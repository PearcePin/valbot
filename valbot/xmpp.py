"""On-demand Riot roster/presence and explicit private messages over validated TLS."""
import base64
from collections import deque
import json
import re
import socket
import ssl
import time
import uuid
from xml.etree import ElementTree as ET
from xml.parsers import expat

from .auth import RiotAuth, AuthError


class ChatError(RuntimeError):
    pass


def local_tag(tag):
    return tag.rsplit("}", 1)[-1]


def child(element, name):
    return next((x for x in element if local_tag(x.tag) == name), None)


def credentials(vault, http):
    auth = RiotAuth(vault)
    session = auth.session()
    for attempt in range(2):
        response = http.get("https://riot-geo.pas.si.riotgames.com/pas/v1/service/chat",
                            headers={"Authorization": "Bearer " + session["access_token"]})
        if response.status_code == 401 and attempt == 0:
            session = auth.session(force=True)
            continue
        if response.status_code != 200:
            raise ChatError(f"PAS HTTP {response.status_code}")
        break
    pas = response.text.strip()
    if pas.startswith('"'):
        pas = response.json()
    try:
        payload = pas.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        affinity = claims["affinity"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ChatError("PAS 格式不符") from exc
    if claims.get("sub") and claims["sub"] != session["puuid"]:
        raise AuthError("PAS 帳號與 Bot 登入不同。")
    response = http.get("https://clientconfig.rpg.riotgames.com/api/v1/config/player",
                        params={"app": "Riot Client"}, headers={
                            "Authorization": "Bearer " + session["access_token"],
                            "X-Riot-Entitlements-JWT": session["entitlements_token"]})
    if response.status_code != 200:
        raise ChatError(f"Chat config HTTP {response.status_code}")
    config = response.json()
    host = (config.get("chat.affinities") or {}).get(affinity, "")
    domain = (config.get("chat.affinity_domains") or {}).get(affinity, "")
    if not isinstance(host, str) or not re.fullmatch(r"[a-z0-9-]+\.chat\.si\.riotgames\.com", host):
        raise ChatError("未提供可信的 Riot 聊天伺服器")
    if not isinstance(domain, str) or not re.fullmatch(r"[a-z0-9-]+(?:\.pvp\.net)?", domain):
        raise ChatError("聊天區域格式不符")
    if "." not in domain:
        domain += ".pvp.net"
    port = int(config.get("chat.port", 5223))
    if port != 5223:
        raise ChatError("不支援的 Riot 聊天連接埠")
    return {**session, "pas": pas, "host": host, "domain": domain, "port": port}


class XmlStream:
    """Incrementally decode bounded XMPP stanzas across arbitrary TCP fragments."""

    def __init__(self):
        self.parser = expat.ParserCreate(namespace_separator="}")
        if hasattr(self.parser, "SetReparseDeferralEnabled"):
            # Complete small live stanzas must be delivered without waiting for another packet.
            self.parser.SetReparseDeferralEnabled(False)
        self.parser.StartElementHandler = self.start
        self.parser.EndElementHandler = self.end
        self.parser.CharacterDataHandler = self.content
        self.parser.StartDoctypeDeclHandler = self.reject_dtd
        self.parser.EntityDeclHandler = self.reject_dtd
        self.stack = []
        self.root = None
        self.pending = deque()
        self.bytes = 0

    @staticmethod
    def reject_dtd(*_):
        raise ChatError("不接受 XML DTD")

    def start(self, name, attributes):
        if len(self.stack) >= 32:
            raise ChatError("XML 層數過深")
        name = "{" + name if "}" in name else name
        element = ET.Element(name, attributes)
        if self.stack:
            self.stack[-1].append(element)
        else:
            self.root = element
        self.stack.append(element)

    def end(self, _):
        element = self.stack.pop()
        if len(self.stack) == 1:
            self.pending.append(element)
            self.root.remove(element)
            self.bytes = 0

    def content(self, text):
        if self.stack:
            element = self.stack[-1]
            element.text = (element.text or "") + text

    def feed(self, chunk):
        self.bytes += len(chunk)
        if self.bytes > 1024 * 1024:
            raise ChatError("XMPP stanza 過大")
        self.parser.Parse(chunk, False)


class RiotChat:
    def __init__(self, creds, stop):
        self.creds, self.stop = creds, stop
        self.socket = None
        self.xml = XmlStream()
        self.deferred = deque()
        self.connect_deadline = None
        self.allowed_friends = set()
        self.message_handler = None

    def send(self, element):
        data = element if isinstance(element, bytes) else ET.tostring(element, encoding="utf-8")
        self.socket.sendall(data)

    def read(self, seconds=30):
        if self.deferred:
            stanza = self.deferred.popleft()
        else:
            stanza = self._read(seconds)
        if stanza is not None and local_tag(stanza.tag) == "message" and self.message_handler:
            self.message_handler(stanza)
        return stanza

    def _read(self, seconds=30):
        deadline = time.monotonic() + seconds
        while not self.stop.is_set() and time.monotonic() < deadline:
            if self.xml.pending:
                return self.xml.pending.popleft()
            try:
                chunk = self.socket.recv(8192)
            except socket.timeout:
                continue
            if not chunk:
                raise ChatError("聊天連線已中斷")
            self.xml.feed(chunk)
        return None

    def expect(self, tag, stanza_id=None):
        deadline = min(time.monotonic() + 30, self.connect_deadline or float("inf"))
        while time.monotonic() < deadline and not self.stop.is_set():
            stanza = self._read(min(5, max(0.1, deadline - time.monotonic())))
            if stanza is None:
                continue
            if local_tag(stanza.tag) in {"failure", "error"} or stanza.get("type") == "error":
                raise ChatError("XMPP 驗證／請求被拒絕")
            if local_tag(stanza.tag) == tag and (stanza_id is None or stanza.get("id") == stanza_id):
                return stanza
            if local_tag(stanza.tag) in {"presence", "message"} or (local_tag(stanza.tag) == "iq" and stanza.get("type") == "set"):
                if len(self.deferred) >= 2000:
                    raise ChatError("好友狀態資料過多")
                self.deferred.append(stanza)
        raise ChatError("XMPP 驗證逾時")

    def open_stream(self):
        self.xml = XmlStream()
        self.send((f'<stream:stream to="{self.creds["domain"]}" version="1.0" '
                   'xmlns="jabber:client" xmlns:stream="http://etherx.jabber.org/streams">').encode())
        features = self.expect("features")
        return features

    def connect(self):
        self.connect_deadline = time.monotonic() + 20
        raw = socket.create_connection((self.creds["host"], self.creds["port"]), timeout=10)
        try:
            self.socket = ssl.create_default_context().wrap_socket(raw, server_hostname=self.creds["host"])
        except Exception:
            raw.close()
            raise
        self.socket.settimeout(1)
        self.open_stream()
        auth = ET.Element("auth", {"xmlns": "urn:ietf:params:xml:ns:xmpp-sasl", "mechanism": "X-Riot-RSO-PAS"})
        ET.SubElement(auth, "rso_token").text = self.creds["access_token"]
        ET.SubElement(auth, "pas_token").text = self.creds["pas"]
        self.send(auth)
        self.expect("success")
        self.open_stream()
        iq = ET.Element("iq", {"type": "set", "id": "valbot-bind"})
        bind = ET.SubElement(iq, "bind", {"xmlns": "urn:ietf:params:xml:ns:xmpp-bind"})
        ET.SubElement(bind, "puuid-mode", {"enabled": "true"})
        ET.SubElement(bind, "resource").text = "RC-VALBOT-" + uuid.uuid4().hex[:8]
        self.send(iq)
        self.expect("iq", "valbot-bind")
        iq = ET.Element("iq", {"type": "set", "id": "valbot-session"})
        session = ET.SubElement(iq, "session", {"xmlns": "urn:ietf:params:xml:ns:xmpp-session"})
        ET.SubElement(session, "platform").text = "riot"
        self.send(iq)
        self.expect("iq", "valbot-session")
        iq = ET.Element("iq", {"type": "get", "id": "valbot-roster"})
        ET.SubElement(iq, "query", {"xmlns": "jabber:iq:riotgames:roster", "last_state": "true"})
        self.send(iq)
        roster = self.expect("iq", "valbot-roster")
        query = child(roster, "query")
        if query is None or "riotgames:roster" not in query.tag:
            raise ChatError("未取得 Riot 好友名單")
        self.allowed_friends = {item.get("jid", "").split("/", 1)[0] for item in query
                                if local_tag(item.tag) == "item" and item.get("subscription") == "both"}
        self.send(ET.Element("presence"))
        return roster

    def send_message(self, jid, body, message_id):
        if jid not in self.allowed_friends or not re.fullmatch(r"[0-9a-fA-F-]{36}@[a-z0-9-]+\.pvp\.net", jid):
            raise ChatError("對象不是目前帳號的 Riot 好友")
        validate_body(body)
        stanza = ET.Element("message", {"to": jid, "type": "chat", "id": message_id})
        ET.SubElement(stanza, "body").text = body
        self.send(stanza)
        # Routing errors may arrive; silence is not a delivery/read receipt.
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            response = self.read(seconds=max(0.1, deadline - time.monotonic()))
            if response is None:
                continue
            if local_tag(response.tag) in {"error", "failure"} or (
                local_tag(response.tag) == "message" and response.get("type") == "error"
                and (response.get("id") == message_id or response.get("from", "").split("/", 1)[0] == jid)):
                raise ChatError("Riot 拒絕此私訊")

    def heartbeat(self):
        self.send(b" ")

    def close(self):
        if self.socket:
            self.socket.close()


def validate_body(body):
    if not isinstance(body, str) or not body.strip() or len(body) > 500:
        raise ChatError("訊息須為 1 至 500 個字")
    if any(not (c in "\t\n\r" or 0x20 <= ord(c) <= 0xD7FF or 0xE000 <= ord(c) <= 0xFFFD
                or 0x10000 <= ord(c) <= 0x10FFFF) for c in body):
        raise ChatError("訊息包含不支援的控制字元")
