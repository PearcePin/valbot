"""Owner-only VALORANT friend online alerts with startup/reconnect suppression."""
import base64
import json
import logging
import re
import time
import uuid

import httpx

from . import flex
from .line import LineClient
from .xmpp import RiotChat, credentials, local_tag, child, ChatError
from .auth import AuthError

log = logging.getLogger("valbot.friends")
FRIEND_COMMANDS = {"好友", "好友提醒", "好友提醒開啟", "好友提醒關閉"}


class PresenceTracker:
    def __init__(self, roster, now):
        self.friends = {}
        self.resources = {}
        self.quiet_until = now + 25
        self.apply_roster(roster)

    def apply_roster(self, stanza):
        query = child(stanza, "query")
        if query is None or "riotgames:roster" not in query.tag:
            return
        for item in query:
            if local_tag(item.tag) != "item":
                continue
            bare = item.get("jid", "").split("/", 1)[0]
            if not bare:
                continue
            if item.get("subscription") != "both":
                self.friends.pop(bare, None)
                self.resources.pop(bare, None)
                continue
            identity = child(item, "id")
            name = identity.get("name") if identity is not None else item.get("name")
            tag = identity.get("tagline") if identity is not None else None
            self.friends[bare] = {"name": name or "好友 " + bare.split("@")[0][:8], "tag": tag or ""}

    def apply(self, stanza, now):
        jid = stanza.get("from", "")
        bare, _, resource = jid.partition("/")
        if bare not in self.friends or stanza.get("type") not in {None, "unavailable"}:
            return None
        resources = self.resources.setdefault(bare, {})
        before = any(x["online"] for x in resources.values())
        if stanza.get("type") == "unavailable":
            resources.pop(resource, None)
        else:
            games = child(stanza, "games")
            valorant = child(games, "valorant") if games is not None else None
            details = {}
            if valorant is not None:
                payload = child(valorant, "p")
                try:
                    if payload is not None and payload.text:
                        details = json.loads(base64.b64decode(payload.text))
                        if not isinstance(details, dict):
                            details = {}
                except (ValueError, TypeError):
                    pass
            status = child(valorant, "st") if valorant is not None else None
            online = valorant is not None and status is not None and status.text in {"chat", "away", "dnd"} \
                and details.get("isValid") is not False
            resources[resource] = {"online": online, "activity": details.get("sessionLoopState", ""),
                                   "card": details.get("playerCardId", "")}
        after = any(x["online"] for x in resources.values())
        if after and not before and now >= self.quiet_until:
            return {"jid": bare, **self.friends[bare], **next(x for x in resources.values() if x["online"])}
        return None

    def online(self):
        return [{**self.friends[jid], **next(x for x in resources.values() if x["online"])}
                for jid, resources in self.resources.items() if jid in self.friends
                and any(x["online"] for x in resources.values())]


def enabled(vault):
    return vault.read("friend_preferences").get("enabled", True)


def card(friend):
    name = friend["name"] + ("#" + friend["tag"] if friend.get("tag") else "")
    activity = {"MENUS": "遊戲大廳", "PREGAME": "選角中", "INGAME": "對戰中"}.get(friend.get("activity"), "VALORANT 已上線")
    contents = [flex.text(name, "xl", weight="bold"), flex.text(activity, "md", flex.GREEN)]
    # Public card images use the UUID from the visible friend presence.
    if re.fullmatch(r"[0-9a-fA-F-]{36}", friend.get("card", "")):
        contents.append(flex.image("https://media.valorant-api.com/playercards/" + friend["card"] + "/wideart.png",
                                   aspectRatio="3:1"))
    return flex.bubble("好友進入特戰英豪", contents)


