"""Manual friend snapshots and owner-confirmed private messages; no background worker."""
import base64
from contextlib import contextmanager
import json
import re
import threading
import time
import uuid
from xml.etree import ElementTree as ET

import httpx

from . import flex
from .xmpp import RiotChat, credentials, local_tag, child, ChatError, validate_body
from .auth import AuthError

FRIEND_COMMANDS = {"好友", "好友提醒", "偵測好友", "傳訊息", "取消私訊"}
TTL = 600
PAGE_SIZE = 8


class PresenceTracker:
    def __init__(self, roster):
        self.friends = {}
        self.resources = {}
        self.apply_roster(roster)

    def apply_roster(self, stanza):
        query = child(stanza, "query")
        if query is None or "riotgames:roster" not in query.tag:
            return
        for item in query:
            if local_tag(item.tag) != "item":
                continue
            bare = item.get("jid", "").split("/", 1)[0]
            if not re.fullmatch(r"[0-9a-fA-F-]{36}@[a-z0-9-]+\.pvp\.net", bare):
                continue
            if item.get("subscription") != "both":
                self.friends.pop(bare, None)
                self.resources.pop(bare, None)
                continue
            identity = child(item, "id")
            name = identity.get("name") if identity is not None else item.get("name")
            tag = identity.get("tagline") if identity is not None else None
            previous = self.friends.get(bare) or {}
            self.friends[bare] = {"jid": bare, "name": name or "好友 " + bare.split("@")[0][:8],
                                 "tag": tag or "", "key": previous.get("key") or uuid.uuid4().hex[:16]}

    def apply(self, stanza):
        bare, _, resource = stanza.get("from", "").partition("/")
        if bare not in self.friends or stanza.get("type") not in {None, "unavailable"}:
            return
        resources = self.resources.setdefault(bare, {})
        if stanza.get("type") == "unavailable":
            resources.pop(resource, None)
            return
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

    def snapshot(self):
        output = []
        for jid, friend in self.friends.items():
            active = next((x for x in self.resources.get(jid, {}).values() if x["online"]), {})
            output.append({**friend, **active, "online": bool(active)})
        return sorted(output, key=lambda x: (not x["online"], x["name"].casefold(), x["tag"]))


def identity(config):
    return config.get("riot_puuid", "") + ":" + config["line_user_id"]


@contextmanager
def connection(config, vault):
    with httpx.Client(timeout=8) as http:
        creds = credentials(vault, http)
    if config.get("riot_puuid") and config["riot_puuid"] != creds["puuid"]:
        raise AuthError("登入帳號不符")
    chat = RiotChat(creds, threading.Event())
    try:
        roster = chat.connect()
        from .mailbox import record
        tracker = PresenceTracker(roster)
        chat.message_handler = lambda stanza: record(config, vault, stanza, tracker.friends)
        yield chat, roster
    finally:
        chat.close()


def query(config, vault):
    with connection(config, vault) as (chat, roster):
        tracker = PresenceTracker(roster)
        from .mailbox import record
        chat.message_handler = lambda stanza: record(config, vault, stanza, tracker.friends)
        start = time.monotonic()
        # Bounded sample; never turn a user action into ongoing monitoring.
        while time.monotonic() - start < 5:
            stanza = chat.read(seconds=min(1, 5 - (time.monotonic() - start)))
            if stanza is None:
                continue
            if local_tag(stanza.tag) == "presence":
                tracker.apply(stanza)
            elif local_tag(stanza.tag) == "iq":
                tracker.apply_roster(stanza)
                if stanza.get("type") == "set" or (stanza.get("type") == "get" and child(stanza, "ping") is not None):
                    chat.send(ET.Element("iq", {"type": "result", "id": stanza.get("id", ""),
                                               "to": stanza.get("from", chat.creds["domain"])}))
            elif local_tag(stanza.tag) in {"error", "failure"}:
                raise ChatError("聊天伺服器拒絕連線")
        snapshot = {"identity": identity(config), "updated_at": time.time(), "friends": tracker.snapshot()}
        vault.write("friend_snapshot", snapshot)
        return snapshot


