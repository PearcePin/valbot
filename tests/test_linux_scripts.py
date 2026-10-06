"""Exercise installation commands with fake systemd/sudo; never touch real services."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from valbot.storage import ROOT


def bash_path():
    if os.name == "nt":
        git = shutil.which("git")
        if git:
            candidate = Path(git).parent.parent / "bin" / "bash.exe"
            if candidate.is_file():
                return str(candidate)
        return None
    return shutil.which("bash")


def run_script(tmp_path, filename, state):
    bash = bash_path()
    if not bash:
        pytest.skip("bash is not available")
    project = tmp_path / "project"
    fake_bin = tmp_path / "bin"
    project.mkdir()
    fake_bin.mkdir()
    for name in ("deploy-linux.sh", "update-linux.sh"):
        # Disable root detection only in isolated test copies; every privileged command is fake.
        contents = (ROOT / name).read_text(encoding="utf-8").replace('[[ "$EUID" -ne 0 ]]', 'true')
        (project / name).write_text(contents, encoding="utf-8")
    (project / "data").mkdir()
    (project / ".venv" / "bin").mkdir(parents=True)
    log = tmp_path / "calls.log"

    def executable(path, content):
        path.write_text("#!/usr/bin/env bash\n" + content, encoding="utf-8")
        path.chmod(0o755)

    executable(project / ".venv" / "bin" / "python", "exit 0\n")
    executable(project / "data" / "cloudflared", "exit 0\n")
    executable(fake_bin / "uname", "echo Linux\n")
    executable(fake_bin / "id", "echo pearce\n")
    executable(fake_bin / "curl", "exit 22\n")
    executable(fake_bin / "git", "exit 0\n")
    executable(fake_bin / "systemctl", '''
echo "systemctl $*" >> "$LOG_FILE"
case "$1" in
    is-active) exit 3 ;;
    is-failed) [[ "$UNIT_STATE" == failed ]] ;;
    show) if [[ "$UNIT_STATE" == absent ]]; then echo not-found; else echo loaded; fi ;;
    *) exit 0 ;;
esac
''')
    executable(fake_bin / "sudo", '''
echo "sudo $*" >> "$LOG_FILE"
if [[ "$1" == systemctl && "$2" == reset-failed && "$UNIT_STATE" == absent ]]; then
    echo "Unit valbot.service not loaded" >&2
    exit 1
fi
exit 0
''')
    environment = {**os.environ, "FAKE_BIN": fake_bin.as_posix(), "LOG_FILE": log.as_posix(),
                   "UNIT_STATE": state, "TEST_SCRIPT": (project / filename).as_posix()}
    command = 'export PATH="$(cd "$FAKE_BIN" && pwd):$PATH"; bash "$TEST_SCRIPT"'
    result = subprocess.run([bash, "-c", command], env=environment, capture_output=True, text=True, timeout=20)
    return result, log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def test_initial_deployment_does_not_reset_unloaded_service(tmp_path):
    result, calls = run_script(tmp_path, "deploy-linux.sh", "absent")
    assert result.returncode == 0, result.stderr
    assert "sudo systemctl reset-failed valbot.service" not in calls
    assert calls.index("sudo systemctl enable valbot.service") < calls.index("sudo systemctl restart valbot.service")


def test_deployment_clears_existing_failure_before_restart(tmp_path):
    result, calls = run_script(tmp_path, "deploy-linux.sh", "failed")
    assert result.returncode == 0, result.stderr
    assert calls.index("sudo systemctl reset-failed valbot.service") < calls.index("sudo systemctl restart valbot.service")


def test_update_recovers_an_installation_with_no_loaded_service(tmp_path):
    result, calls = run_script(tmp_path, "update-linux.sh", "absent")
    assert result.returncode == 0, result.stderr
    assert "sudo systemctl stop valbot.service" not in calls
    assert "sudo systemctl restart valbot.service" in calls
