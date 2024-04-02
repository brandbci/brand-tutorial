# This script retrieves the DISPLAY
# environment variable if a user logs
# into a GUI session and writes it to
# ~/.DISPLAY

if [ x$DISPLAY != x ] ; then
    # from https://askubuntu.com/questions/21923/how-do-i-create-the-xauthority-file
    /bin/bash -c 'ln -s -f "$XAUTHORITY" $HOME/.Xauthority'
    echo $DISPLAY > $HOME/.DISPLAY
fi
