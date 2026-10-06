import json
import threading
import time
from unittest.mock import Mock
from xml.etree import ElementTree as ET

import pytest

from valbot import mailbox, friends, flex, xmpp
from valbot.app import process_event
from valbot.line import LineClient
from valbot.storage import Vault
from tests.test_friends import JID, roster
from tests.test_friend_actions import CONFIG, snapshot


def incoming(message_id="remote-id", sender=JID, kind="chat", body="一起玩嗎？"):
    node = ET.Element("message", {"id": message_id, "from": sender + "/PC", "type": kind})
    ET.SubElement(node, "body").text = body
    return node


def save(vault, **kwargs):
    return mailbox.record(CONFIG, vault, incoming(**kwargs), friends.PresenceTracker(roster()).friends)


def test_incoming_private_message_is_encrypted_deduplicated_and_visible_after_restart(tmp_path):
    vault = Vault(tmp_path)
    assert save(vault)
    assert not save(Vault(tmp_path))
    saved = mailbox.state(CONFIG, Vault(tmp_path))
    assert len(saved["messages"]) == 1 and not saved["messages"][0]["seen"]
    assert "一起玩嗎？".encode() not in (tmp_path / "friend_messages.enc").read_bytes()
    assert "一起玩嗎？" in json.dumps(mailbox.render(CONFIG, vault), ensure_ascii=False)
    LineClient.models(mailbox.render(CONFIG, vault))


@pytest.mark.parametrize("changes", [{"sender": "stranger@as2.pvp.net"}, {"kind": "groupchat"},
                                     {"kind": "error"}, {"body": ""}])
def test_only_mutual_friend_private_text_is_saved(tmp_path, changes):
    vault = Vault(tmp_path)
    assert not save(vault, **changes)
    assert not mailbox.state(CONFIG, vault)["messages"]


def test_other_recipient_and_changed_account_cannot_leak_messages(tmp_path):
    vault = Vault(tmp_path)
    stanza = incoming()
    stanza.set("to", "other@as2.pvp.net")
    assert not mailbox.record(CONFIG, vault, stanza, friends.PresenceTracker(roster()).friends)
    save(vault)
    assert mailbox.state({**CONFIG, "riot_puuid": "other"}, vault)["messages"] == []


def test_delay_timestamp_and_bounded_archive_and_local_seen_only(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    monkeypatch.setattr(mailbox, "MAX_MESSAGES", 2)
    save(vault, message_id="first")
    save(vault, message_id="second")
    stanza = incoming("third")
    ET.SubElement(stanza, "{urn:xmpp:delay}delay", {"stamp": "2025-01-01T00:00:00Z"})
    assert mailbox.record(CONFIG, vault, stanza, friends.PresenceTracker(roster()).friends)
    messages = mailbox.state(CONFIG, vault)["messages"]
    assert len(messages) == 2 and messages[-1]["sent_at"] == 1735689600
    query = Mock()
    monkeypatch.setattr(friends, "query", query)
    mailbox.command(CONFIG, vault, "訊息標為已看")
    assert all(m["seen"] for m in mailbox.state(CONFIG, vault)["messages"])
    query.assert_not_called()


def test_manual_check_runs_once_and_failure_keeps_old_inbox(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    save(vault)
    query = Mock(return_value={})
    monkeypatch.setattr(friends, "query", query)
    mailbox.command(CONFIG, vault, "好友訊息")
    assert query.call_count == 1 and mailbox.state(CONFIG, vault)["checked_at"] > 0
    before = mailbox.state(CONFIG, vault)["checked_at"]
    query.side_effect = RuntimeError("must never print tokens")
    result = mailbox.command(CONFIG, vault, "好友訊息")
    content = json.dumps(result, ensure_ascii=False)
    assert "檢查失敗" in content and "一起玩嗎？" in content and "tokens" not in content
    assert mailbox.state(CONFIG, vault)["checked_at"] == before


def test_received_message_reply_creates_draft_without_sending(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    save(vault)
    message = mailbox.state(CONFIG, vault)["messages"][0]
    snapshot(vault)
    query = Mock(return_value=vault.read("friend_snapshot"))
    monkeypatch.setattr(friends, "query", query)
    result = mailbox.command(CONFIG, vault, "回覆好友 " + message["id"])
    assert vault.read("friend_dm")["status"] == "composing"
    assert vault.read("friend_dm")["friend"]["jid"] == JID
    assert "輸入私訊內容" in json.dumps(result, ensure_ascii=False)


def test_view_pages_fit_line_and_do_not_mark_as_seen_or_reconnect(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    for i in range(11):
        save(vault, message_id=str(i), body="👋" * 2001)
    query = Mock()
    monkeypatch.setattr(friends, "query", query)
    result = mailbox.render(CONFIG, vault)
    assert len(result) == 3
    LineClient.models(flex.messages([flex.menu()]) + result)
    assert not any(m["seen"] for m in mailbox.state(CONFIG, vault)["messages"])
    mailbox.command(CONFIG, vault, "訊息頁 2")
    query.assert_not_called()


def test_xml_read_handler_receives_deferred_message_once():
    chat = xmpp.RiotChat({}, threading.Event())
    chat.xml.feed(b'<stream:stream xmlns:stream="http://etherx.jabber.org/streams">')
    message = incoming()
    chat.xml.feed(ET.tostring(message) + b'<iq id="roster" type="result"/>')
    assert chat.expect("iq", "roster").get("id") == "roster"
    callback = Mock()
    chat.message_handler = callback
    assert xmpp.child(chat.read(), "body").text == "一起玩嗎？"
    callback.assert_called_once()
    assert xmpp.child(callback.call_args.args[0], "body").text == "一起玩嗎？"


def test_mail_commands_take_priority_over_draft_and_are_owner_only(tmp_path, monkeypatch):
    vault, line, check = Vault(tmp_path), Mock(), Mock(return_value=flex.messages([flex.notice("訊息", "測試")]))
    monkeypatch.setattr(mailbox, "command", check)
    vault.write("friend_dm", {"identity": friends.identity(CONFIG), "status": "composing", "created_at": time.time()})
    def event(user):
        return {"type": "message", "replyToken": "reply", "source": {"type": "user", "userId": user},
                "message": {"text": "好友訊息"}}
    process_event(event("outsider"), CONFIG, vault, line)
    check.assert_not_called()
    process_event(event(CONFIG["line_user_id"]), CONFIG, vault, line)
    check.assert_called_once()
    assert vault.read("friend_dm")["status"] == "composing"
    assert line.reply.call_args.args[1][0]["contents"] == flex.menu()
