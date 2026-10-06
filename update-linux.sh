#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
[[ "$(uname -s)" == "Linux" ]] || { echo "Linux only" >&2; exit 1; }
[[ "$EUID" -ne 0 ]] || { echo "Run as your normal user, not sudo." >&2; exit 1; }
[[ -x .venv/bin/python ]] || { echo "Missing project venv." >&2; exit 1; }
if [[ -n "$(git status --porcelain)" ]]; then
    echo "Local source changes found. Commit or stash them before updating; data/ is preserved." >&2
    exit 1
fi
git pull --ff-only
sudo systemctl stop valbot.service
trap 'echo "Update failed; service is stopped. Read the error before restarting." >&2' ERR
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -c 'from valbot.app import app; from valbot import daemon, systemd'
bash "$ROOT/deploy-linux.sh"
trap - ERR
echo "Update installed. Check journalctl for the new Tunnel URL and LINE verification."