def command(vault, text):
    if text in {"好友提醒開啟", "好友提醒關閉"}:
        with vault.lock("friend_preferences"):
            vault.write("friend_preferences", {"enabled": text == "好友提醒開啟"})
        detail = "已開啟。先建立好友快照，之後偵測進入 VALORANT 時推播。" if enabled(vault) else "已關閉好友上線推播與聊天連線。"
        return flex.messages([flex.notice(text, detail)])
    state = vault.read("friends")
    if text == "好友":
        if state.get("status") != "connected" or time.time() - state.get("updated_at", 0) > 120:
            return flex.messages([flex.notice("好友", "監聽未連線或快照已過期；可輸入「好友提醒」查看狀態。")])
        online = state.get("online") or []
        if len(online) > 12:
            return flex.messages([flex.notice("在線好友", f"目前 {len(online)} 位，以下顯示前 12 位。"),
                                  flex.carousel([card(x) for x in online[:12]])])
        return flex.messages([flex.carousel([card(x) for x in online]) if online
                              else flex.notice("好友", "目前沒有偵測到好友在線上玩 VALORANT。")])
    buttons = [flex.box([flex.text(label, "sm")], paddingAll="12px", backgroundColor=flex.PANEL,
                        action={"type": "message", "label": label, "text": label})
               for label in ("好友提醒開啟", "好友提醒關閉")]
    status = {"connected": "已連線", "connecting": "連線中", "error": "連線失敗，正在重試", "disabled": "已關閉"}
    return flex.messages([flex.bubble("好友提醒", [flex.text("提醒 " + ("開啟" if enabled(vault) else "關閉")),
                         flex.text(status.get(state.get("status"), "等待監聽啟動"), "sm", flex.MUTED),
                         flex.text(state.get("error_detail") or "好友進入 VALORANT 時通知", "xs", flex.MUTED),
                         flex.text("首次連線／重連先建立快照。每位好友每 10 分鐘最多提醒一次。", "xs", flex.MUTED),
                         flex.text("監聽使用 Riot 聊天連線，可能使你的 Riot 帳號顯示在線。", "xs", flex.MUTED),
                         *buttons])])


def notify(config, vault, alert, now, stop):
    from linebot.v3.messaging.exceptions import ApiException
    with vault.lock("friend_alerts"):
        sent = vault.read("friend_alerts")
        previous = sent.get(alert["jid"], {})
        if now - previous.get("at", 0) < 600 or not enabled(vault):
            return False
        retry_key = str(uuid.uuid4())
        # Record before delivery to bound duplicate notifications across process restarts.
        sent[alert["jid"]] = {"at": now, "delivered": False}
        vault.write("friend_alerts", sent)
        for attempt in range(3):
            if stop.is_set() or not enabled(vault):
                return False
            try:
                LineClient(config["line_access_token"]).push(config["line_user_id"],
                    flex.messages([card(alert)], "好友進入 VALORANT"), retry_key)
            except Exception as exc:
                headers = {str(k).lower(): v for k, v in (getattr(exc, "headers", None) or {}).items()}
                accepted = isinstance(exc, ApiException) and exc.status == 409 \
                    and headers.get("x-line-accepted-request-id")
                if not accepted:
                    log.warning("Friend alert delivery failed (%s)", type(exc).__name__)
                    if attempt < 2:
                        stop.wait(2)
                        continue
                    return False
            sent[alert["jid"]]["delivered"] = True
            vault.write("friend_alerts", sent)
            return True


def worker(config, vault, stop):
    while not stop.is_set():
        if not enabled(vault):
            vault.write("friends", {"status": "disabled", "updated_at": time.time(), "online": []})
            stop.wait(5)
            continue
        chat = None
        try:
            vault.write("friends", {"status": "connecting", "updated_at": time.time(), "online": []})
            with httpx.Client(timeout=15) as http:
                creds = credentials(vault, http)
            if config.get("riot_puuid") and config["riot_puuid"] != creds["puuid"]:
                raise ChatError("登入帳號不符")
            chat = RiotChat(creds, stop)
            roster = chat.connect()
            tracker = PresenceTracker(roster, time.time())
            last_heartbeat = last_snapshot = 0
            while not stop.is_set() and enabled(vault):
                now = time.time()
                if creds["expires_at"] <= now + 120:
                    break
                stanza = chat.read(seconds=2)
                if stanza is not None:
                    if local_tag(stanza.tag) == "iq":
                        tracker.apply_roster(stanza)
                        if stanza.get("type") == "set" or (stanza.get("type") == "get"
                                                           and child(stanza, "ping") is not None):
                            from xml.etree import ElementTree as ET
                            chat.send(ET.Element("iq", {"type": "result", "id": stanza.get("id", ""),
                                                        "to": stanza.get("from", creds["domain"])}))
                    elif local_tag(stanza.tag) == "presence":
                        alert = tracker.apply(stanza, now)
                        if alert:
                            notify(config, vault, alert, now, stop)
                    elif local_tag(stanza.tag) in {"error", "failure"}:
                        raise ChatError("聊天伺服器拒絕連線")
                if now - last_snapshot >= 5:
                    vault.write("friends", {"status": "connected", "updated_at": now, "online": tracker.online()})
                    last_snapshot = now
                if now - last_heartbeat >= 60:
                    chat.heartbeat()
                    last_heartbeat = now
        except Exception as exc:
            detail = str(exc) if isinstance(exc, (ChatError, AuthError)) else type(exc).__name__
            log.warning("Friend monitor failed (%s)", detail)
            vault.write("friends", {"status": "error", "updated_at": time.time(), "online": [],
                                    "error_type": type(exc).__name__, "error_detail": detail})
        finally:
            if chat:
                chat.close()
        stop.wait(30)
