import threading
from unittest.mock import Mock, MagicMock

import pytest

from valbot import daemon
from valbot import line as line_module
from valbot.line import LineClient
from valbot.systemd import unit


def test_new_tunnel_is_healthy_and_line_verified_before_update(monkeypatch):
    calls = []
    api = Mock()
    api.test_webhook_endpoint.side_effect = lambda *a, **k: (calls.append("verify") or Mock(success=True))
    api.set_webhook_endpoint.side_effect = lambda *a, **k: calls.append("set")
    endpoint = "https://example-test.trycloudflare.com/webhook"
    api.get_webhook_endpoint.return_value = Mock(endpoint=endpoint, active=True)
    monkeypatch.setattr(line_module, "ApiClient", MagicMock())
    monkeypatch.setattr(line_module, "MessagingApi", Mock(return_value=api))
    monkeypatch.setattr(daemon, "wait_health", lambda *a, **k: calls.append("health"))
    daemon.sync_webhook("https://example-test.trycloudflare.com", "private-token", threading.Event())
    assert calls == ["health", "verify", "set"]


def test_failed_line_verification_keeps_old_endpoint(monkeypatch):
    api = Mock()
    api.test_webhook_endpoint.return_value = Mock(success=False)
    monkeypatch.setattr(line_module, "ApiClient", MagicMock())
    monkeypatch.setattr(line_module, "MessagingApi", Mock(return_value=api))
    with pytest.raises(RuntimeError):
        LineClient("private-token").configure_webhook("https://example-test.trycloudflare.com/webhook")
    api.set_webhook_endpoint.assert_not_called()


def test_tunnel_sync_refuses_unrelated_urls(monkeypatch):
    wait = Mock()
    monkeypatch.setattr(daemon, "wait_health", wait)
    with pytest.raises(ValueError):
        daemon.sync_webhook("https://example.com", "private-token", threading.Event())
    wait.assert_not_called()


def test_systemd_unit_escapes_paths_and_runs_as_user():
    contents = unit("/home/pearce/my bot%test", "/home/pearce/my bot%test/.venv/bin/python",
                    "/home/pearce/my bot%test/data", "pearce")
    assert 'WorkingDirectory=/home/pearce/my bot%%test\n' in contents
    assert 'ExecStart="/home/pearce/my bot%%test/.venv/bin/python" -m valbot.daemon' in contents
    assert "User=pearce" in contents
    assert "KillMode=control-group" in contents
    assert "WantedBy=multi-user.target" in contents


def test_unit_passes_native_systemd_parser(tmp_path):
    import os
    import shutil
    import subprocess
    import sys
    if os.name != "posix" or not shutil.which("systemd-analyze"):
        pytest.skip("native systemd validator is only available on Linux")
    import pwd
    username = pwd.getpwuid(os.getuid()).pw_name
    root = tmp_path / "project with space%"
    root.mkdir()
    output = tmp_path / "valbot-test.service"
    output.write_text(unit(root, sys.executable, root / "data", username), encoding="utf-8")
    result = subprocess.run(["systemd-analyze", "verify", str(output)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_daemon_startup_failure_stops_launched_bot(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from valbot.storage import ROOT
    binary = tmp_path / "cloudflared"
    binary.write_text("placeholder")
    monkeypatch.setenv("VALBOT_CLOUDFLARED", str(binary))
    monkeypatch.setattr(daemon, "os", SimpleNamespace(name="posix", environ=daemon.os.environ,
                                                     access=lambda *a: True, X_OK=1))
    monkeypatch.setattr(daemon, "load_config", lambda: {"line_access_token": "private-token"})
    monkeypatch.setattr(daemon.signal, "signal", Mock())
    bot = Mock()
    bot.poll.return_value = None
    launch = Mock(return_value=bot)
    monkeypatch.setattr(daemon.subprocess, "Popen", launch)
    monkeypatch.setattr(daemon, "wait_health", Mock(side_effect=RuntimeError("unavailable")))
    assert daemon.main() == 1
    assert launch.call_count == 1
    assert launch.call_args.kwargs["cwd"] == ROOT
    bot.terminate.assert_called_once()
    bot.wait.assert_called_once_with(timeout=10)


def test_windows_launcher_selects_exe_and_cleans_up_without_real_launch(tmp_path, monkeypatch):
    from types import SimpleNamespace
    binary = tmp_path / "cloudflared.exe"
    binary.write_bytes(b"placeholder")
    monkeypatch.delenv("VALBOT_CLOUDFLARED", raising=False)
    monkeypatch.setattr(daemon, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(daemon, "os", SimpleNamespace(name="nt", environ=daemon.os.environ,
                                                     access=lambda path, mode: str(path).endswith(".exe"), X_OK=1))
    monkeypatch.setattr(daemon, "load_config", lambda: {"line_access_token": "private-token"})
    monkeypatch.setattr(daemon.signal, "signal", Mock())
    bot = Mock()
    bot.poll.return_value = None
    launch = Mock(return_value=bot)
    monkeypatch.setattr(daemon.subprocess, "Popen", launch)
    monkeypatch.setattr(daemon, "wait_health", Mock(side_effect=RuntimeError("unavailable")))
    assert daemon.main() == 1
    assert launch.call_count == 1
    bot.terminate.assert_called_once()
