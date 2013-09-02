import collections
import copy
import logging
import os
import Queue
import subprocess
import threading
import time
import traceback

from .utils import ComputationInterruptedException, UNINITIALIZED
from .utils import get_config, split_search_dir_and_query

_logger = logging.getLogger(__name__)

CurrentFilenames = collections.namedtuple("CurrentFilenames", [ "candidates", "candidate_computation_complete", "git_root_dir", "current_search_dir" ])
class FilenameCollectionThread(threading.Thread):
    def __init__(self, initial_input_str):
        super(FilenameCollectionThread, self).__init__()
        self.daemon = True
        self.ex_traceback = None

        self.should_stop = False
        self.search_dir_queue = Queue.Queue()
        self.state_lock = threading.Lock()            # for updating shared state

        self.current_search_dir = None                # only re-run find/git if the search directory changes
        self.candidate_computation_complete = False   # are we done getting all filenames for the current search directory?
        self.candidate_fns_cache = {}                 # cache for candidate filenames given an input_str
        self.candidate_fns = UNINITIALIZED            # current set of candidate functions
        self.git_root_dir = UNINITIALIZED             # git root directory

        self.update_input_str(initial_input_str)

    def get_traceback(self):
        """ Returns the traceback for the exception that killed this thread. """
        return self.ex_traceback

    def _interrupted(self):
        return self.should_stop or not self.search_dir_queue.empty()

    def stop(self):
        self.should_stop = True

    def state_is_consistent(self):
        """ Returns true if the state of this thread is consistent enough to trust the results.  That is, the filenames returned and the metadata (git_root_dir) are in sync. """
        with self.state_lock:
            return self.git_root_dir != UNINITIALIZED and self.candidate_fns != UNINITIALIZED

    def run(self):
        try:
            while True:
                if self.should_stop:
                    return

                if self.search_dir_queue.empty():
                    # don't hold the state lock until we have a queued search_dir available
                    time.sleep(0.005)
                    continue

                with self.state_lock:
                    assert not self.search_dir_queue.empty()
                    # clear out the queue in case we had multiple strings queued up
                    while not self.search_dir_queue.empty():
                        next_search_dir = self.search_dir_queue.get()

                    self.current_search_dir = next_search_dir

                    # indicate that we're not done computing
                    self.candidate_computation_complete = False

                    # reset
                    self.candidate_fns = set()

                try:
                    self._compute_candidates()
                except ComputationInterruptedException:
                    _logger.debug("Candidate computation interrupted!")
                    continue

                with self.state_lock:
                    # this set of candidate filenames is definitely done, so add it to the cache!
                    self.candidate_fns_cache[self.current_search_dir] = self.candidate_fns

                    # we're done, as long as no one has queued us up for more
                    self.candidate_computation_complete = self.search_dir_queue.empty()
        except Exception:
            self.ex_traceback = traceback.format_exc()
            raise

    @staticmethod
    def _get_shell_output(cmd):
        # don't use check_output because it won't swallow stderr
        return subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()[0]

    def _compute_candidates(self):
        """ The actual meat of computing the candidate filenames. """
        try:
            git_root_dir = self._get_shell_output("cd {} && git rev-parse --show-toplevel".format(self.current_search_dir)).strip() or None
        except subprocess.CalledProcessError:
            git_root_dir = None

        with self.state_lock:
            self.git_root_dir = git_root_dir

        def append_batched_filenames(cmd, base_dir=None, shell=False, add_dirnames=False):
            """ Adds all the files from the output of this command to our candidate_fns in batches. """
            BATCH_SIZE = 100

            proc = subprocess.Popen(cmd, shell=shell, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            _logger.debug("Started cmd {} with pid {:d}".format(cmd, proc.pid))
            batch = set()
            while True:
                if self._interrupted():
                    _logger.debug("Command interrupted.  Killing pid {:d}.".format(proc.pid))
                    try:
                        proc.kill()
                        proc.communicate()
                    except OSError:
                        pass
                    raise ComputationInterruptedException("Interrupted while executing: {}".format(cmd))

                nextline = proc.stdout.readline().strip()
                if nextline == "" and proc.poll() != None:
                    break

                fn = os.path.join(base_dir, nextline) if base_dir is not None else nextline
                if not fn:
                    continue

                abs_fn = os.path.abspath(fn)
                if add_dirnames:
                    def add_dirs_rec(name):
                        if name != self.current_search_dir and name not in batch:
                            batch.add(name)
                            add_dirs_rec(os.path.dirname(name))
                    add_dirs_rec(abs_fn)
                else:
                    batch.add(abs_fn)

                if len(batch) >= BATCH_SIZE:
                    with self.state_lock:
                        self.candidate_fns.update(batch)
                        batch = set()

            if batch:
                with self.state_lock:
                    # clean up the stragglers
                    self.candidate_fns.update(batch)

        cache_key = self.current_search_dir
        if cache_key in self.candidate_fns_cache:
            _logger.debug("Found candidate_fn cache key: {}".format(cache_key))
            with self.state_lock:
                self.candidate_fns.update(self.candidate_fns_cache[cache_key])

        elif self.git_root_dir is not None:
            # return files that git recognizes

            # start with this current search directory
            search_dirs = [ self.current_search_dir ]

            # add all subdirectories (which are rooted at git_root_dir)
            # ...note that we can't just split on " " because the first character is either a space or a -
            for submodule in self._get_shell_output("cd {} && git submodule status --recursive | cut -b43- | cut --delim=' ' -f1".format(self.git_root_dir)).split():
                _logger.debug("Found submodule: {}".format(submodule))
                submodule_root = os.path.join(self.git_root_dir, submodule)
                if submodule_root.startswith(self.current_search_dir):
                    search_dirs.append(submodule_root)

            for search_dir in search_dirs:
                for shell_cmd in (
                        "git ls-files --cached",
                        "git ls-files --exclude-standard --others"):
                    append_batched_filenames("cd {} && {}".format(search_dir, shell_cmd), base_dir=search_dir, shell=True, add_dirnames=get_config("include_directories"))

        else:
            # return all files in the current_search_dir
            find_cmd = ["find", "-L", self.current_search_dir]
            if not get_config("find_hidden_directories"):
                find_cmd += ["-not", "-path", "*/.*/*"]
            if not get_config("find_hidden_files"):
                find_cmd += ["-not", "-name", ".*"]

            if get_config("include_directories"):
                append_batched_filenames(find_cmd + ["-type", "d"])
            append_batched_filenames(find_cmd + ["-type", "f"])

    def update_input_str(self, input_str):
        """ Determines the appropriate directory and queues a recompute of eligible files matching the input string. """
        new_search_dir, _ = split_search_dir_and_query(input_str)

        if new_search_dir != self.current_search_dir:
            with self.state_lock:
                _logger.debug("Switching search directory from {} to {}".format(self.current_search_dir, new_search_dir))
                self.search_dir_queue.put(new_search_dir)

    def get_current_filenames(self):
        """ Get all the relevant filenames given the input string, whether we're done computing them or not. """

        with self.state_lock:
            candidate_fns = copy.copy(self.candidate_fns)
            candidate_computation_complete = self.candidate_computation_complete
            git_root_dir = self.git_root_dir
            current_search_dir = self.current_search_dir

        return CurrentFilenames(candidates=candidate_fns, candidate_computation_complete=candidate_computation_complete, git_root_dir=git_root_dir, current_search_dir=current_search_dir)
