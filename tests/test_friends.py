import base64
from collections import deque
import json
import threading
from unittest.mock import Mock
from xml.etree import ElementTree as ET

import httpx
import pytest

from valbot import friends, xmpp
from valbot.line import LineClient
from valbot.storage import Vault

JID = "11111111-1111-1111-1111-111111111111@as2.pvp.net"


def roster():
    return ET.fromstring(f'<iq><query xmlns="jabber:iq:riotgames:roster"><item jid="{JID}" subscription="both">'
                         '<id name="Test Friend" tagline="AP"/></item></query></iq>')


def presence(resource="PC", available=True, valorant=True, activity="MENUS"):
    data = base64.b64encode(json.dumps({"isValid": True, "sessionLoopState": activity}).encode()).decode()
    game = f'<valorant><st>chat</st><p>{data}</p></valorant>' if valorant else '<keystone><st>chat</st></keystone>'
    return ET.fromstring(f'<presence from="{JID}/{resource}"' + ('' if available else ' type="unavailable"')
                         + f'><games>{game}</games></presence>')


def test_manual_snapshot_includes_already_online_friends_without_notifications():
    tracker = friends.PresenceTracker(roster())
    assert tracker.apply(presence()) is None
    online = tracker.snapshot()[0]
    assert online["online"] and online["name"] == "Test Friend"
    LineClient.models(friends.flex.messages([friends.card(online)]))


def test_mobile_presence_and_unrelated_users_do_not_trigger_alert():
    tracker = friends.PresenceTracker(roster())
    assert tracker.apply(presence(resource="Mobile", valorant=False)) is None
    assert not tracker.snapshot()[0]["online"]
    stanza = presence()
    stanza.set("from", "unknown@as2.pvp.net/PC")
    assert tracker.apply(stanza) is None


def test_multiple_resources_do_not_create_false_reconnect_notifications():
    tracker = friends.PresenceTracker(roster())
    tracker.apply(presence(resource="PC1"))
    tracker.apply(presence(resource="PC2"))
    tracker.apply(presence(resource="PC1", available=False))
    assert len(tracker.snapshot()) == 1 and tracker.snapshot()[0]["online"]
    tracker.apply(presence(resource="PC2", available=False))
    assert not tracker.snapshot()[0]["online"]


def test_auto_alert_commands_and_worker_are_removed():
    from valbot.app import COMMANDS
    assert "好友提醒開啟" not in COMMANDS and "好友提醒關閉" not in COMMANDS
    assert not hasattr(friends, "worker") and not hasattr(friends, "notify")


def test_stream_handles_fragmented_and_combined_stanzas():
    stream = xmpp.XmlStream()
    data = (f'<stream:stream xmlns:stream="http://etherx.jabber.org/streams" xmlns="jabber:client">'
            f'<presence from="{JID}/PC"><status>你好</status></presence><iq id="two"/>').encode()
    for start in range(0, len(data), 7):
        stream.feed(data[start:start + 7])
    assert [xmpp.local_tag(x.tag) for x in stream.pending] == ["presence", "iq"]
    assert len(stream.root) == 0


def test_stream_rejects_dtd_split_over_packets():
    stream = xmpp.XmlStream()
    stream.feed(b"<!DOC")
    with pytest.raises(xmpp.ChatError):
        stream.feed(b"TYPE test [<!ENTITY x 'bad'>]>")


def test_pas_uses_authenticated_player_and_official_chat_host(tmp_path, monkeypatch):
    session = {"puuid": "owner", "access_token": "access", "entitlements_token": "ent", "expires_at": 9999999999}
    monkeypatch.setattr(xmpp, "RiotAuth", Mock(return_value=Mock(session=Mock(return_value=session))))
    payload = base64.urlsafe_b64encode(json.dumps({"sub": "owner", "affinity": "as2"}).encode()).decode().rstrip("=")
    host = ["as2.chat.si.riotgames.com"]

    def handler(request):
        if request.url.path.endswith("/chat"):
            return httpx.Response(200, text="header." + payload + ".signature")
        return httpx.Response(200, json={"chat.affinities": {"as2": host[0]},
            "chat.affinity_domains": {"as2": "as2"}, "chat.port": 5223})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = xmpp.credentials(Vault(tmp_path), client)
        assert result["domain"] == "as2.pvp.net"
        assert result["host"] == host[0]
        host[0] = "evil.example"
        with pytest.raises(xmpp.ChatError):
            xmpp.credentials(Vault(tmp_path), client)


def test_tls_handshake_roster_and_unique_resource(monkeypatch):
    opening = b'<stream:stream xmlns:stream="http://etherx.jabber.org/streams" xmlns="jabber:client">'
    roster_result = roster()
    roster_result.set("id", "valbot-roster")
    roster_result.set("type", "result")
    chunks = deque([opening[:15], opening[15:] + b'<stream:features/>',
                    b'<success xmlns="urn:ietf:params:xml:ns:xmpp-sasl"/>',
                    opening + b'<stream:features/>', b'<iq id="valbot-bind" type="result"/>',
                    b'<iq id="valbot-session" type="result"/>',
                    ET.tostring(presence()) + ET.tostring(roster_result)])
    connection = Mock()
    connection.recv.side_effect = lambda size: chunks.popleft() if chunks else b""
    context = Mock()
    context.wrap_socket.return_value = connection
    monkeypatch.setattr(xmpp.socket, "create_connection", Mock(return_value=connection))
    monkeypatch.setattr(xmpp.ssl, "create_default_context", Mock(return_value=context))
    chat = xmpp.RiotChat({"host": "as2.chat.si.riotgames.com", "port": 5223, "domain": "as2.pvp.net",
                         "access_token": "private-access", "pas": "private-pas"}, threading.Event())
    assert xmpp.child(chat.connect(), "query") is not None
    assert xmpp.local_tag(chat.read().tag) == "presence"
    context.wrap_socket.assert_called_once_with(connection, server_hostname="as2.chat.si.riotgames.com")
    sent = [call.args[0] for call in connection.sendall.call_args_list]
    assert any(b"RC-VALBOT-" in data for data in sent)
    assert not any(b"<message" in data for data in sent)
    chat.close()
    connection.close.assert_called_once()
