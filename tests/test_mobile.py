import json
from unittest.mock import Mock

import pytest

from valbot import mobile
from valbot.auth import AuthError
from valbot.storage import Vault


@pytest.fixture
def vault(tmp_path, monkeypatch):
    value = Vault(tmp_path)
    monkeypatch.setattr(mobile, "_vault", value)
    return value


def response(action, payload=None):
    return json.loads(mobile.dispatch(action, json.dumps(payload or {})))


def test_android_cipher_vault_does_not_create_exportable_key(tmp_path):
    native = Mock()
    native.encrypt.side_effect = lambda value: "sealed-" + value
    native.decrypt.side_effect = lambda value: value.removeprefix("sealed-")
    vault = Vault(tmp_path, cipher=mobile.AndroidCipher(native))
    vault.write("session", {"puuid": "owner"})
    assert vault.read("session")["puuid"] == "owner"
    assert not (tmp_path / "vault.key").exists()


def test_mobile_session_status_never_exposes_tokens_or_cookies(vault):
    vault.write("session", {"puuid": "owner-puuid", "access_token": "private-token", "cookies": [{"value": "private-cookie"}], "expires_at": 99})
    raw = mobile.dispatch("status")
    assert json.loads(raw)["data"]["logged_in"]
    assert "private-token" not in raw and "private-cookie" not in raw


def test_mobile_uses_all_existing_command_paths_without_line(vault, monkeypatch):
    vault.write("session", {"puuid": "owner", "expires_at": 9999999999})
    vault.write("config", {"region": "ap", "line_user_id": "android-local", "riot_puuid": "owner"})
    service = Mock()
    service.command.return_value = [{"type": "flex"}]
    monkeypatch.setattr(mobile, "RiotClient", Mock())
    monkeypatch.setattr(mobile, "BotService", Mock(return_value=service))
    assert response("command", {"command": "戰績 20"})["ok"]
    service.command.assert_called_once_with("戰績 20")
    mailbox = Mock(return_value=[{"type": "flex"}])
    monkeypatch.setattr(mobile.mailbox, "command", mailbox)
    assert response("command", {"command": "好友訊息"})["ok"]
    mailbox.assert_called_once()


def test_auth_error_prompts_in_app_verification_and_never_leaks_secret(vault, monkeypatch):
    monkeypatch.setattr(mobile, "run_command", Mock(side_effect=AuthError("sensitive token")))
    result = response("command", {"command": "商店"})
    assert result["auth_required"] and "sensitive" not in result["error"]


def test_mobile_logout_clears_account_messages_and_drafts(vault):
    for name in ("session", "config", "friend_dm", "friend_messages", "friend_snapshot", "mobile_daily"):
        vault.write(name, {"private": "value"})
    assert response("logout")["ok"]
    assert all(not vault.read(name) for name in ("session", "config", "friend_dm", "friend_messages", "friend_snapshot", "mobile_daily"))


def test_invalid_regions_and_unknown_requests_are_rejected(vault):
    assert not response("region", {"region": "untrusted"})["ok"]
    assert not response("execute_arbitrary_code")["ok"]
    assert mobile.config()["region"] == "ap"
