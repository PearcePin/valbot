"""Manual Riot message checks and encrypted local inbox. No polling/receiver thread."""
from datetime import datetime, timezone
import hashlib
import logging
import re
import time
import uuid

from . import flex, friends
from .xmpp import child

log = logging.getLogger("valbot.mailbox")
MAIL_COMMANDS = {"好友訊息", "訊息標為已看"}
MAX_MESSAGES = 200
PAGE_SIZE = 10


def handles(text):
    return text in MAIL_COMMANDS or re.fullmatch(r"訊息頁 [1-9][0-9]{0,5}", text) is not None \
        or re.fullmatch(r"回覆好友 [a-f0-9]{32}", text) is not None


def state(config, vault):
    saved = vault.read("friend_messages")
    return saved if saved.get("identity") == friends.identity(config) else {
        "identity": friends.identity(config), "messages": []}


def record(config, vault, stanza, roster):
    sender = stanza.get("from", "").split("/", 1)[0]
    body = child(stanza, "body")
    recipient = stanza.get("to", "").split("/", 1)[0].partition("@")[0]
    if stanza.get("type") not in {None, "chat", "normal"} or sender not in roster \
            or body is None or not body.text or not body.text.strip() \
            or (recipient and recipient != config.get("riot_puuid")):
        return False
    stamp = None
    delay = next((x for x in stanza if x.tag == "{urn:xmpp:delay}delay"), None)
    if delay is not None and delay.get("stamp"):
        try:
            parsed = datetime.fromisoformat(delay.get("stamp").replace("Z", "+00:00"))
            stamp = parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).timestamp()
            if not 0 <= stamp <= time.time() + 86400:
                stamp = None
        except (ValueError, OverflowError):
            pass
    remote_id = stanza.get("id")
    dedup = hashlib.sha256((sender + ":" + remote_id).encode()).hexdigest() if remote_id else None
    with vault.lock("friend_messages"):
        saved = state(config, vault)
        messages = saved.get("messages") or []
        if dedup and any(m.get("dedup") == dedup for m in messages):
            return False
        friend = roster[sender]
        messages.append({"id": uuid.uuid4().hex, "dedup": dedup, "jid": sender,
                         "name": friend["name"], "tag": friend.get("tag", ""),
                         "body": body.text[:2000], "truncated": len(body.text) > 2000,
                         "received_at": time.time(), "sent_at": stamp, "seen": False})
        saved["messages"] = messages[-MAX_MESSAGES:]
        vault.write("friend_messages", saved)
    return True


def message_card(message):
    name = message["name"] + ("#" + message["tag"] if message.get("tag") else "")
    stamp = message.get("sent_at") or message["received_at"]
    date = datetime.fromtimestamp(stamp).astimezone().strftime("%m/%d %H:%M:%S")
    label = "Riot 傳送時間" if message.get("sent_at") else "Bot 收取時間"
    rows = [flex.text(name, "lg", weight="bold"),
            flex.text("本機已標為已看" if message.get("seen") else "尚未標為已看", "xs", flex.MUTED if message.get("seen") else flex.GREEN),
            flex.text(f"{label} · {date}", "xs", flex.MUTED), flex.text(message["body"], "sm"),
            friends.button("回覆這位好友", "回覆好友 " + message["id"])]
    if message.get("truncated"):
        rows.append(flex.text("長訊息僅保留前 2000 字", "xxs", flex.MUTED))
    return flex.bubble("收到 Riot 私訊", rows)


def render(config, vault, page=1, error=False):
    saved = state(config, vault)
    messages = list(reversed(saved.get("messages") or []))
    pages = max(1, (len(messages) + PAGE_SIZE - 1) // PAGE_SIZE)
    if not 1 <= page <= pages:
        return flex.messages([flex.notice("好友訊息", "頁碼不存在，請重新按「好友訊息」。")])
    unseen = sum(not m.get("seen") for m in messages)
    rows = [flex.text(f"保存 {len(messages)} 則 · 未標已看 {unseen} 則", "md", weight="bold"),
            flex.text("本機最多保留 200 則，只收取短暫連線期間 Riot 回傳的私訊，無法保證完整聊天歷史。", "xs", flex.MUTED)]
    if error:
        rows.append(flex.text("本次連線檢查失敗，以下只顯示先前保存的訊息。請確認 Riot 登入與網路。", "sm", flex.RED))
    elif saved.get("checked_at"):
        rows.append(flex.text("最近檢查 " + datetime.fromtimestamp(saved["checked_at"]).astimezone().strftime("%m/%d %H:%M:%S"), "xs", flex.MUTED))
    else:
        rows.append(flex.text("尚未完成手動檢查", "xs", flex.MUTED))
    rows.append(friends.button("重新檢查", "好友訊息"))
    if unseen:
        rows.append(friends.button("全部標為已看", "訊息標為已看"))
    if page > 1:
        rows.append(friends.button("上一頁", f"訊息頁 {page - 1}"))
    if page < pages:
        rows.append(friends.button("下一頁", f"訊息頁 {page + 1}"))
    selected = messages[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    cards = [message_card(m) for m in selected]
    if not cards:
        rows.append(flex.text("目前沒有收取到私訊；這不代表朋友從未傳訊息給你。", "sm", flex.MUTED))
    return flex.messages([flex.bubble(f"好友訊息 · 第 {page}/{pages} 頁", rows),
                          *[flex.carousel(cards[i:i + 5]) for i in range(0, len(cards), 5)]], "Valorant · 好友訊息")


def command(config, vault, text):
    if text == "好友訊息":
        error = False
        try:
            friends.query(config, vault)
            with vault.lock("friend_messages"):
                saved = state(config, vault)
                saved["checked_at"] = time.time()
                vault.write("friend_messages", saved)
        except Exception as exc:
            log.warning("Manual message check failed (%s)", type(exc).__name__)
            error = True
        return render(config, vault, error=error)
    if text == "訊息標為已看":
        with vault.lock("friend_messages"):
            saved = state(config, vault)
            for message in saved.get("messages") or []:
                message["seen"] = True
            vault.write("friend_messages", saved)
        return render(config, vault)
    if text.startswith("訊息頁 "):
        return render(config, vault, int(text.split()[1]))
    if text.startswith("回覆好友 "):
        message = next((m for m in state(config, vault).get("messages", []) if m["id"] == text.split()[1]), None)
        if message:
            snapshot = friends.query(config, vault)
            friend = next((f for f in snapshot["friends"] if f["jid"] == message["jid"]), None)
            if friend:
                return friends.command(config, vault, "私訊選擇 " + friend["key"])
        return flex.messages([flex.notice("無法回覆", "訊息已不在本機紀錄中，或對方不再是目前帳號的好友。")])
    return render(config, vault)
