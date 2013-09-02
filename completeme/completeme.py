import curses
import logging
import os
import time

from contextlib import contextmanager

from .collection import FilenameCollectionThread
from .search import SearchThread

_logger = logging.getLogger(__name__)

HIGHLIGHT_COLOR_PAIR = 1
STATUS_BAR_COLOR_PAIR = 2
NEWLINE = "^J"
TAB = "^I"
def init_screen():
    screen = curses.initscr()
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(HIGHLIGHT_COLOR_PAIR, curses.COLOR_RED, curses.COLOR_WHITE)
    curses.init_pair(STATUS_BAR_COLOR_PAIR, curses.COLOR_GREEN, -1)
    screen.keypad(1)
    screen.nodelay(1) # nonblocking input
    return screen

def cleanup_curses():
    curses.nocbreak()
    curses.echo()
    curses.endwin()

class SearchStatus(object):
    SEARCH_STATUS_CHARS = ("|", "\\", "-", "/")

    def __init__(self):
        super(SearchStatus, self).__init__()
        self.curr_idx = None
        self.reset_status()

    def reset_status(self):
        self.curr_idx = 0

    def get_next_status_char(self):
        self.curr_idx = (self.curr_idx + 1) % len(self.SEARCH_STATUS_CHARS)
        return self.SEARCH_STATUS_CHARS[self.curr_idx]

def _common_suffix(path_one, path_two):
    def rstr(s):
        return "".join(reversed(s))

    rpath_one, rpath_two = rstr(path_one), rstr(path_two)
    rprefix = os.path.commonprefix((rpath_one, rpath_two))
    return rstr(rprefix)

@contextmanager
def umask(newmask):
    oldmask = os.umask(newmask)
    yield
    os.umask(oldmask)

def select_filename(screen, fn_collection_thread, search_thread, input_str, output_script):
    highlighted_pos = 0
    key_name = None

    search_status = SearchStatus()

    def get_display_uuid(input_str, curr_fns, eligible_fns):
        """ Returns a unique id to represent what we're currently displaying on the screen.  Useful for us to block if we're not showing anything new. """
        return hash("".join(map(str,[
            input_str,
            curr_fns.candidate_computation_complete, curr_fns.current_search_dir, len(curr_fns.candidates),
            eligible_fns.search_complete, len(eligible_fns.eligible) ])))

    def ensure_threads_alive(*threads):
        for th in threads:
            if not th.is_alive():
                raise Exception("{} died with traceback:\n{}".format(th, th.get_traceback()))

    prev_display_uuid = None
    while True:
        ensure_threads_alive(fn_collection_thread, search_thread)

        screen.clear()

        fn_collection_thread.update_input_str(input_str)
        curr_fns = fn_collection_thread.get_current_filenames()

        search_thread.update_input(input_str, curr_fns)
        eligible_fns = search_thread.get_eligible_filenames()

        if not eligible_fns.search_complete:
            highlighted_pos = 0

        STATUS_BAR_Y = 0      # status bar first!
        INPUT_Y = 2           # where the input line should go
        FN_OFFSET = 3         # first Y coordinate of a filename
        max_height, max_width = screen.getmaxyx()
        max_files_to_show = min(len(eligible_fns.eligible), max_height - FN_OFFSET)

        def addstr(y, x, s, attr):
            if s:
                _logger.debug("adding string '{}'".format(s))
                screen.addstr(y, x, s, attr)

        def add_line(y, x, line, attr, fill_line=False, bold_positions=None):
            s = line[-(max_width - 1):]
            if fill_line:
                s = s.ljust(max_width - 1, " ")
            try:
                if bold_positions is None:
                    addstr(y, x, s, attr)
                else:
                    cur_x = x
                    str_pos = 0
                    for bold_pos in bold_positions:
                        # draw the string up to this point
                        no_bold = s[str_pos:bold_pos]
                        addstr(y, cur_x, no_bold, attr)
                        cur_x += len(no_bold)
                        str_pos += len(no_bold)

                        # draw the bold character
                        bold = s[bold_pos]
                        addstr(y, cur_x, bold, attr | curses.A_BOLD)
                        cur_x += 1
                        str_pos += 1

                    # clean up the rest
                    addstr(y, cur_x, s[str_pos:], attr)

            except Exception:
                _logger.debug("Couldn't add string to screen: {}".format(s))

        if (not eligible_fns.search_complete or not curr_fns.candidate_computation_complete):
            search_status_prefix = "{} ".format(search_status.get_next_status_char())
        else:
            search_status_prefix = "  "
            search_status.reset_status()

        # add status bar
        status_text = "{}{:d} of {:d} candidate filenames -- {}".format(
                search_status_prefix,
                len(eligible_fns.eligible),
                len(curr_fns.candidates),
                "{}{}".format(curr_fns.current_search_dir, " (git)" if curr_fns.git_root_dir is not None else ""))
        add_line(STATUS_BAR_Y, 0, status_text, curses.color_pair(STATUS_BAR_COLOR_PAIR) | curses.A_BOLD, fill_line=True)

        # input line
        add_line(INPUT_Y, 0, input_str, curses.A_UNDERLINE, fill_line=True)

        cwd = os.getcwd()
        def get_display_fn_match_positions(eligible_fn):
            if (curr_fns.current_search_dir.startswith(cwd)
                    or (curr_fns.git_root_dir is not None and cwd.startswith(curr_fns.git_root_dir))):
                display_fn = os.path.relpath(eligible_fn.abs_fn)
                # recompute our match positions
                common_suffix = _common_suffix(display_fn, eligible_fn.abs_fn)
                abs_prefix = eligible_fn.abs_fn[:-len(common_suffix)]
                display_prefix = display_fn[:-len(common_suffix)]
                match_positions = [ pos - len(abs_prefix) + len(display_prefix) for pos in eligible_fn.abs_match_positions ]
            else:
                display_fn = eligible_fn.abs_fn
                match_positions = eligible_fn.abs_match_positions

            if not display_fn.endswith("/") and os.path.isdir(display_fn):
                display_fn += "/"

            return display_fn, match_positions

        highlighted_fn = None
        screen_pos = 0
        for eligible_fn in eligible_fns.eligible:
            if screen_pos >= max_files_to_show:
                break

            if eligible_fn.abs_fn == curr_fns.current_search_dir:
                continue

            display_fn, match_positions = get_display_fn_match_positions(eligible_fn)
            if screen_pos == highlighted_pos:
                attr = curses.color_pair(HIGHLIGHT_COLOR_PAIR)
                highlighted_fn = display_fn
            else:
                attr = curses.A_NORMAL

            add_line(FN_OFFSET + screen_pos, 0, display_fn, attr, bold_positions=match_positions)
            screen_pos += 1

        screen.refresh()

        # put the cursor at the end of the string
        input_x = min(len(input_str), max_width - 1)

        # getch is nonblocking; try in 20ms increments for up to 120ms before redrawing screen (60s if we know the screen won't change without input)
        new_display_uuid = get_display_uuid(input_str, curr_fns, eligible_fns)
        getch_time = 60 if new_display_uuid == prev_display_uuid and curr_fns.candidate_computation_complete and eligible_fns.search_complete else 0.120
        prev_display_uuid = new_display_uuid

        start_getch = time.time()
        raw_key = -1
        while (time.time() - start_getch) < getch_time:
            raw_key = screen.getch(INPUT_Y, input_x)
            if raw_key != -1: break
            time.sleep(0.020)

        if raw_key == -1:
            continue

        key_name = curses.keyname(raw_key)

        if key_name == NEWLINE:
            # open the file in $EDITOR
            open_file(highlighted_fn, output_script)
            return
        elif key_name == TAB:
            # dump the character back to the prompt
            dump_to_prompt(highlighted_fn, output_script)
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

