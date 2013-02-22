##########
completeme
##########

completeme is a python script that'll allow you to auto-complete filenames and launch them in an editor, much like GitHub's 't' keyboard shortcut.  Rather than tab-completing to oblivion (ever worked on a Java project?), just start typing the name of the file, and when you hit enter, it'll open that file in your favorite $EDITOR.  Uses files stored in the current GitHub repository and falls back on all files below the current working directory.

**Make sure to add `source /usr/local/bin/setup_completeme_key_binding.sh` to your .bashrc to enable Ctrl+t support!**

#############
Configuration
#############

completeme comes with /etc/completeme.json, which you can use to, well, configure your completeme experience.

* *git_entire_tree* (default=true) indicates whether, if we're in a git repository, we should search all files in the git repository, regardless of where we are in said repository.  That is, if we have a repository like /hello.txt, /a/there.txt, /b/myfriends.txt, and we're in the /a directory, *git_entire_tree=true* implies that we'll also surface /hello.txt and /b/myfriends.txt.  Otherwise, you'll just get /a/there.txt.
* *find_hidden_directories* (default=false) indicates whether we should search inside dot directories (assuming we didn't find a git repository).  These are things like .config/, .vim/, etc.
* *find_hidden_files* (default=false) indicates whether we should find files that start with a dot (assuming we didn't find a git repository).  These are things like .emacs, .xinitrc, .DS_Store, etc.

#######
License
#######
This software is licensed under the WtHYWv2 (Whatever the Hell You Want, v2).  Please throw some credit around if it's deserved.
