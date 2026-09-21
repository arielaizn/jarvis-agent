#!/bin/zsh
set -eu
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  print "חסרה סביבת Python. הפעל תחילה את install.command"
  exit 1
fi
exec .venv/bin/python main.py
