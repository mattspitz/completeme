#!/bin/bash

# Checks to see if a build should execute.  Returns 0 if so, 1 otherwise.

if [ "$SKIP_CHECK" != "" ]
then
    exit 0
fi

LOCAL_CHANGES=`git diff-index --name-only HEAD`
if [[ $LOCAL_CHANGES != "" ]]
then
    echo "You have local changes!  Commit or revert them before building."
    echo $LOCAL_CHANGES
    exit 1
fi

UNCOMMITTED_FILES=`git ls-files --exclude-standard --others`
if [[ $UNCOMMITTED_FILES != "" ]]
then
    echo "You have uncommitted files!  Remove or commit them before building."
    echo $UNCOMMITTED_FILES
    exit 1
fi

exit 0
