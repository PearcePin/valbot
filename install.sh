#!/usr/bin/env bash
set -euo pipefail
REPO_URL="${VALBOT_REPO_URL:-https://github.com/PearcePin/valbot.git}"
TARGET="${VALBOT_INSTALL_DIR:-$HOME/valbot}"
LOCAL=0
DEPLOY=1
SETUP=1
for arg in "$@"; do
    case "$arg" in
        --local) LOCAL=1 ;;
        --no-deploy) DEPLOY=0 ;;
        --no-setup) SETUP=0 ;;
        *) echo "Usage: install.sh [--local] [--no-deploy] [--no-setup]" >&2; exit 1 ;;
    esac
done
[[ "$(uname -s)" == Linux ]] || { echo "Ubuntu/Linux installer only." >&2; exit 1; }
[[ "$EUID" -ne 0 ]] || { echo "Run as your normal user, not sudo. Administrator steps will ask for sudo." >&2; exit 1; }
trap 'echo "Installation incomplete. Keep data/; fix the error above, then rerun install.sh --local. See docs/install.md." >&2' ERR
if ! command -v git >/dev/null || ! command -v curl >/dev/null || ! command -v crontab >/dev/null; then
    command -v apt-get >/dev/null || { echo "Install git, curl and cron first." >&2; exit 1; }
    echo "[1/5] Installing Ubuntu prerequisites (sudo password is hidden)..."
    sudo apt-get update </dev/tty
    sudo apt-get install -y git curl ca-certificates cron </dev/tty
fi
if [[ "$LOCAL" == 1 ]]; then
    TARGET="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
elif [[ -e "$TARGET" ]]; then
    [[ -d "$TARGET/.git" && -f "$TARGET/setup.py" ]] || { echo "Destination is not a valbot checkout: $TARGET" >&2; exit 1; }
    [[ -z "$(git -C "$TARGET" status --porcelain)" ]] || { echo "Local source changes found; commit/stash them first. Do not delete data/." >&2; exit 1; }
    echo "Updating existing checkout; settings are preserved."
    git -C "$TARGET" pull --ff-only
else
    echo "[1/5] Downloading project..."
    git clone -- "$REPO_URL" "$TARGET"
fi
cd "$TARGET"
TARGET="$(pwd -P)"
[[ -f setup.py && -f requirements.txt ]] || { echo "Invalid project directory." >&2; exit 1; }
echo "[2/5] Preparing compatible Python (system Python 3.14 is left intact)..."
if [[ -x .venv/bin/python ]] && .venv/bin/python -c 'import sys; assert (3,11) <= sys.version_info < (3,14)' 2>/dev/null; then
    echo "Using existing compatible venv."
else
    if [[ -e .venv ]]; then
        if command -v systemctl >/dev/null && systemctl is-active --quiet valbot.service; then
            sudo systemctl stop valbot.service </dev/tty
        fi
        BACKUP=".venv.backup-$(date +%Y%m%d-%H%M%S)-$$"
        mv -- "$TARGET/.venv" "$TARGET/$BACKUP"
        echo "Previous venv backed up as $BACKUP; data/ was retained."
    fi
    if [[ -n "${VALBOT_PYTHON:-}" ]]; then
        "$VALBOT_PYTHON" -c 'import sys; assert (3,11) <= sys.version_info < (3,14), "Python 3.11-3.13 required"'
        "$VALBOT_PYTHON" -m venv .venv
    else
        UV="$(command -v uv || true)"
        [[ -n "$UV" ]] || UV="$HOME/.local/bin/uv"
        if [[ ! -x "$UV" ]]; then
            UV_INSTALLER="$(mktemp)"
            curl -fL --retry 3 https://astral.sh/uv/install.sh -o "$UV_INSTALLER"
            UV_INSTALL_DIR="$HOME/.local/bin" UV_NO_MODIFY_PATH=1 sh "$UV_INSTALLER"
            rm -f -- "$UV_INSTALLER"
            UV="$HOME/.local/bin/uv"
        fi
        "$UV" venv --python 3.12 --seed .venv
    fi
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -c 'from valbot.app import app'
echo "[3/5] Riot / LINE configuration..."
if [[ "$SETUP" == 1 ]]; then
    ( : </dev/tty ) 2>/dev/null || { echo "Open a terminal and run: cd \"$TARGET\"; bash install.sh --local" >&2; exit 1; }
    RECONFIGURE=1
    if .venv/bin/python -c 'from valbot.storage import load_config; load_config()' >/dev/null 2>&1; then
        read -r -p "Keep existing Riot/LINE settings? [Y/n]: " KEEP </dev/tty
        [[ "${KEEP,,}" == n ]] || RECONFIGURE=0
    fi
    if [[ "$RECONFIGURE" == 1 ]]; then
        .venv/bin/python setup.py --login-method browser </dev/tty
    else
        .venv/bin/python setup.py --schedule-only </dev/tty
    fi
fi
echo "[4/5] Preparing Cloudflare Tunnel..."
if [[ ! -x data/cloudflared ]]; then
    case "$(uname -m)" in
        x86_64) ARCH=amd64 ;;
        aarch64|arm64) ARCH=arm64 ;;
        *) echo "Unsupported CPU. Download cloudflared manually." >&2; exit 1 ;;
    esac
    # Vault creates data/ with private permissions during configuration.
    .venv/bin/python -c 'from valbot.storage import Vault; Vault()'
    TUNNEL_TEMP="$(mktemp "$TARGET/data/.cloudflared.XXXXXX")"
    curl -fL --retry 3 "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-$ARCH" -o "$TUNNEL_TEMP"
    chmod 700 "$TUNNEL_TEMP"
    "$TUNNEL_TEMP" --version
    mv -- "$TUNNEL_TEMP" "$TARGET/data/cloudflared"
fi
if [[ "$DEPLOY" == 1 ]]; then
    echo "[5/5] Installing background service and automatic webhook setup..."
    [[ -d /run/systemd/system ]] || { echo "systemd is not running. Use --no-deploy for containers/WSL; see docs/install.md." >&2; exit 1; }
    sudo systemctl enable --now cron </dev/tty
    bash "$TARGET/deploy-linux.sh" </dev/tty
else
    echo "[5/5] Service deployment skipped. Run bash deploy-linux.sh when configuration is complete."
fi
echo "Installed at $TARGET. Detailed instructions: $TARGET/docs/install.md"
echo "Enable Use webhook and disable LINE's default auto-reply in LINE Developers."
echo "Updates: cd \"$TARGET\" && bash update-linux.sh"