def button(label, command):
    return flex.box([flex.text(label, "sm")], paddingAll="12px", backgroundColor=flex.PANEL,
                    cornerRadius="8px", action={"type": "message", "label": label[:20], "text": command})


def display_name(friend):
    return friend["name"] + ("#" + friend["tag"] if friend.get("tag") else "")


def card(friend):
    activity = {"MENUS": "遊戲大廳", "PREGAME": "選角中", "INGAME": "對戰中"}.get(friend.get("activity"), "VALORANT 已上線") \
        if friend.get("online") else "本次未偵測到在 VALORANT 上線"
    contents = [flex.text(display_name(friend), "xl", weight="bold"),
                flex.text(activity, "sm", flex.GREEN if friend.get("online") else flex.MUTED)]
    if re.fullmatch(r"[0-9a-fA-F-]{36}", friend.get("card", "")):
        contents.append(flex.image("https://media.valorant-api.com/playercards/" + friend["card"] + "/wideart.png", aspectRatio="3:1"))
    contents.append(button("傳訊息給這位好友", "私訊選擇 " + friend["key"]))
    return flex.bubble("Riot 好友", contents)


def snapshot_pages(snapshot, page=1, online_only=False):
    friends = [x for x in snapshot["friends"] if x["online"]] if online_only else snapshot["friends"]
    pages = max(1, (len(friends) + PAGE_SIZE - 1) // PAGE_SIZE)
    if not 1 <= page <= pages:
        return flex.messages([flex.notice("好友列表", "頁碼不存在，請重新按「好友」。")])
    items = friends[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    label = "本次在 VALORANT 上線" if online_only else "可選擇私訊的 Riot 好友"
    stamp = time.strftime("%H:%M:%S", time.localtime(snapshot["updated_at"]))
    rows = [flex.text(f"{label} {len(friends)} 位 · 第 {page}/{pages} 頁", "sm"),
            flex.text(f"查詢時間 {stamp} · 狀態僅代表本次短暫偵測", "xs", flex.MUTED), button("重新偵測好友", "好友")]
    prefix = "在線好友頁 " if online_only else "私訊好友頁 "
    if page < pages:
        rows.append(button("下一頁", prefix + str(page + 1)))
    if page > 1:
        rows.append(button("上一頁", prefix + str(page - 1)))
    if online_only:
        rows.append(button("查看全部好友", "好友"))
    messages = [flex.bubble("好友查詢", rows)]
    if items:
        messages.append(flex.carousel([card(x) for x in items]))
    else:
        messages.append(flex.notice("好友", "目前未取得符合條件的好友；可稍後重新偵測。"))
    return flex.messages(messages)


def current_snapshot(config, vault):
    snapshot = vault.read("friend_snapshot")
    if snapshot.get("identity") != identity(config) or time.time() - snapshot.get("updated_at", 0) > TTL:
        return None
    return snapshot


def current_draft(config, vault):
    draft = vault.read("friend_dm")
    if draft.get("identity") != identity(config) or time.time() - draft.get("created_at", 0) > TTL:
        return {}
    return draft


def handles(config, vault, text):
    return text in FRIEND_COMMANDS or text.startswith(("私訊選擇 ", "確認私訊 ", "私訊好友頁 ", "在線好友頁 ")) \
        or current_draft(config, vault).get("status") == "composing"


def confirm_card(draft):
    return flex.bubble("私訊送出前確認", [flex.text("收件人 · " + display_name(draft["friend"]), "md", weight="bold"),
        flex.text(draft["body"], "sm"), flex.text("使用你的 Riot 帳號傳送遊戲私訊", "xs", flex.MUTED),
        button("確認送出", "確認私訊 " + draft["nonce"]), button("取消", "取消私訊")])


def send_draft(config, vault, text):
    with vault.lock("friend_dm"):
        draft = current_draft(config, vault)
        nonce = text.removeprefix("確認私訊 ")
        if draft.get("status") != "ready" or nonce != draft.get("nonce"):
            return flex.messages([flex.notice("私訊", "確認已失效或已處理；請重新按「好友」。")])
        # Failures before the send leave the confirmed draft available for retry.
        with connection(config, vault) as (chat, roster):
            tracker = PresenceTracker(roster)
            jid = draft["friend"]["jid"]
            if jid not in tracker.friends:
                return flex.messages([flex.notice("無法送出", "對象已不在目前帳號的互為好友名單中。")])
            # Consume nonce BEFORE network write. Never auto-resend an ambiguous message.
            draft.update(status="attempted", attempted_at=time.time())
            vault.write("friend_dm", draft)
            try:
                chat.send_message(jid, draft["body"], "valbot-" + draft["nonce"])
            except Exception:
                vault.write("friend_dm", {"identity": identity(config), "status": "unknown", "created_at": time.time()})
                return flex.messages([flex.notice("私訊送出狀態未確認", "連線中斷或 Riot 拒絕訊息；不會自動重送。請先確認好友是否收到，再決定是否重新傳送。")])
            vault.write("friend_dm", {"identity": identity(config), "status": "submitted", "created_at": time.time()})
            return flex.messages([flex.notice("私訊已提交", "已將私訊寫入 Riot 聊天連線；不代表好友已收到或已讀。")])


def command(config, vault, text):
    if text in {"好友", "好友提醒", "偵測好友", "傳訊息"}:
        with vault.lock("friend_dm"):
            vault.write("friend_dm", {})
        snapshot = query(config, vault)
        return snapshot_pages(snapshot)
    if text == "取消私訊":
        with vault.lock("friend_dm"):
            vault.write("friend_dm", {})
        return flex.messages([flex.notice("私訊已取消", "可以重新選擇好友。")])
    if text.startswith(("私訊好友頁 ", "在線好友頁 ")):
        snapshot = current_snapshot(config, vault)
        if snapshot is None:
            return flex.messages([flex.notice("好友名單已過期", "請重新按「好友」取得最新名單。")])
        try:
            page = int(text.split(" ", 1)[1])
        except ValueError:
            page = 0
        return snapshot_pages(snapshot, page, online_only=text.startswith("在線好友頁 "))
    if text.startswith("確認私訊 "):
        return send_draft(config, vault, text)
    with vault.lock("friend_dm"):
        if text.startswith("私訊選擇 "):
            snapshot = current_snapshot(config, vault)
            friend = next((x for x in (snapshot or {}).get("friends", []) if x["key"] == text.split(" ", 1)[1]), None)
            if not friend:
                return flex.messages([flex.notice("好友選擇已失效", "請重新按「好友」取得最新名單。")])
            vault.write("friend_dm", {"identity": identity(config), "friend": friend, "status": "composing", "created_at": time.time()})
            return flex.messages([flex.bubble("輸入私訊內容", [flex.text("收件人 · " + display_name(friend), "md", weight="bold"),
                                  flex.text("下一則文字會成為草稿，最多 500 字。預覽後按確認才會送出；10 分鐘內有效。", "sm", flex.MUTED),
                                  button("取消", "取消私訊")])])
        draft = current_draft(config, vault)
        if draft.get("status") == "composing":
            try:
                validate_body(text)
            except ChatError as exc:
                return flex.messages([flex.notice("訊息內容無法使用", str(exc))])
            draft.update(status="ready", body=text, nonce=uuid.uuid4().hex)
            vault.write("friend_dm", draft)
            return flex.messages([confirm_card(draft)])
    return flex.messages([flex.notice("私訊", "請先按「好友」選擇收件人。")])
