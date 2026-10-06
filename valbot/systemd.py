"""Generate a system-wide service running as the configured non-root Linux user."""
import os
from pathlib import Path
import re
import sys

from .storage import ROOT, data_dir


def quote(value):
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def unit(root, python, directory, user):
    if not re.fullmatch(r"[a-z_][a-z0-9_-]*\$?", user):
        raise ValueError("不支援的 Linux 使用者名稱。")
    return f"""[Unit]
Description=Valorant LINE Bot and Quick Tunnel
Wants=network-online.target
After=network-online.target
StartLimitIntervalSec=600
StartLimitBurst=5

[Service]
Type=exec
User={user}
WorkingDirectory={quote(root)}
Environment={quote('VALBOT_DATA_DIR=' + str(directory))}
Environment=PYTHONUNBUFFERED=1
ExecStart={quote(python)} -m valbot.daemon
Restart=on-failure
RestartSec=15
TimeoutStopSec=30
KillMode=control-group
UMask=0077

[Install]
WantedBy=multi-user.target
"""


if __name__ == "__main__":
    if os.name != "posix" or len(sys.argv) != 3:
        raise SystemExit("Usage: python -m valbot.systemd USER OUTPUT")
    Path(sys.argv[2]).write_text(unit(ROOT, Path(sys.executable).absolute(), data_dir(), sys.argv[1]),
                               encoding="utf-8")
