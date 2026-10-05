#!/usr/bin/env bash
set -euo pipefail
REPO_URL="${VALBOT_REPO_URL:-https://github.com/PearcePin/valbot.git}"
TARGET="${VALBOT_INSTALL_DIR:-$HOME/valbot}"
for tool in git python3; do
    command -v "$tool" >/dev/null || { echo "Missing $tool. Ubuntu: sudo apt install git python3 python3-venv cron" >&2; exit 1; }
done
python3 -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"'
if [[ -e "$TARGET" ]]; then
    echo "Destination already exists: $TARGET. Choose VALBOT_INSTALL_DIR or run its setup.py." >&2
    exit 1
fi
git clone -- "$REPO_URL" "$TARGET"
cd "$TARGET"
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
# Reading /dev/tty keeps prompts usable even when this script is piped into bash.
if [[ -r /dev/tty ]]; then
    .venv/bin/python setup.py </dev/tty
else
    echo "Installed. Run: cd \"$TARGET\" && .venv/bin/python setup.py"
fi
