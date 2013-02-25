#!/usr/bin/env python2.7

import collections
import copy
import curses
import itertools
import json
import logging
import os
import Queue
import re
import shlex
import subprocess
import sys
import threading
import time

import pkg_resources


logging.basicConfig(level=logging.DEBUG if os.environ.get("DEBUG") else logging.ERROR,
                    format="%(asctime)s: %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")
_logger = logging.getLogger(__name__)

CONFIG_FN = pkg_resources.resource_filename(__name__, "conf/completeme.json")
def get_config(key, default="NO_DEFAULT"):
    """ Returns the value for the config key, loading first from the working directory and then the basic install point.  Can be overridden with CONFIG_FN environment variable. """

    def load_config():
        CONFIG_CACHE_KEY = "cached_config"
        if hasattr(get_config, CONFIG_CACHE_KEY):
            return getattr(get_config, CONFIG_CACHE_KEY)

        base_fn = os.path.basename(CONFIG_FN)
        fn_paths = [ os.path.join("conf", base_fn),
                     CONFIG_FN ]
        if "CONFIG_FN" in os.environ:
            fn_paths.append(os.environ["CONFIG_FN"])

        for fn in fn_paths:
            try:
                cfg = json.load(open(fn, "r"))
                setattr(get_config, CONFIG_CACHE_KEY, cfg)
                return cfg
            except IOError:
                pass

        raise Exception("Couldn't load config from any of {}".format(fn_paths))

    return load_config()[key] if default == "NO_DEFAULT" else load_config().get(key, default)

HIGHLIGHT_COLOR_PAIR = 1
STATUS_BAR_COLOR_PAIR = 2
NEWLINE = "^J"
TAB = "^I"
def init_screen():
    screen = curses.initscr()
    curses.start_color()
    curses.init_pair(HIGHLIGHT_COLOR_PAIR, curses.COLOR_RED, curses.COLOR_WHITE)
    curses.init_pair(STATUS_BAR_COLOR_PAIR, curses.COLOR_GREEN, curses.COLOR_BLACK)
    screen.keypad(1)
    screen.nodelay(1) # nonblocking input
    return screen

def cleanup_curses():
    curses.nocbreak()
    curses.echo()
    curses.endwin()

class ComputationInterruptedException(Exception):
    pass

