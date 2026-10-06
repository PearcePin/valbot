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


def test_startup_snapshot_does_not_notify_existing_online_friends():
    tracker = friends.PresenceTracker(roster(), 100)
    assert tracker.apply(presence(), 101) is None
    assert len(tracker.online()) == 1
    assert tracker.apply(presence(activity="INGAME"), 150) is None
    tracker.apply(presence(available=False), 151)
    alert = tracker.apply(presence(), 160)
    assert alert["name"] == "Test Friend"
    assert alert["activity"] == "MENUS"
    LineClient.models(friends.flex.messages([friends.card(alert)]))


def test_mobile_presence_and_unrelated_users_do_not_trigger_alert():
    tracker = friends.PresenceTracker(roster(), 100)
    assert tracker.apply(presence(resource="Mobile", valorant=False), 200) is None
    assert tracker.online() == []
    stanza = presence()
    stanza.set("from", "unknown@as2.pvp.net/PC")
    assert tracker.apply(stanza, 201) is None


def test_multiple_resources_do_not_create_false_reconnect_notifications():
    tracker = friends.PresenceTracker(roster(), 100)
    assert tracker.apply(presence(resource="PC1"), 150)
    assert tracker.apply(presence(resource="PC2"), 151) is None
    assert tracker.apply(presence(resource="PC1", available=False), 152) is None
    assert tracker.apply(presence(resource="PC1"), 153) is None
    assert len(tracker.online()) == 1


def test_alert_retry_key_and_cooldown_and_disabled_setting(tmp_path, monkeypatch):
    from linebot.v3.messaging.exceptions import ApiException
    vault = Vault(tmp_path)
    line = Mock()
    line.push.side_effect = [ApiException(status=503), None]
    monkeypatch.setattr(friends, "LineClient", Mock(return_value=line))
    stop = Mock()
    stop.is_set.return_value = False
    alert = {"jid": JID, "name": "Friend", "tag": "AP"}
    config = {"line_user_id": "owner", "line_access_token": "private"}
    assert friends.notify(config, vault, alert, 1000, stop)
    assert line.push.call_count == 2
    assert line.push.call_args_list[0].args[2] == line.push.call_args_list[1].args[2]
    assert not friends.notify(config, vault, alert, 1100, stop)
    vault.write("friend_preferences", {"enabled": False})
    assert not friends.notify(config, vault, alert, 2000, stop)
    assert line.push.call_count == 2


def test_friend_toggle_is_available_without_riot_auth(tmp_path):
    vault = Vault(tmp_path)
    friends.command(vault, "好友提醒關閉")
    assert not friends.enabled(vault)
    friends.command(vault, "好友提醒開啟")
    assert friends.enabled(vault)
    LineClient.models(friends.command(vault, "好友提醒"))


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
                    ET.tostring(roster_result)])
    connection = Mock()
    connection.recv.side_effect = lambda size: chunks.popleft() if chunks else b""
    context = Mock()
    context.wrap_socket.return_value = connection
    monkeypatch.setattr(xmpp.socket, "create_connection", Mock(return_value=connection))
    monkeypatch.setattr(xmpp.ssl, "create_default_context", Mock(return_value=context))
    chat = xmpp.RiotChat({"host": "as2.chat.si.riotgames.com", "port": 5223, "domain": "as2.pvp.net",
                         "access_token": "private-access", "pas": "private-pas"}, threading.Event())
    assert xmpp.child(chat.connect(), "query") is not None
    context.wrap_socket.assert_called_once_with(connection, server_hostname="as2.chat.si.riotgames.com")
    sent = [call.args[0] for call in connection.sendall.call_args_list]
    assert any(b"RC-VALBOT-" in data for data in sent)
    assert not any(b"<message" in data for data in sent)
    chat.close()
    connection.close.assert_called_once()
