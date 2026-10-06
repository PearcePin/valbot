from contextlib import contextmanager
import json
import time
import threading
from unittest.mock import Mock
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from valbot import friends, xmpp, flex
from valbot.app import create_app, process_event
from valbot.line import LineClient
from valbot.storage import Vault
from tests.test_friends import JID, roster, presence

CONFIG = {"riot_puuid": "owner", "line_user_id": "owner-line", "line_channel_secret": "secret"}


def snapshot(vault):
    friend = friends.PresenceTracker(roster()).snapshot()[0]
    state = {"identity": friends.identity(CONFIG), "updated_at": time.time(), "friends": [friend]}
    vault.write("friend_snapshot", state)
    return friend


def prepared(vault):
    friend = snapshot(vault)
    friends.command(CONFIG, vault, "私訊選擇 " + friend["key"])
    messages = friends.command(CONFIG, vault, "要不要一起打？ <3 & 好耶")
    LineClient.models(messages)
    return vault.read("friend_dm")


def mock_connection(monkeypatch, chat, new_roster=None):
    @contextmanager
    def connected(config, vault):
        try:
            yield chat, new_roster if new_roster is not None else roster()
        finally:
            chat.close()
    monkeypatch.setattr(friends, "connection", connected)


def test_query_connects_only_on_demand_closes_and_never_pushes(tmp_path, monkeypatch):
    vault, chat = Vault(tmp_path), Mock()
    elapsed = [0]
    def read(seconds):
        elapsed[0] += 1
        return presence() if elapsed[0] == 1 else None
    chat.read.side_effect = read
    monkeypatch.setattr(friends.time, "monotonic", lambda: elapsed[0])
    mock_connection(monkeypatch, chat)
    messages = friends.command(CONFIG, vault, "好友")
    assert elapsed[0] == 5
    chat.close.assert_called_once()
    assert vault.read("friend_snapshot")["friends"][0]["online"]
    chat.send_message.assert_not_called()
    LineClient.models(messages)


