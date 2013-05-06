bind -x '"\C-t": TMPFILE=`mktemp` && env completeme $TMPFILE && test -e /tmp/completeme.sh && source $TMPFILE; rm -f $TMPFILE'