def _shellquote(s):
    """ Cleans up a filename for the shell (from http://stackoverflow.com/a/35857) """
    return "'" + s.replace("'", "'\\''") + "'"

def dump_to_prompt(fn, output_script):
    if fn:
        with umask(0077), open(output_script, 'wb') as f:
            new_token = _shellquote(_shellquote(fn) + " ") # double shell-quote because we're setting an environment variable with the quoted string
            print >> f, "READLINE_LINE='{}'{}".format(os.environ.get("READLINE_LINE", ""), new_token),
            print >> f, "READLINE_POINT='{}'".format(int(os.environ.get("READLINE_POINT", 0)) + len(new_token))

def open_file(fn, output_script):
    if fn:
        editor_cmd = os.getenv("EDITOR")
        if editor_cmd is None:
            raise Exception("Environment variable $EDITOR is missing!")

        with umask(0077), open(output_script, "wb") as f:
            cmd = "{} {}".format(editor_cmd, _shellquote(fn))
            print >> f, cmd
            print >> f, "history -s \"{}\"".format(cmd)

def get_initial_input_str():
    """ Returns the string that should seed our search.

    TODO parse the existing commandline (READLINE_LINE, READLINE_POINT).
    If we're in the middle of typing something, seed with that argument.
    """
    return ""

def run_loop():
    import sys
    if len(sys.argv) == 2:
        output_script = sys.argv[1]
    else:
        print >> sys.stderr, "usage: completeme output-script-file"
        raise SystemExit()

    initial_input_str = get_initial_input_str()
    fn_collection_thread = FilenameCollectionThread(initial_input_str)
    fn_collection_thread.start()

    while not fn_collection_thread.state_is_consistent():
        time.sleep(0.002)

    search_thread = SearchThread(initial_input_str, fn_collection_thread.get_current_filenames())
    search_thread.start()

    try:
        screen = init_screen()
        select_filename(screen, fn_collection_thread, search_thread, initial_input_str, output_script)
    except KeyboardInterrupt:
        pass
    finally:
        fn_collection_thread.stop()
        search_thread.stop()

        cleanup_curses()

        search_thread.join()
        fn_collection_thread.join()

def main():
    logging.basicConfig(level=logging.DEBUG if os.environ.get("DEBUG") else logging.ERROR,
            format="%(asctime)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S")
    if os.environ.get("RUN_PROFILER"):
        import cProfile
        import pstats
        import tempfile
        _, profile_fn = tempfile.mkstemp()
        cProfile.run("run_loop()", profile_fn)
        pstats.Stats(profile_fn).sort_stats("cumulative").print_stats()
    else:
        run_loop()
