bind -x '"\C-t": TMPFILE=`mktemp` && env completeme $TMPFILE && test -e $TMPFILE && source $TMPFILE; rm -f $TMPFILE'
