bind -x '"\C-t": TMPFILE=`mktemp 2> /dev/null || mktemp -t completeme 2> /dev/null` && env completeme $TMPFILE && test -e $TMPFILE && source $TMPFILE; rm -f $TMPFILE'
