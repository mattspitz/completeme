import collections
import logging
import os
import Queue
import re
import threading
import time
import traceback

from .utils import ComputationInterruptedException
from .utils import split_search_dir_and_query

_logger = logging.getLogger(__name__)

EligibleFile = collections.namedtuple("EligibleFile", [ "abs_fn", "abs_match_positions" ])
EligibleFilenames = collections.namedtuple("EligibleFilenames", [ "eligible", "search_complete" ])
class SearchThread(threading.Thread):
    NewInput = collections.namedtuple("NewInput", [ "input_str", "current_search_dir", "candidate_fns", "candidate_computation_complete" ])
    IncrementalInput = collections.namedtuple("IncrementalInput", [ "new_candidate_fns", "candidate_computation_complete" ])
    MatchTuple = collections.namedtuple("MatchTuple", ["abs_fn", "match_str", "abs_match_positions", "num_nonempty_groups", "total_group_length", "num_dirs_in_path" ])

    def __init__(self, initial_input_str, initial_current_filenames):
        super(SearchThread, self).__init__()
        self.daemon = True
        self.ex_traceback = None

        self.input_queue = Queue.Queue()
        self.state_lock = threading.Lock()
        self.should_stop = False

        self.input_str = None
        self.current_search_dir = None
        self.new_candidate_fns = None               # used for incremental search
        self.candidate_fns = None
        self.candidate_computation_complete = None

        self.search_complete = False

        self.eligible_matchtuples = []
        self.eligible_matchtuples_cache = {}        # cache for eligible filenames given an input_str and a current_search_dir

        self.update_input(initial_input_str, initial_current_filenames)

    def get_traceback(self):
        """ Returns the traceback for the exception that killed this thread. """
        return self.ex_traceback

    def _interrupted(self):
        return self.should_stop or not self.input_queue.empty()

    def stop(self):
        self.should_stop = True

    def run(self):
        try:
            while True:
                if self.should_stop:
                    return

                if self.input_queue.empty():
                    # don't hold our state_lock until we have a queued item available
                    time.sleep(0.005)
                    continue

                with self.state_lock:
                    assert not self.input_queue.empty()
                    # clear out the queue in case we had a couple pile up
                    while not self.input_queue.empty():
                        next_input = self.input_queue.get()

                    if isinstance(next_input, self.NewInput):
                        self.input_str = next_input.input_str
                        self.current_search_dir = next_input.current_search_dir
                        self.candidate_fns = next_input.candidate_fns
                        self.new_candidate_fns = None
                        self.candidate_computation_complete = next_input.candidate_computation_complete
                        self.eligible_matchtuples = []

                    elif isinstance(next_input, self.IncrementalInput):
                        self.candidate_fns.update(next_input.new_candidate_fns)
                        self.new_candidate_fns = next_input.new_candidate_fns
                        self.candidate_computation_complete = next_input.candidate_computation_complete

                    else:
                        raise Exception("Unrecognized input!: {}".format(next_input))

                    self.search_complete = False

                try:
                    self._compute_eligible_filenames()
                except ComputationInterruptedException:
                    _logger.debug("Searching interrupted!")
                    continue

                with self.state_lock:
                    self.search_complete = self.input_queue.empty()
        except Exception:
            self.ex_traceback = traceback.format_exc()
            raise

    def update_input(self, input_str, current_filenames):
        """ Queue up computation given a (possibly new) input string and the current state from the FilenameCollectionThread's get_current_filenames() . """
        if any( map(lambda x: x is None, [ input_str, current_filenames.current_search_dir, current_filenames.candidates ]) ):
            # nothing to update!
            return

        query_search_dir, _ = split_search_dir_and_query(input_str)

        if os.path.abspath(query_search_dir) != os.path.abspath(current_filenames.current_search_dir): # abspath rids us of incosistent trailing slashes
            # not ready yet!
            _logger.debug("Next input's search dir {} doesn't match query search dir {} -- skipping this input string.".format(current_filenames.current_search_dir, query_search_dir))
            return

        if (input_str != self.input_str
                or not self.input_queue.empty()):
            # we've got a new input str or we've already queued up input OR we're already going to trigger a new search, so make sure we've got the latest input before we start
            with self.state_lock:
                _logger.debug("Triggering new search with input string '{}' and {:d} candidate filenames.".format(input_str, len(current_filenames.candidates)))
                self.input_queue.put(self.NewInput(
                    input_str=input_str,
                    current_search_dir=current_filenames.current_search_dir,
                    candidate_fns=current_filenames.candidates,
                    candidate_computation_complete=current_filenames.candidate_computation_complete
                    ))

        elif (input_str == self.input_str
                and current_filenames.current_search_dir == self.current_search_dir
                and self.search_complete
                and not self.candidate_computation_complete
                and self.input_queue.empty()):
            # we've found more files in the same directory with the same query and aren't currently interrupted
            # so... add on an incremental search!
            with self.state_lock:
                new_files = current_filenames.candidates.difference(self.candidate_fns)
                _logger.debug("Adding {:d} more files to current search for input_str '{}' in directory {}".format(len(new_files), input_str, current_filenames.current_search_dir))
                self.input_queue.put(self.IncrementalInput(
                    new_candidate_fns=new_files,
                    candidate_computation_complete=current_filenames.candidate_computation_complete
                    ))

    def get_eligible_filenames(self):
        """ Retrieve a current snapshot of what we think are the current eligible filenames. """
        with self.state_lock:
            eligible_fns = [ EligibleFile(abs_fn=match.abs_fn, abs_match_positions=match.abs_match_positions) for match in self.eligible_matchtuples ]
            search_complete = self.search_complete

        return EligibleFilenames(eligible=eligible_fns, search_complete=search_complete)

    @staticmethod
    def _matchtuple_cmp(match_one, match_two):
        """ TODO!
        first, obviously, best match (num_nonempty_groups, total_group_length)

        then...
        prefer files in this directory (num_dirs_in_path==0)

        prefer all directories in this directory, followed by their filenames (recursively)
        e.g.
            a/
            a/stuff.txt
            a/b/
            a/b/c/
            a/b/c/things.dat
            a/b/c/zebras.zoo
            x/
            x/stuff.txt
            x/y/
            x/y/z/
            x/y/z/wowza.txt

        finally, compare the LOWERED filenames (README < hithere.txt)

        Note: maybe we'll need to keep track of all the directory names in the path when we create the matchtuple?
        """

        # prefer the fewest number of empty groups (fewest gaps in fuzzy matching)
        # (more nonempty groups -> show up later in the list)
        diff = match_one.num_nonempty_groups - match_two.num_nonempty_groups
        if diff != 0:
            return diff

        # then the shortest total length of all groups (prefer "MyGreatFile.txt" over "My Documents/stuff/File.txt")
        diff = match_one.total_group_length - match_two.total_group_length
        if diff != 0:
            return diff

        if match_one.num_dirs_in_path == 0 and match_two.num_dirs_in_path > 0:
            return -1
        elif match_two.num_dirs_in_path == 0 and match_one.num_dirs_in_path > 0:
            return 1

        # and finally in lexicographical order
        return cmp(match_one.match_str.lower(), match_two.match_str.lower())

    def _compute_eligible_filenames(self):
        """ Return a sorted ordering of the filenames based on this input string.

        All filenames that match the input_string are included, and we prefer those
        that match on word boundaries.
        """
        _, query_str = split_search_dir_and_query(self.input_str)

        lowered = query_str.lower()
        if len(lowered) >= 100:
            # more helpful explanation for the exception we'll get with regex.compile()
            raise Exception("python2.7 supports only 100 named groups, so this isn't going to work.  What're you doing searching for a string with >= 100 characters?")

        def make_cache_key(search_dir, normalized_input):
            return (search_dir, normalized_input)

        cache_key = make_cache_key(self.current_search_dir, lowered)

        def is_incremental_search():
            return self.new_candidate_fns is not None

        def get_num_dirs_in_path(fn):
            count = 0
            initial_val, last_val = fn, None
            while fn:
                head, _ = os.path.split(fn)
                if head in ("", "/"):
                    break
                count += 1
                fn = head
                if fn == last_val: raise Exception("Hit infinite loop while computing dirs for {}!".format(initial_val))
                last_val = fn
            return count

        def perform_search():
            if cache_key in self.eligible_matchtuples_cache:
                _logger.debug("Found cached eligible_matchtuples key: {}".format(cache_key))
                return self.eligible_matchtuples_cache[cache_key]

            if is_incremental_search():
                initial_filenames = self.new_candidate_fns
            else:
                # if this query is at least two characters long and the prefix minus this last letter has already been computed, start with those eligible filenames
                # no need to prune down the whole list if we've already limited the search space
                prev_cache_key = make_cache_key(self.current_search_dir, lowered[:-1])
                if len(lowered) >= 2 and prev_cache_key in self.eligible_matchtuples_cache:
                    initial_filenames = [ match.abs_fn for match in self.eligible_matchtuples_cache[prev_cache_key] ]
                else:
                    initial_filenames = self.candidate_fns

            _logger.debug("Searching {:d} files for '{}'{}".format(len(initial_filenames), lowered, " (incremental!)" if is_incremental_search() else ""))

            def get_match_tuples_it(filter_regex=None, ranking_regex=None):
                assert (filter_regex is not None and ranking_regex is not None) or (filter_regex is None and ranking_regex is None)

                LOCK_BATCH_SIZE = 100
                for idx, abs_fn in enumerate(initial_filenames):
                    if idx % LOCK_BATCH_SIZE == 0 and self._interrupted():
                        raise ComputationInterruptedException("Searching interrupted!")

                    assert abs_fn.startswith(self.current_search_dir), "expected {} to start with {}!".format(abs_fn, self.current_search_dir)
                    trimmed_fn = abs_fn[len(self.current_search_dir):]

                    if filter_regex is not None:
                        filter_match = filter_regex.search(trimmed_fn)

                        if filter_match is None:
                            continue
                        ranking_match = ranking_regex.search(trimmed_fn)
                        nonempty_groups = []
                        match_positions = []
                        cur_abs_pos = len(self.current_search_dir) # position relative to the absolute file (ranking match peels off the current_search_dir!)
                        for idx, group in enumerate(ranking_match.groups()):
                            if idx > 0 and group: # skip the group that starts the file when calculating nonempty groups
                                nonempty_groups.append(group)

                            cur_abs_pos += len(group)           # skip the group
                            match_positions.append(cur_abs_pos) # add the matched character
                            cur_abs_pos += 1                    # consume the character
                    else:
                        nonempty_groups = []
                        match_positions = []

                    yield self.MatchTuple(
                            abs_fn=abs_fn,
                            match_str=trimmed_fn,
                            abs_match_positions=match_positions,
                            num_nonempty_groups = len(nonempty_groups),
                            total_group_length=len("".join(nonempty_groups)),
                            num_dirs_in_path=get_num_dirs_in_path(trimmed_fn)
                            )
            if lowered == "":
                _logger.debug("Returning all candidates for empty input str.")
                return list(get_match_tuples_it())
            else:
                # fuzzy matching: for input string abc, find a*b*c substrings (consuming as few characters as possible in between)
                # guard against user input that may be construed as a regex
                regex_str = "(.*?)".join( re.escape(ch) for ch in lowered )
                filter_regex = re.compile(regex_str, re.IGNORECASE | re.DOTALL)
                # prepend (?:.*) to push off the matching as much as possible (more expensive but more accurate)
                ranking_regex = re.compile("(.*)" + regex_str, re.IGNORECASE | re.DOTALL)

                return list(get_match_tuples_it(filter_regex=filter_regex, ranking_regex=ranking_regex))

        if is_incremental_search():
            eligible_matchtuples = self.eligible_matchtuples + perform_search()
        else:
            eligible_matchtuples = perform_search()

        # need to re-sort if incremental!
        eligible_matchtuples.sort(cmp=self._matchtuple_cmp)
        _logger.debug("Found {:d} eligible matchtuples.".format(len(eligible_matchtuples)))

        with self.state_lock:
            self.eligible_matchtuples = eligible_matchtuples

            if self.candidate_computation_complete: # if we're dealing with a complete set of candidates, cache the results
                self.eligible_matchtuples_cache[cache_key] = eligible_matchtuples
