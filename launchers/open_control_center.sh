#!/usr/bin/env sh
set -eu

launcher_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if ! command -v python3 >/dev/null 2>&1; then
    zenity --error --title='BudBot Control Center' --text='Python 3 is missing. Install Python 3 and try again.'
    exit 1
fi
if ! python3 -c 'import tkinter' >/dev/null 2>&1; then
    zenity --error --title='BudBot Control Center' --text='Tkinter is missing. On Linux Mint, install the python3-tk package, then try again.'
    exit 1
fi
exec python3 "$launcher_dir/control_center.py"
