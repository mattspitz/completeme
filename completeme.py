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

def get_filenames():
    # first try to list all files under (git) source control
    git_fns = subprocess.check_output("git ls-tree -r HEAD | cut -f2", shell=True, universal_newlines=True)
    if git_fns:
        return git_fns.strip().split("\n")

    # fall back on all filenames below this directory
    all_fns = subprocess.check_output("find -L -type f", shell=True, universal_newlines=True)

    # strip off the leading ./ to match git output
    return map(lambda fn: fn[len("./"):] if fn.startswith("./") else fn,
               all_fns.strip().split("\n"))

def compute_eligible_filenames(input_str, all_filenames):
    """ Return a sorted ordering of the filenames based on this input string.

    All filenames that match the input_string are included, and we prefer those
    that match on word boundaries. """
    regex = re.compile(input_str, re.IGNORECASE)

    eligible_filenames = filter(lambda x: regex.search(x),
                                all_filenames)
    # TODO sort by those that match on a word boudary
    return eligible_filenames

def display_filenames(screen, all_filenames):
    input_str = ""
    eligible_filenames = compute_eligible_filenames(input_str, all_filenames)

    highlighted_pos = 0
    key_name = None

    while key_name != NEWLINE:
        highlighted_fn = eligible_filenames[highlighted_pos] if eligible_filenames else None

        screen.clear()

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
        key_name = curses.keyname(screen.getch(INPUT_Y, input_x))

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
            if key_name == "KEY_BACKSPACE":   # delete single character
                input_str = input_str[:-1]
            elif key_name == "^W":            # delete whole line
                input_str = ""
            elif key_name.startswith("KEY_"): # just ignore it
                continue
            else:                             # add character (doesn't special key checking)
                input_str += key_name

            # at this point, input_str has changed

            # ...recalculate eligible filenames
            eligible_filenames = compute_eligible_filenames(input_str, all_filenames)

            # ...and reset highlighted_pos
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
