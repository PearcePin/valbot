from unittest.mock import Mock

from linebot.v3.messaging.exceptions import ApiException

import run_daily
from valbot import flex
from valbot.storage import Vault


def configure(tmp_path, monkeypatch, messages):
    vault = Vault(tmp_path)
    vault.write("config", {"line_user_id": "Uowner", "line_access_token": "secret"})
    monkeypatch.setattr(run_daily, "RiotClient", Mock())
    service = Mock()
    service.daily.return_value = messages
    monkeypatch.setattr(run_daily, "BotService", Mock(return_value=service))
    line = Mock()
    monkeypatch.setattr(run_daily, "LineClient", Mock(return_value=line))
    monkeypatch.setattr("sys.argv", ["run_daily.py"])
    return vault, line


def test_daily_resumes_with_same_retry_key_and_skips_sent_batches(tmp_path, monkeypatch):
    messages = flex.messages([flex.notice("Test", "Test") for _ in range(6)])
    vault, line = configure(tmp_path, monkeypatch, messages)
    line.push.side_effect = [None, ApiException(status=503)]
    assert run_daily.main() == 1
    saved = vault.read("daily")
    assert saved["sent"] == 1
    line.reset_mock(side_effect=True)
    assert run_daily.main() == 0
    assert line.push.call_count == 1
    assert line.push.call_args.args[2] == saved["keys"][1]
    assert vault.read("daily")["done"] is True
    line.reset_mock()
    assert run_daily.main() == 0
    line.push.assert_not_called()


def test_accepted_retry_conflict_is_success(tmp_path, monkeypatch):
    vault, line = configure(tmp_path, monkeypatch, flex.messages([flex.menu()]))
    accepted = ApiException(status=409)
    accepted.headers = {"x-line-accepted-request-id": "accepted"}
    line.push.side_effect = accepted
    assert run_daily.main() == 0
    assert vault.read("daily")["done"] is True


def test_dry_run_never_pushes_or_changes_checkpoint(tmp_path, monkeypatch):
    vault, line = configure(tmp_path, monkeypatch, flex.messages([flex.menu()]))
    monkeypatch.setattr("sys.argv", ["run_daily.py", "--dry-run"])
    assert run_daily.main() == 0
    line.push.assert_not_called()
    assert vault.read("daily") == {}
    assert (tmp_path / "daily-preview.json").exists()
