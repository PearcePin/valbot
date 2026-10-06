#!/usr/bin/env bash
set -euo pipefail
REPO_URL="${VALBOT_REPO_URL:-https://github.com/PearcePin/valbot.git}"
TARGET="${VALBOT_INSTALL_DIR:-$HOME/valbot}"
PYTHON="${VALBOT_PYTHON:-python3}"
for tool in git "$PYTHON"; do
    command -v "$tool" >/dev/null || { echo "Missing $tool. Ubuntu: sudo apt install git python3 python3-venv cron" >&2; exit 1; }
done
"$PYTHON" -c 'import sys; assert (3, 11) <= sys.version_info < (3, 14), "Use Python 3.11-3.13 (recommended: 3.12). LINE SDK uses Pydantic V1, incompatible with Python 3.14. Set VALBOT_PYTHON to a compatible Python executable."'
if [[ "${1:-}" == "--local" ]]; then
    TARGET="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
    [[ -f "$TARGET/setup.py" && -f "$TARGET/requirements.txt" ]] || { echo "Invalid local project" >&2; exit 1; }
elif [[ -e "$TARGET" ]]; then
    echo "Destination already exists: $TARGET. Choose VALBOT_INSTALL_DIR or run its setup.py." >&2
    exit 1
else
    git clone -- "$REPO_URL" "$TARGET"
fi
cd "$TARGET"
if [[ -x .venv/bin/python ]] && ! .venv/bin/python -c 'import sys; assert (3, 11) <= sys.version_info < (3, 14)' 2>/dev/null; then
    echo "Existing .venv uses an incompatible Python. Rename .venv to a backup, then rerun. Keep data/ intact." >&2
    exit 1
fi
"$PYTHON" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
# Reading /dev/tty keeps prompts usable even when this script is piped into bash.
if [[ -r /dev/tty ]]; then
    .venv/bin/python setup.py </dev/tty
else
    echo "Installed. Run: cd \"$TARGET\" && .venv/bin/python setup.py"
fi
