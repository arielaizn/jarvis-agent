#!/bin/zsh
set -eu
cd "$(dirname "$0")"
if ! command -v uv >/dev/null 2>&1; then
  print "נדרשת התקנת uv: https://docs.astral.sh/uv/getting-started/installation/"
  exit 1
fi
uv venv --python 3.12 --allow-existing .venv
uv pip install --python .venv/bin/python -r requirements.txt
uv venv --python 3.12 --allow-existing .venv-browser
uv pip install --python .venv-browser/bin/python -r requirements-browser.txt
print "ההתקנה הסתיימה. להפעלה: start.command"
