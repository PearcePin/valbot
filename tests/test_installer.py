"""Run Linux installer against fake downloads/Python; preserve real machine state."""
import os
import subprocess

import pytest

from valbot.storage import ROOT
from tests.test_linux_scripts import bash_path


@pytest.mark.parametrize("compatible", [False, True])
def test_linux_installer_repairs_314_preserves_config_and_downloads_tunnel(tmp_path, compatible):
    bash = bash_path()
    if not bash:
        pytest.skip("bash unavailable")
    project, fake_bin = tmp_path / "project", tmp_path / "bin"
    project.mkdir()
    fake_bin.mkdir()
    data = project / "data"
    data.mkdir()
    (data / "config.enc").write_bytes(b"existing-private-config")
    (project / "setup.py").write_text("placeholder", encoding="utf-8")
    (project / "requirements.txt").write_text("placeholder", encoding="utf-8")
    (project / "install.sh").write_text((ROOT / "install.sh").read_text(encoding="utf-8").replace(
        '[[ "$EUID" -ne 0 ]]', 'true'), encoding="utf-8")
    def executable(path, content):
        path.write_text("#!/usr/bin/env bash\n" + content, encoding="utf-8")
        path.chmod(0o755)
    log = tmp_path / "calls.log"
    template = tmp_path / "python-template"
    executable(template, 'echo "python $*" >> "$INSTALL_LOG"\nexit 0\n')
    venv = project / ".venv" / "bin"
    venv.mkdir(parents=True)
    executable(venv / "python", 'echo "old-python $*" >> "$INSTALL_LOG"\n' + ('exit 0\n' if compatible else 'exit 1\n'))
    executable(fake_bin / "uname", 'if [[ "$1" == -m ]]; then echo x86_64; else echo Linux; fi\n')
    executable(fake_bin / "git", 'exit 0\n')
    executable(fake_bin / "crontab", 'exit 0\n')
    executable(fake_bin / "systemctl", 'exit 3\n')
    executable(fake_bin / "uv", '''
echo "uv $*" >> "$INSTALL_LOG"
mkdir -p .venv/bin
cp "$PY_TEMPLATE" .venv/bin/python
chmod +x .venv/bin/python
''')
    executable(fake_bin / "curl", '''
echo "curl $*" >> "$INSTALL_LOG"
while [[ $# -gt 0 ]]; do
    if [[ "$1" == -o ]]; then destination="$2"; break; fi
    shift
done
printf '#!/usr/bin/env bash\necho cloudflared-test\n' > "$destination"
''')
    environment = {**os.environ, "FAKE_BIN": fake_bin.as_posix(), "INSTALL_LOG": log.as_posix(),
                   "PY_TEMPLATE": template.as_posix(), "INSTALL_SCRIPT": (project / "install.sh").as_posix()}
    command = 'export PATH="$(cd "$FAKE_BIN" && pwd):$PATH"; bash "$INSTALL_SCRIPT" --local --no-setup --no-deploy'
    result = subprocess.run([bash, "-c", command], env=environment, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    calls = log.read_text(encoding="utf-8")
    assert (data / "config.enc").read_bytes() == b"existing-private-config"
    assert (data / "cloudflared").is_file()
    assert "cloudflared-linux-amd64" in calls
    assert "systemctl restart" not in calls
    if compatible:
        assert "uv venv" not in calls and not list(project.glob(".venv.backup-*"))
    else:
        assert "uv venv --python 3.12 --seed .venv" in calls
        assert len(list(project.glob(".venv.backup-*"))) == 1
