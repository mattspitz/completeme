#!/usr/bin/env python2.7

import curses
import os
import re
import subprocess

""" Some of this is generously lifted from http://blog.skeltonnetworks.com/2010/03/python-curses-custom-menu/ """

HIGHLIGHT_COLOR_PAIR = 1
NEWLINE = "^J"
def init_screen():
    screen = curses.initscr()
    curses.start_color()
    curses.init_pair(HIGHLIGHT_COLOR_PAIR, curses.COLOR_RED, curses.COLOR_WHITE)
    screen.keypad(1)
    return screen

def cleanup_curses():
    curses.nocbreak()
    curses.echo()
    curses.endwin()

def run_cmd(cmd, shell=False, check_returncode=False):
    """ Run the command specified.  Returns (stdout, stderr).  Optionally checks returncode. """
    popen = subprocess.Popen(cmd, shell=shell, universal_newlines=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = popen.communicate()
    if check_returncode and popen.returncode != 0:
        raise Exception("{} returned return code {:d}.  Stderr:\n{}".format(cmd, popen.returncode, stderr))

    return stdout, stderr

def get_filenames():
    # first try to list all files under (git) source control
    git_fns, _ = run_cmd("git ls-tree -r HEAD | cut -f2", shell=True, check_returncode=True)
    if git_fns:
        # also pull in untracked (but not .gitignore'd) files
        untracked_fns, _ = run_cmd("git ls-files --exclude-standard --others | cut -f2", shell=True, check_returncode=True)
        return git_fns.strip().split("\n") + untracked_fns.strip().split("\n")

    # fall back on all filenames below this directory
    all_fns, _ = run_cmd("find -L . -type f", shell=True)

    # strip off the leading ./ to match git output
    return map(lambda fn: fn[len("./"):] if fn.startswith("./") else fn,
               all_fns.strip().split("\n"))

ELIGIBLE_FILENAMES_CACHE = {}
def compute_eligible_filenames(input_str, all_filenames):
    """ Return a sorted ordering of the filenames based on this input string.

    All filenames that match the input_string are included, and we prefer those
    that match on word boundaries. """

    lowered = input_str.lower()
    if lowered not in ELIGIBLE_FILENAMES_CACHE:
        # if this query is at least two characters long and the prefix minus this last letter has already been computed, start with those eligible filenames
        # no need to prune down the whole list if we've already limited the search space
        initial_filenames = ELIGIBLE_FILENAMES_CACHE.get(lowered[:-1], all_filenames) if len(lowered) >= 2 else all_filenames

        # fuzzy matching: for input string abc, find a*b*c substrings (consuming as few characters as possible in between)
        regex = re.compile("(.*?)".join(lowered), re.IGNORECASE | re.DOTALL)

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

        ELIGIBLE_FILENAMES_CACHE[lowered] = [ match.string for match in sorted(matches, cmp=match_cmp) ]

    return ELIGIBLE_FILENAMES_CACHE[lowered]

def display_filenames(screen, all_filenames):
    input_str = ""
    eligible_filenames = compute_eligible_filenames(input_str, all_filenames)

    highlighted_pos = 0
    key_name = None

    while key_name != NEWLINE:
        screen.clear()

        eligible_filenames = compute_eligible_filenames(input_str, all_filenames)
        highlighted_fn = eligible_filenames[highlighted_pos] if eligible_filenames else None

        INPUT_Y = 1   # where the input line should go
        FN_OFFSET = 2 # first Y coordinate of a filename
        max_height, max_width = screen.getmaxyx()
        max_files_to_show = min(len(eligible_filenames), max_height - FN_OFFSET)

        # stretch input_str to the max_width for the underline
        formatted_input_str = input_str[-(max_width - 1):].ljust(max_width, " ")

        # input line
        screen.addstr(INPUT_Y, 0, formatted_input_str, curses.A_UNDERLINE)

        for pos, fn in enumerate(eligible_filenames[:max_files_to_show]):
            attr = curses.color_pair(HIGHLIGHT_COLOR_PAIR) if pos == highlighted_pos else curses.A_NORMAL
            screen.addstr(FN_OFFSET + pos, 0, fn, attr)

        screen.refresh()

        # put the cursor at the end of the string
        input_x = min(len(input_str), max_width - 1)
        try:
            key_name = curses.keyname(screen.getch(INPUT_Y, input_x))
        except KeyboardInterrupt:
            # swallow ctrl+c
            return None

        if key_name == NEWLINE:
            continue
        if key_name == "KEY_DOWN":
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

    return highlighted_fn

def open_file(fn):
    editor_cmd = os.getenv("EDITOR")
    if editor_cmd is None:
        raise Exception("Environment variable $EDITOR is missing!")

    subprocess.call([ editor_cmd, fn ])

def main():
    filenames = get_filenames()
    selected_fn = None
    try:
        screen = init_screen()
        selected_fn = display_filenames(screen, filenames)
    finally:
        cleanup_curses()

    if selected_fn:
        open_file(selected_fn)

if __name__ == "__main__":
    main()
