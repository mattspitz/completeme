##########
completeme
##########

completeme is a python script that'll allow you to auto-complete filenames and launch them in an editor, much like GitHub's 't' keyboard shortcut.  Rather than tab-completing to oblivion (ever worked on a Java project?), just start typing the name of the file, and when you hit 'enter', it'll open that file in your favorite $EDITOR.  If you hit 'tab', the filename will be entered back into the command line.

Uses files stored in the current GitHub repository and falls back on all files below the current working directory.

**Make sure to add `source /usr/local/bin/setup_completeme_key_binding.sh` to your .bashrc to enable Ctrl+t support!**

#############
Configuration
#############

completeme comes with (wherever-pip-installs-the-completeme-python-package)/completeme.json, which you can use to, well, configure your completeme experience.

* *include_directories* (defualt=true) indicates whether we should also display directories (not just files).
* *find_hidden_directories* (default=false) indicates whether we should search inside dot directories (assuming we didn't find a git repository).  These are things like .config/, .vim/, etc.
* *find_hidden_files* (default=false) indicates whether we should find files that start with a dot (assuming we didn't find a git repository).  These are things like .emacs, .xinitrc, .DS_Store, etc.

############
Known Issues
############

* Mac OS X ships with bash 3.2, which doesn't use the READLINE_LINE or READLINE_POINT variables.  Unless you upgrade, you won't be able to use the tab-functionality to drop the filename back into the prompt!  Fortunately, `brew install bash` will give you a compatible version!

#######
License
#######
This software is licensed under the WtHYWv2 (Whatever the Hell You Want, v2).  Please throw some credit around if it's deserved.

######
Thanks
######

Thank you to all who have contributed ideas and feedback.  Special thanks to those listed below!

* Mark Steve Samson (`@marksteve <https://github.com/marksteve>`_)
* Harold Cooper (`@hrldcpr <https://github.com/hrldcpr>`_)
