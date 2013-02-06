# completeme

## Description
This is a python script that'll allow you to auto-complete filenames and launch them in an editor, much like GitHub's 't' keyboard shortcut.  Rather than tab-completing to oblivion (ever worked on a Java project?), just start typing the name of the file, and when you hit enter, it'll open that file in your favorite $EDITOR.  Uses files stored in the current GitHub repository and falls back on all files below the current working directory.

If you add the line in bashrc\_inc to your bashrc, it'll bind Ctrl+t to this script.

## License
This software is licensed under the WtHYWv2 (Whatever the Hell You Want, v2).  Please throw some credit around if it's deserved.

## Known issues
* Still needs an install setup.py (and deploy to PyPI) so we can use a global command in bashrc\_inc.  The current one only works if you're in the same directory as completeme.py.  Boring.
* Currently, the git search (ls-tree) lists only the files under source control at or beneath this directory.  Do we want to support querying all files in the git repository, regardless of which subdirectory you're in?  If so, we'll want to use the --full-tree option.
* Come up with some way to sort the results to prioritize the better matches, perhaps by word boundary.

## Wishlist
* I wish I didn't have to run the $EDITOR command in the script.  Wouldn't it be neat if Ctrl+t could just output the filename into my current prompt?  Then, you can autocomplete for anything, not just your text editor.
* It'd also be neat to specify a different directory that you'd like to autocomplete, not just the current working directory, though perhaps that's beyond the scope of this project.
* I'd love to configure curses to use whatever your terminal background is (not the weird gray color that mine seems to want to use in Debian).
