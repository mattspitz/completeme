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

_logger = None

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

class CandidateComputationInterruptedException(Exception):
    pass

CurrentFilenames = collections.namedtuple("CurrentFilenames", [ "candidates", "eligible", "candidate_computation_complete", "git_root_dir" ])
class FilenameSearchThread(threading.Thread):
    def __init__(self, initial_input_str):
        super(FilenameSearchThread, self).__init__()
        self.daemon = True

        self.interrupted = threading.Event()
        self.input_str_queue = Queue.Queue()
        self.state_lock = threading.Lock()            # for updating shared state

        self.current_search_dir = None                # only re-run find/git if the search directory changes
        self.candidate_computation_complete = False   # are we done getting all filenames for the current search directory?
        self.candidate_fns_cache = {}                 # cache for candidate filenames given an input_str
        self.eligible_fns_cache = {}                  # cache for eligible filenames given an input_str and a current_search_dir
        self.candidate_fns = []                       # current set of candidate functions
        self.git_root_dir = None                           # git root directory

        self.input_str = None
        self.update_input_str(initial_input_str)

    def run(self):
        while True:
            next_input_str = self.input_str_queue.get()
            with self.state_lock:
                # clear out the queue in case we had multiple strings queued up
                while not self.input_str_queue.empty():
                    next_input_str = self.input_str_queue.get()

                # allow ourselves to be interrupted again
                self.interrupted.clear()

                # indicate that we're not done computing
                self.candidate_computation_complete = False

                # reset
                self.candidate_fns = []

            try:
                # don't use check_output because it won't swallow stdout
                git_root_dir = subprocess.Popen("cd {} && git rev-parse --show-toplevel".format(self.current_search_dir),
                    shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()[0].strip() or None
            except subprocess.CalledProcessError:
                git_root_dir = None

            with self.state_lock:
                self.git_root_dir = git_root_dir

            def append_batched_filenames(shell_cmd):
                """ Adds all the files from the output of this command to our candidate_fns in batches. """
                _logger.debug("running shell cmd {}".format(shell_cmd))
                proc = subprocess.Popen(shell_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                while True:
                    if self.interrupted.is_set():
                        raise CandidateComputationInterruptedException("Interrupted while executing: {}".format(shell_cmd))

                    # TODO batch these
                    nextline = proc.stdout.readline()
                    if nextline == "" and proc.poll() != None:
                        return

                    with self.state_lock:
                        self.candidate_fns.append(nextline.strip())

            try:
                if self.git_root_dir is not None:
                    # return all files in this git tree
                    # TODO these two git commands will affect the absolute path we use for searching (the former is joined with git_root_dir, the latter is joined with os.getcwd()
                    for shell_cmd in ("git ls-tree --full-tree -r HEAD" if get_config("git_entire_tree") else "git ls-tree -r HEAD",
                            "git ls-files --exclude-standard --others"):
                        append_batched_filenames("cd {} && {} | cut -f2".format(self.current_search_dir, shell_cmd))
                else:
                    # return all files in the current_search_dir
                    find_cmd = "find -L {} -type f".format(self.current_search_dir)
                    if not get_config("find_hidden_directories"):
                        find_cmd = "{} {}".format(find_cmd, "-not -path '*/.*/*'")
                    if not get_config("find_hidden_files"):
                        find_cmd = "{} {}".format(find_cmd, "-not -name '.*'")
                    append_batched_filenames(find_cmd)
            except CandidateComputationInterruptedException:
                continue

            with self.state_lock:
                self.candidate_fns_cache[self.current_search_dir] = self.candidate_fns
                # we're done, as long as no one has queued us up for more
                self.candidate_computation_complete = self.input_str_queue.empty()

    def update_input_str(self, input_str):
        """ Determines the appropriate directory and queues a recompute of eligible files matching the input string. """
        old_search_dir = self.current_search_dir
        self.current_search_dir = self._guess_root_directory(input_str)

        with self.state_lock:
            self.input_str = input_str
            if old_search_dir != self.current_search_dir:
                self.input_str_queue.put(input_str)
                self.interrupted.set()

    def get_current_filenames(self):
        """ Get all the relevant filenames given the input string, whether we're done computing them or not. """

        with self.state_lock:
            candidate_fns = copy.copy(self.candidate_fns)
            candidate_computation_complete = self.candidate_computation_complete
            git_root_dir = self.git_root_dir
            input_str = self.input_str
            current_search_dir = self.current_search_dir

        eligible_fns = self._compute_eligible_filenames(input_str, candidate_fns, current_search_dir, candidate_computation_complete)

        return CurrentFilenames(candidates=candidate_fns, eligible=eligible_fns, candidate_computation_complete=candidate_computation_complete, git_root_dir=git_root_dir)

    def _compute_eligible_filenames(self, input_str, candidate_fns, current_search_dir, candidate_computation_complete):
        """ Return a sorted ordering of the filenames based on this input string.

        All filenames that match the input_string are included, and we prefer those
        that match on word boundaries.

        Note that we don't ever lock the eligible_fns_cache.  This will only be accessed by the main (I/O) thread, so no need to lock. """

        lowered = input_str.lower()
        if len(lowered) >= 100:
            # more helpful explanation for the exception we'll get with regex.compile()
            raise Exception("python2.7 supports only 100 named groups, so this isn't going to work.  What're you doing searching for a string with >= 100 characters?")

        def make_cache_key(search_dir, normalized_input):
            return (os.path.abspath(search_dir), normalized_input)

        cache_key = make_cache_key(current_search_dir, lowered)
        if cache_key in self.eligible_fns_cache:
            return self.eligible_fns_cache[cache_key]

        # if this query is at least two characters long and the prefix minus this last letter has already been computed, start with those eligible filenames
        # no need to prune down the whole list if we've already limited the search space
        initial_filenames = (self.eligible_fns_cache.get(make_cache_key(current_search_dir, lowered[:-1]), candidate_fns)
                if len(lowered) >= 2
                else candidate_fns)

        # fuzzy matching: for input string abc, find a*b*c substrings (consuming as few characters as possible in between)
        # guard against user input that may be construed as a regex
        regex_str = "(.*?)".join( re.escape(ch) for ch in lowered )
        regex = re.compile(regex_str, re.IGNORECASE | re.DOTALL)

        # we use filter rather than a list comprehension to avoid computing
        # re.search() more than once per filename
        matches = filter(lambda match: match is not None,
                         ( regex.search(fn) for fn in initial_filenames ))

        def match_cmp(match_one, match_two):
            # prefer the fewest number of empty groups (fewest gaps in fuzzy matching)
            def nonempty_groups(match):
                return filter(lambda x: x,
                              match.groups())

            one_groups, two_groups = nonempty_groups(match_one), nonempty_groups(match_two)

            diff = len(one_groups) - len(two_groups) # (more nonempty groups -> show up later in the list)
            if diff != 0:
                return diff

            # then the shortest total length of all groups (prefer "MyGreatFile.txt" over "My Documents/stuff/File.txt")
            diff = len("".join(one_groups)) - len("".join(two_groups))
            if diff != 0:
                return diff

            # and finally in lexicographical order
            return cmp(match_one.string, match_two.string)

        eligible_fns = [ match.string for match in sorted(matches, cmp=match_cmp) ]

        if candidate_computation_complete: # if we're dealing with a complete set of candidates, cache the results
            self.eligible_fns_cache[cache_key] = eligible_fns
        # TODO return filenames with both the absolute path and the display name (use the latter to open, the former for, well, display)
        return eligible_fns

    def _guess_root_directory(self, input_str):
        """ Given an input_str, deduce what directory we should search, either by relative path (../../whatever) or by absolute path (/). """
        # TODO return whether the path is absolute (starts with /)
        # If the path is absolute, display as absolute
        # If the path is relative, display as relative
        return os.path.abspath(".") # TODO be smarter about this

def select_filename(screen, search_thread, input_str):
    highlighted_pos = 0
    key_name = None

    while True:
        screen.clear()

        search_thread.update_input_str(input_str)
        curr_fns = search_thread.get_current_filenames()

        highlighted_fn = curr_fns.eligible[highlighted_pos] if curr_fns.eligible else None

        STATUS_BAR_Y = 0      # status bar first!
        INPUT_Y = 2           # where the input line should go
        FN_OFFSET = 3         # first Y coordinate of a filename
        max_height, max_width = screen.getmaxyx()
        max_files_to_show = min(len(curr_fns.eligible), max_height - FN_OFFSET)

        def add_line(y, x, line, attr, fill_line=False):
            s = line[-(max_width - 1):]
            if fill_line:
                s = s.ljust(max_width - 1, " ")
            screen.addstr(y, x, s, attr)

        # add status bar
        status_text = "{:d} of {:d}{} candidate filenames{}".format(
                len(curr_fns.eligible),
                len(curr_fns.candidates),
                "*" if not curr_fns.candidate_computation_complete else "",
                " (git: {})".format(curr_fns.git_root_dir) if curr_fns.git_root_dir is not None else "")
        add_line(STATUS_BAR_Y, 0, status_text, curses.color_pair(STATUS_BAR_COLOR_PAIR), fill_line=True)

        # input line
        add_line(INPUT_Y, 0, input_str, curses.A_UNDERLINE, fill_line=True)

        for pos, fn in enumerate(curr_fns.eligible[:max_files_to_show]):
            attr = curses.color_pair(HIGHLIGHT_COLOR_PAIR) if pos == highlighted_pos else curses.A_NORMAL
            add_line(FN_OFFSET + pos, 0, fn, attr)

        screen.refresh()

        # put the cursor at the end of the string
        input_x = min(len(input_str), max_width - 1)

        raw_key = screen.getch(INPUT_Y, input_x)
        if raw_key == -1:
            # getch() is nonblocking, try again after 50ms
            time.sleep(.05)
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
    with open('/tmp/completeme.sh', 'wb') as f:
        new_token = fn + " " # add a space at the end for the next argument
        print >> f, "READLINE_LINE='{}'".format(os.environ.get("READLINE_LINE", "") + new_token),
        print >> f, "READLINE_POINT='{}'".format(int(os.environ.get("READLINE_POINT", 0)) + len(new_token))

def open_file(fn):
    editor_cmd = os.getenv("EDITOR")
    if editor_cmd is None:
        raise Exception("Environment variable $EDITOR is missing!")

    subprocess.call(shlex.split(editor_cmd) + [fn])

def get_initial_input_str():
    """ Returns the string that should seed our search.

    TODO parse the existing commandline (READLINE_LINE, READLINE_POINT).
    If we're in the middle of typing something, seed with that argument.
    """
    return ""

def main():
    initial_input_str = get_initial_input_str()
    search_thread = FilenameSearchThread(initial_input_str)
    search_thread.start()
    try:
        screen = init_screen()
        select_filename(screen, search_thread, initial_input_str)
    finally:
        cleanup_curses()

if __name__ == "__main__":
    log_level = logging.DEBUG if os.environ.get("DEBUG") else logging.ERROR
    logging.basicConfig(level=log_level,
                        format="%(asctime)s: %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")
    _logger = logging.getLogger(__name__)
    main()