CurrentFilenames = collections.namedtuple("CurrentFilenames", [ "candidates", "candidate_computation_complete", "git_root_dir", "current_search_dir", "uuid" ])
class FilenameCollectionThread(threading.Thread):
    def __init__(self, initial_input_str):
        super(FilenameCollectionThread, self).__init__()
        self.daemon = True

        self.search_dir_queue = Queue.Queue()
        self.state_lock = threading.Lock()            # for updating shared state

        self.current_search_dir = None                # only re-run find/git if the search directory changes
        self.candidate_computation_complete = False   # are we done getting all filenames for the current search directory?
        self.candidate_fns_cache = {}                 # cache for candidate filenames given an input_str
        self.candidate_fns = []                       # current set of candidate functions
        self.git_root_dir = None                      # git root directory

        self.update_input_str(initial_input_str)

    def _interrupted(self):
        return not self.search_dir_queue.empty()

    def run(self):
        while True:
            next_search_dir = self.search_dir_queue.get()
            with self.state_lock:
                # clear out the queue in case we had multiple strings queued up
                while not self.search_dir_queue.empty():
                    next_search_dir = self.search_dir_queue.get()

                self.current_search_dir = next_search_dir

                # indicate that we're not done computing
                self.candidate_computation_complete = False

                # reset
                self.candidate_fns = []

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

    def _compute_candidates(self):
        """ The actual meat of computing the candidate filenames. """
        try:
            # don't use check_output because it won't swallow stdout
            git_root_dir = subprocess.Popen("cd {} && git rev-parse --show-toplevel".format(self.current_search_dir),
                        shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()[0].strip() or None
        except subprocess.CalledProcessError:
            git_root_dir = None

        with self.state_lock:
            self.git_root_dir = git_root_dir

        def append_batched_filenames(shell_cmd, absolute_path=False, base_dir=None):
            """ Adds all the files from the output of this command to our candidate_fns in batches. """
            BATCH_SIZE = 100

            _logger.debug("running shell cmd {}".format(shell_cmd))
            proc = subprocess.Popen(shell_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            batch = []
            while True:
                if self._interrupted():
                    raise ComputationInterruptedException("Interrupted while executing: {}".format(shell_cmd))

                nextline = proc.stdout.readline().strip()
                if nextline == "" and proc.poll() != None:
                    break

                fn = os.path.join(base_dir, nextline) if base_dir is not None else nextline
                batch.append(os.path.abspath(fn) if absolute_path else os.path.relpath(fn))

                if len(batch) >= BATCH_SIZE:
                    with self.state_lock:
                        self.candidate_fns.extend(batch)
                        batch = []

            with self.state_lock:
                # clean up the stragglers
                self.candidate_fns.extend(batch)

        if self.git_root_dir is not None:
            # return all files in this git tree
            for shell_cmd in ("git ls-tree --full-tree -r HEAD" if get_config("git_entire_tree") else "git ls-tree -r HEAD",
                    "git ls-files --exclude-standard --others"):
                append_batched_filenames("cd {} && {} | cut -f2".format(self.current_search_dir, shell_cmd), base_dir=self.git_root_dir)
        else:
            # return all files in the current_search_dir
            find_cmd = "find -L {} -type f".format(self.current_search_dir)
            if not get_config("find_hidden_directories"):
                find_cmd = "{} {}".format(find_cmd, "-not -path '*/.*/*'")
            if not get_config("find_hidden_files"):
                find_cmd = "{} {}".format(find_cmd, "-not -name '.*'")
            append_batched_filenames(find_cmd, absolute_path=os.path.isabs(self.current_search_dir))

    def update_input_str(self, input_str):
        """ Determines the appropriate directory and queues a recompute of eligible files matching the input string. """
        new_search_dir = self._guess_root_directory(input_str)

        if new_search_dir != self.current_search_dir:
            with self.state_lock:
                _logger.debug("Switching search directory from {} to {}.".format(self.current_search_dir, new_search_dir))
                self.search_dir_queue.put(new_search_dir)

    def get_current_filenames(self):
        """ Get all the relevant filenames given the input string, whether we're done computing them or not. """

        with self.state_lock:
            candidate_fns = copy.copy(self.candidate_fns)
            candidate_computation_complete = self.candidate_computation_complete
            git_root_dir = self.git_root_dir
            current_search_dir = self.current_search_dir

        # useful for summarizing the current state
        uuid = hash("".join( [current_search_dir] + candidate_fns ))

        return CurrentFilenames(candidates=candidate_fns, candidate_computation_complete=candidate_computation_complete, git_root_dir=git_root_dir, current_search_dir=current_search_dir, uuid=uuid)

    def _guess_root_directory(self, input_str):
        """ Given an input_str, deduce what directory we should search, either by relative path (../../whatever) or by absolute path (/). """
        # TODO return whether the path is absolute (starts with /)
        # If the path is absolute, display as absolute
        # If the path is relative, display as relative
        return "."

EligibleFilenames = collections.namedtuple("EligibleFilenames", [ "eligible", "search_complete" ])
class SearchThread(threading.Thread):
    def __init__(self, initial_input_str, initial_current_filenames):
        super(SearchThread, self).__init__()
        self.daemon = True

        self.input_queue = Queue.Queue()
        self.state_lock = threading.Lock()

        self.input_str = None
        self.current_filenames = None

        self.search_complete = False

        self.eligible_fns = []
        self.eligible_fns_cache = {}        # cache for eligible filenames given an input_str and a current_search_dir

        self.update_input(initial_input_str, initial_current_filenames)

    def _interrupted(self):
        return not self.input_queue.empty()

    def run(self):
        while True:
            next_input_str, next_current_filenames = self.input_queue.get()
            with self.state_lock:
                # clear out the queue in case we had a couple pile up
                while not self.input_queue.empty():
                    next_input_str, next_current_filenames = self.input_queue.get()

                self.input_str = next_input_str
                self.current_filenames = next_current_filenames

                self.search_complete = False
                self.eligible_fns = []

            try:
                self._compute_eligible_filenames()
            except ComputationInterruptedException:
                _logger.debug("Searching interrupted!")
                continue

            with self.state_lock:
                self.search_complete = self.input_queue.empty()

    def update_input(self, input_str, current_filenames):
        """ Queue up computation given a (possibly new) input string and the current state from the FilenameCollectionThread's get_current_filenames() . """
        if (input_str != self.input_str
                or self.current_filenames.uuid != current_filenames.uuid):
            with self.state_lock:
                _logger.debug("Triggering new search with input string '{}' and {:d} candidate filenames.".format(input_str, len(current_filenames.candidates)))
                self.input_queue.put( (input_str, current_filenames) )

    def get_eligible_filenames(self):
        """ Retrieve a current snapshot of what we think are the current eligible filenames. """
        with self.state_lock:
            eligible_fns = copy.copy(self.eligible_fns)
            search_complete = self.search_complete

        return EligibleFilenames(eligible=eligible_fns, search_complete=search_complete)

    def _compute_eligible_filenames(self):
        """ Return a sorted ordering of the filenames based on this input string.

        All filenames that match the input_string are included, and we prefer those
        that match on word boundaries.
        """
        _logger.debug("Starting search with input string '{}'.".format(self.input_str))

        candidate_fns, current_search_dir, candidate_computation_complete = self.current_filenames.candidates, self.current_filenames.current_search_dir, self.current_filenames.candidate_computation_complete

        lowered = self.input_str.lower()
        if len(lowered) >= 100:
            # more helpful explanation for the exception we'll get with regex.compile()
            raise Exception("python2.7 supports only 100 named groups, so this isn't going to work.  What're you doing searching for a string with >= 100 characters?")

        def make_cache_key(search_dir, normalized_input):
            return (os.path.abspath(search_dir), normalized_input)

        cache_key = make_cache_key(current_search_dir, lowered)
        def perform_search():
            if lowered == "":
                return candidate_fns

            with self.state_lock:
                if cache_key in self.eligible_fns_cache:
                    _logger.debug("Found cached eligible_fns key: {}".format(cache_key))
                    return self.eligible_fns_cache[cache_key]

            # if this query is at least two characters long and the prefix minus this last letter has already been computed, start with those eligible filenames
            # no need to prune down the whole list if we've already limited the search space
            with self.state_lock:
                initial_filenames = (self.eligible_fns_cache.get(make_cache_key(current_search_dir, lowered[:-1]), candidate_fns)
                        if len(lowered) >= 2
                        else candidate_fns)

            _logger.debug("Searching {:d} files for '{}'".format(len(initial_filenames), lowered))

            # fuzzy matching: for input string abc, find a*b*c substrings (consuming as few characters as possible in between)
            # guard against user input that may be construed as a regex
            regex_str = "(.*?)".join( re.escape(ch) for ch in lowered )
            regex = re.compile(regex_str, re.IGNORECASE | re.DOTALL)

            MatchTuple = collections.namedtuple("MatchTuple", ["string", "num_nonempty_groups", "total_group_length"])
            def get_match_tuples_it():
                def nonempty_groups(match):
                    return filter(lambda x: x, match.groups())

                for fn in initial_filenames:
                    if self._interrupted():
                        raise ComputationInterruptedException("Searching interrupted!")

                    match = regex.search(fn)
                    if match is not None:
                        negs = nonempty_groups(match)
                        yield MatchTuple(
                                string=match.string,
                                num_nonempty_groups = len(negs),
                                total_group_length=len("".join(negs))
                                )

            def matchtuple_cmp(match_one, match_two):
                # prefer the fewest number of empty groups (fewest gaps in fuzzy matching)

                # (more nonempty groups -> show up later in the list)
                diff = match_one.num_nonempty_groups - match_two.num_nonempty_groups
                if diff != 0:
                    return diff

                # then the shortest total length of all groups (prefer "MyGreatFile.txt" over "My Documents/stuff/File.txt")
                diff = match_one.total_group_length - match_two.total_group_length
                if diff != 0:
                    return diff

                # and finally in lexicographical order
                return cmp(match_one.string, match_two.string)

            return [ match.string for match in sorted(get_match_tuples_it(), cmp=matchtuple_cmp) ]

        eligible_fns = perform_search()
        _logger.debug("Found {:d} eligible filenames for input string '{}'".format(len(eligible_fns), self.input_str))

        with self.state_lock:
            self.eligible_fns = eligible_fns
            if candidate_computation_complete: # if we're dealing with a complete set of candidates, cache the results
                self.eligible_fns_cache[cache_key] = self.eligible_fns

def select_filename(screen, fn_collection_thread, input_str):
    highlighted_pos = 0
    key_name = None

    search_thread = SearchThread(input_str, fn_collection_thread.get_current_filenames())
    search_thread.start()

    while True:
        screen.clear()

        fn_collection_thread.update_input_str(input_str)
        curr_fns = fn_collection_thread.get_current_filenames()

        search_thread.update_input(input_str, curr_fns)
        eligible_fns = search_thread.get_eligible_filenames()

        if not eligible_fns.search_complete:
            highlighted_pos = 0

        highlighted_fn = eligible_fns.eligible[highlighted_pos] if eligible_fns.eligible else None

        STATUS_BAR_Y = 0      # status bar first!
        INPUT_Y = 2           # where the input line should go
        FN_OFFSET = 3         # first Y coordinate of a filename
        max_height, max_width = screen.getmaxyx()
        max_files_to_show = min(len(eligible_fns.eligible), max_height - FN_OFFSET)

        def add_line(y, x, line, attr, fill_line=False):
            s = line[-(max_width - 1):]
            if fill_line:
                s = s.ljust(max_width - 1, " ")
            try:
                screen.addstr(y, x, s, attr)
            except Exception:
                _logger.debug("Couldn't add string to screen: {}".format(s))

        # add status bar
        status_text = "{:d}{} of {:d}{} candidate filenames{}".format(
                len(eligible_fns.eligible),
                "*" if not eligible_fns.search_complete else "",
                len(curr_fns.candidates),
                "*" if not curr_fns.candidate_computation_complete else "",
                " (git: {})".format(curr_fns.git_root_dir) if curr_fns.git_root_dir is not None else "")
        add_line(STATUS_BAR_Y, 0, status_text, curses.color_pair(STATUS_BAR_COLOR_PAIR), fill_line=True)

        # input line
        add_line(INPUT_Y, 0, input_str, curses.A_UNDERLINE, fill_line=True)

        for pos, fn in enumerate(eligible_fns.eligible[:max_files_to_show]):
            attr = curses.color_pair(HIGHLIGHT_COLOR_PAIR) if pos == highlighted_pos else curses.A_NORMAL
            add_line(FN_OFFSET + pos, 0, fn, attr)

        screen.refresh()

        # put the cursor at the end of the string
        input_x = min(len(input_str), max_width - 1)

        # getch is nonblocking; try in 20ms increments for up to 200ms before redrawing screen
        start_getch = time.time()
        raw_key = -1
        while (time.time() - start_getch) < 0.200:
            raw_key = screen.getch(INPUT_Y, input_x)
            if raw_key != -1: break
            time.sleep(0.020)

        if raw_key == -1:
            continue

        key_name = curses.keyname(raw_key)

        if key_name == NEWLINE:
            # open the file in $EDITOR
            open_file(highlighted_fn)
            return
        elif key_name == TAB:
            # dump the character back to the prompt
            dump_to_prompt(highlighted_fn)
            return

        elif key_name == "KEY_DOWN":
            highlighted_pos = min(highlighted_pos + 1, max_files_to_show - 1)
        elif key_name == "KEY_UP":
            highlighted_pos = max(highlighted_pos - 1, 0)
        elif key_name == "KEY_NPAGE": # page down
            highlighted_pos = max_files_to_show - 1
        elif key_name == "KEY_PPAGE": # page up
            highlighted_pos = 0
        else:
            if key_name in ["KEY_BACKSPACE", "^?"]:   # delete single character
                input_str = input_str[:-1]
            elif key_name == "^W":                    # delete whole line
                input_str = ""
            elif (key_name.startswith("KEY_")
                    or key_name.startswith("^")):     # just ignore it
                continue
            else:                                     # add character (doesn't special key checking)
                input_str += key_name

            # at this point, input_str has changed, so reset the highlighted_pos
            highlighted_pos = 0

    # something's definitely not right
    raise Exception("Should be unreachable.  Exit this function within the loop!")

def dump_to_prompt(fn):
    if fn:
        with open('/tmp/completeme.sh', 'wb') as f:
            new_token = fn + " " # add a space at the end for the next argument
            print >> f, "READLINE_LINE='{}'".format(os.environ.get("READLINE_LINE", "") + new_token),
            print >> f, "READLINE_POINT='{}'".format(int(os.environ.get("READLINE_POINT", 0)) + len(new_token))

def open_file(fn):
    if fn:
        editor_cmd = os.getenv("EDITOR")
        if editor_cmd is None:
            raise Exception("Environment variable $EDITOR is missing!")

        subprocess.call(shlex.split(editor_cmd) + [fn])
        subprocess.call("bash -i -c 'history -s \"{} {}\"'".format(editor_cmd, fn), shell=True)

def get_initial_input_str():
    """ Returns the string that should seed our search.

    TODO parse the existing commandline (READLINE_LINE, READLINE_POINT).
    If we're in the middle of typing something, seed with that argument.
    """
    return ""

def main():
    initial_input_str = get_initial_input_str()
    fn_collection_thread = FilenameCollectionThread(initial_input_str)
    fn_collection_thread.start()
    try:
        screen = init_screen()
        select_filename(screen, fn_collection_thread, initial_input_str)
    except KeyboardInterrupt:
        pass
    finally:
        cleanup_curses()

if __name__ == "__main__":
    if os.environ.get("RUN_PROFILER"):
        import cProfile
        import pstats
        import tempfile
        _, profile_fn = tempfile.mkstemp()
        cProfile.run("main()", profile_fn)
        pstats.Stats(profile_fn).sort_stats("cumulative").print_stats()
    else:
        main()
