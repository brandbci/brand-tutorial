install_script_dir=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

# install the get_display script
exec_cmd="Exec=bash -c \"$install_script_dir/get_display.sh"
exec_cmd="$exec_cmd\""
if ! test -s $HOME/.config/autostart; then mkdir -p $HOME/.config/autostart; fi
cp get_display.desktop $HOME/.config/autostart
if ! grep -Fxq "$exec_cmd" $HOME/.config/autostart/get_display.desktop ; then
    echo $exec_cmd >> $HOME/.config/autostart/get_display.desktop
fi