def test_merged_friend_entry_shows_all_friends_and_preserves_old_alias(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    friend = snapshot(vault)
    state = vault.read("friend_snapshot")
    state["friends"].append({**friend, "name": "Offline Friend", "key": "offline", "online": False})
    monkeypatch.setattr(friends, "query", Mock(return_value=state))
    first = friends.command(CONFIG, vault, "好友")
    alias = friends.command(CONFIG, vault, "傳訊息")
    assert first == alias and len(first[1]["contents"]["contents"]) == 2
    assert "私訊選擇 offline" in json.dumps(first, ensure_ascii=False)
    menu = json.dumps(flex.menu(), ensure_ascii=False)
    assert '"text": "好友"' in menu and '"text": "傳訊息"' not in menu


def test_app_startup_has_no_friend_connections_even_with_legacy_enabled_setting(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    vault.write("friend_preferences", {"enabled": True})
    query = Mock()
    monkeypatch.setattr(friends, "query", query)
    line = Mock()
    with TestClient(create_app({**CONFIG, "line_access_token": "token"}, vault, line)) as client:
        assert client.get("/health").status_code == 200
    query.assert_not_called()
    line.push.assert_not_called()


def test_compose_requires_confirmation_and_draft_is_encrypted(tmp_path, monkeypatch):
    vault, connect = Vault(tmp_path), Mock()
    monkeypatch.setattr(friends, "connection", connect)
    draft = prepared(vault)
    assert draft["status"] == "ready"
    connect.assert_not_called()
    assert draft["body"].encode() not in (tmp_path / "friend_dm.enc").read_bytes()
    friends.command(CONFIG, vault, "確認私訊 invalid")
    connect.assert_not_called()
    friends.command(CONFIG, vault, "取消私訊")
    assert vault.read("friend_dm") == {}


def test_explicit_confirm_sends_only_once_and_rechecks_current_friendship(tmp_path, monkeypatch):
    vault, chat = Vault(tmp_path), Mock()
    draft = prepared(vault)
    mock_connection(monkeypatch, chat)
    result = friends.command(CONFIG, vault, "確認私訊 " + draft["nonce"])
    assert result[0]["contents"]["header"]["contents"][1]["text"] == "私訊已提交"
    chat.send_message.assert_called_once_with(JID, draft["body"], "valbot-" + draft["nonce"])
    chat.close.assert_called_once()
    friends.command(CONFIG, Vault(tmp_path), "確認私訊 " + draft["nonce"])
    assert chat.send_message.call_count == 1


def test_removed_friend_or_changed_account_does_not_send(tmp_path, monkeypatch):
    vault, chat = Vault(tmp_path), Mock()
    draft = prepared(vault)
    empty = ET.fromstring('<iq><query xmlns="jabber:iq:riotgames:roster"/></iq>')
    mock_connection(monkeypatch, chat, empty)
    friends.command(CONFIG, vault, "確認私訊 " + draft["nonce"])
    chat.send_message.assert_not_called()
    friends.command({**CONFIG, "riot_puuid": "different"}, vault, "確認私訊 " + draft["nonce"])
    chat.send_message.assert_not_called()


def test_ambiguous_socket_failure_consumes_confirmation_without_automatic_retry(tmp_path, monkeypatch):
    vault, chat = Vault(tmp_path), Mock()
    draft = prepared(vault)
    chat.send_message.side_effect = TimeoutError()
    mock_connection(monkeypatch, chat)
    result = friends.command(CONFIG, vault, "確認私訊 " + draft["nonce"])
    assert "狀態未確認" in json.dumps(result, ensure_ascii=False)
    friends.command(CONFIG, Vault(tmp_path), "確認私訊 " + draft["nonce"])
    assert chat.send_message.call_count == 1 and vault.read("friend_dm")["status"] == "unknown"


def test_expired_snapshots_and_drafts_cannot_target_or_send(tmp_path, monkeypatch):
    vault, connect = Vault(tmp_path), Mock()
    monkeypatch.setattr(friends, "connection", connect)
    draft = prepared(vault)
    state = vault.read("friend_snapshot")
    state["updated_at"] -= 601
    vault.write("friend_snapshot", state)
    friends.command(CONFIG, vault, "私訊選擇 " + draft["friend"]["key"])
    draft["created_at"] -= 601
    vault.write("friend_dm", draft)
    friends.command(CONFIG, vault, "確認私訊 " + draft["nonce"])
    connect.assert_not_called()


def test_owner_only_webhook_routes_draft_and_confirmation_menu_first(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    friend = snapshot(vault)
    line = Mock()
    def event(text, owner="owner-line"):
        return {"type": "message", "replyToken": "reply", "source": {"type": "user", "userId": owner},
                "message": {"text": text}}
    process_event(event("私訊選擇 " + friend["key"], "outsider"), CONFIG, vault, line)
    assert vault.read("friend_dm") == {}
    process_event(event("私訊選擇 " + friend["key"]), CONFIG, vault, line)
    process_event(event("可以一起玩嗎"), CONFIG, vault, line)
    assert vault.read("friend_dm")["status"] == "ready"
    assert line.reply.call_args.args[1][0]["contents"] == flex.menu()
    line.push.assert_not_called()


def test_friend_pages_keep_all_friends_and_respect_flex_message_limits(tmp_path):
    vault = Vault(tmp_path)
    friend = snapshot(vault)
    state = vault.read("friend_snapshot")
    state["friends"] = [{**friend, "name": f"Friend {i}", "key": str(i)} for i in range(20)]
    vault.write("friend_snapshot", state)
    result = friends.command(CONFIG, vault, "私訊好友頁 2")
    assert len(result) == 2 and len(result[1]["contents"]["contents"]) == 8
    LineClient.models(result)


def test_xmpp_message_serialization_escapes_body_and_rejects_nonfriends(monkeypatch):
    chat = xmpp.RiotChat({}, threading.Event())
    chat.allowed_friends = {JID}
    chat.socket = Mock()
    elapsed = [0]
    def read(seconds):
        elapsed[0] += 2
        return None
    monkeypatch.setattr(xmpp.time, "monotonic", lambda: elapsed[0])
    chat.read = read
    body = '<message to="other">你好 & 世界</message>\n👋'
    chat.send_message(JID, body, "id")
    stanza = ET.fromstring(chat.socket.sendall.call_args.args[0])
    assert stanza.attrib == {"to": JID, "type": "chat", "id": "id"}
    assert len(stanza) == 1 and stanza.find("body").text == body
    with pytest.raises(xmpp.ChatError):
        chat.send_message("stranger@as2.pvp.net", "hello", "id2")


def test_xmpp_routing_error_is_not_reported_as_submission_success():
    chat = xmpp.RiotChat({}, threading.Event())
    chat.allowed_friends = {JID}
    chat.socket = Mock()
    chat.read = Mock(return_value=ET.fromstring(f'<message from="{JID}" type="error" id="id"/>'))
    with pytest.raises(xmpp.ChatError, match="拒絕"):
        chat.send_message(JID, "hello", "id")
    chat.socket.sendall.assert_called_once()


def test_fresh_account_validation_and_connection_cleanup(tmp_path, monkeypatch):
    vault, chat = Vault(tmp_path), Mock()
    creds = {"puuid": "different"}
    monkeypatch.setattr(friends, "credentials", Mock(return_value=creds))
    constructor = Mock(return_value=chat)
    monkeypatch.setattr(friends, "RiotChat", constructor)
    with pytest.raises(friends.AuthError):
        with friends.connection(CONFIG, vault):
            pass
    constructor.assert_not_called()
    creds["puuid"] = "owner"
    chat.connect.side_effect = xmpp.ChatError("authentication failed")
    with pytest.raises(xmpp.ChatError):
        with friends.connection(CONFIG, vault):
            pass
    chat.close.assert_called_once()


@pytest.mark.parametrize("body", ["", " " * 2, "x" * 501, "bad\x00text", "bad\ud800text"])
def test_invalid_message_bodies_never_enter_socket(body):
    with pytest.raises(xmpp.ChatError):
        xmpp.validate_body(body)
