##########
completeme
##########

#####
TL;DR
#####

**Linux**:

- $ sudo pip install completeme
- $ echo "source \`which setup_completeme_key_binding.sh\`" >> ~/.bashrc
- $ source ~/.bashrc

**OS X**:

- $ brew install bash # see note below about OS X and bash 4
- $ sudo pip install completeme # no need for 'sudo' if you installed python with brew, as well!
- $ echo "source \`which setup_completeme_key_binding.sh\`" >> ~/.profile
- $ source ~/.profile

**Windows**:

- http://bit.ly/1bdcxmt

###########
Description
###########

completeme is a python script to auto-complete filenames in a given directory, much like Github's 't' keyboard shortcut or Command-T in TextMate or SublimeText.  When you've settled on the file you'd like to edit, press "Enter" to open it with whatever's in your $EDITOR variable or press "Tab" to drop that filename at the end of your current command!

To change your search directory, simply prefix your query.  That is, start your string with "../" to search your current working directory's parent or "/tmp/" to search "/tmp/".  Note that the trailing slash is what triggers the directory change. If your current search directory is a git repository, this will respect your .gitignore.

**Make sure to add "source `which setup_completeme_key_binding.sh`" to your .bashrc to enable Ctrl+t support!**

#############
Configuration
#############

completeme comes with (wherever-pip-installs-the-completeme-python-package)/completeme.json, which you can use to, well, configure your completeme experience.

* *include_directories* (default=true) indicates whether we should also display directories (not just files).
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
* Andrew Gwozdziewycz (`@apgwoz <https://github.com/apgwoz>`_)
