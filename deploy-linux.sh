#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
[[ "$(uname -s)" == "Linux" ]] || { echo "Linux only" >&2; exit 1; }
[[ "$EUID" -ne 0 ]] || { echo "Run as your normal user; the script will call sudo for systemd." >&2; exit 1; }
[[ -x .venv/bin/python ]] || { echo "Create the venv and finish setup.py first." >&2; exit 1; }
.venv/bin/python -c 'from valbot.storage import load_config; load_config()'
[[ -x data/cloudflared ]] || { echo "Download cloudflared to data/cloudflared and chmod +x first." >&2; exit 1; }
if ! systemctl is-active --quiet valbot.service && curl -fsS --max-time 3 http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo "First press Ctrl+C in your manually started Bot and Tunnel terminals, then rerun this script." >&2
    exit 1
fi
SERVICE_FILE="$(mktemp)"
trap 'rm -f -- "$SERVICE_FILE"' EXIT
.venv/bin/python -m valbot.systemd "$(id -un)" "$SERVICE_FILE"
sudo install -m 644 "$SERVICE_FILE" /etc/systemd/system/valbot.service
sudo systemctl daemon-reload
sudo systemctl enable valbot.service
# A newly installed unit may not have a failed state yet. Only clear an
# actual failure; reset-failed on an unloaded unit aborts first-time setup.
if systemctl is-failed --quiet valbot.service 2>/dev/null; then
    sudo systemctl reset-failed valbot.service
fi
sudo systemctl restart valbot.service
echo "Service installed. Follow startup and webhook verification:"
echo "sudo journalctl -u valbot.service -n 50 -f"
echo "Once 'Bot service is ready' appears, you can close the terminal."
