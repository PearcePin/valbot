"""Android API: same real game/friend logic, no LINE or external server required."""
import base64
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import time

import httpx

from .storage import Vault
from .auth import RiotAuth, AuthError, token_from_url
from .riot import RiotClient, SHARDS
from .service import BotService, is_match_command
from . import friends, mailbox, flex

_vault = None


class AndroidCipher:
    def __init__(self, native):
        self.native = native

    def encrypt(self, raw):
        return str(self.native.encrypt(base64.b64encode(raw).decode())).encode()

    def decrypt(self, raw):
        try:
            return base64.b64decode(str(self.native.decrypt(raw.decode())))
        except Exception as exc:
            raise ValueError("Android Keystore 無法解密資料") from exc


def initialize(directory, native_cipher):
    global _vault
    os.environ["VALBOT_DATA_DIR"] = str(directory)
    _vault = Vault(Path(str(directory)), cipher=AndroidCipher(native_cipher))
    return True


def config():
    settings = _vault.read("config")
    if not settings:
        settings = {"region": "ap", "line_user_id": "android-local"}
    return settings


def status():
    settings = config()
    session = _vault.read("session")
    return {"logged_in": bool(session), "region": settings["region"],
            "expires_at": session.get("expires_at", 0),
            "refresh_available": bool(session.get("cookies")),
            "account": (session.get("puuid") or "")[:8],
            "saved_messages": len(mailbox.state(settings, _vault).get("messages", []))}


def browser_cookies():
    # Native-only synchronization of rotated cookies; not exposed through dispatch/JS.
    return json.dumps(_vault.read("session").get("cookies") or [])


def login(uri, cookie_header, region):
    if region not in SHARDS:
        raise ValueError("請選擇有效區域")
    token_from_url(uri)
    cookies = SimpleCookie()
    cookies.load(cookie_header or "")
    auth = RiotAuth(_vault)
    # Work transactionally: keep a previous valid session until verification succeeds.
    with _vault.lock("auth"):
        with auth.client() as client:
            for name, morsel in cookies.items():
                client.cookies.set(name, morsel.value, domain="auth.riotgames.com", path="/")
            session = auth.finish(client, uri)
        _vault.write("config", {"region": region, "line_user_id": "android-local", "riot_puuid": session["puuid"]})
    return status()


def run_command(command):
    settings = config()
    if not _vault.read("session"):
        raise AuthError("請先在 App 內完成 Riot 登入")
    if mailbox.handles(command):
        return mailbox.command(settings, _vault, command)
    if friends.handles(settings, _vault, command) and not is_match_command(command) and command not in {"商店", "夜市", "配件", "錢包", "牌位", "精選組合包"}:
        return friends.command(settings, _vault, command)
    if command == "精選組合包":
        with httpx.Client(timeout=15) as http:
            service = BotService(RiotClient(settings, RiotAuth(_vault), http))
            return flex.messages([service.bundles(service.riot.storefront())], "精選組合包")
    if not (command in {"商店", "夜市", "配件", "錢包", "牌位"} or is_match_command(command)):
        raise ValueError("未知功能")
    with httpx.Client(timeout=15) as http:
        return BotService(RiotClient(settings, RiotAuth(_vault), http)).command(command)


def daily():
    settings = config()
    with httpx.Client(timeout=20) as http:
        messages = BotService(RiotClient(settings, RiotAuth(_vault), http)).daily()
    with _vault.lock("auth"):
        if config().get("riot_puuid") != settings.get("riot_puuid") or not _vault.read("session"):
            raise AuthError("帳號已變更")
        _vault.write("mobile_daily", {"date": time.strftime("%Y-%m-%d"), "messages": messages})
    return messages


def daily_lines(messages):
    lines = []
    for message in messages:
        container = message.get("contents") or {}
        cards = container.get("contents", []) if container.get("type") == "carousel" else [container]
        for card in cards:
            header = (card.get("header") or {}).get("contents") or []
            body = (card.get("body") or {}).get("contents") or []
            if len(header) > 1 and body and body[0].get("text"):
                lines.append(header[1].get("text", "商店") + " · " + body[0]["text"])
    return lines


def dispatch(action, payload="{}"):
    try:
        data = json.loads(payload)
        if action == "status":
            result = status()
        elif action == "login":
            result = login(data["uri"], data.get("cookies", ""), data.get("region", "ap"))
        elif action == "command":
            result = {"messages": run_command(data["command"])}
            draft = friends.current_draft(config(), _vault)
            result["compose"] = {"status": draft.get("status"), "name": friends.display_name(draft["friend"]) if draft.get("friend") else ""}
        elif action == "daily":
            messages = daily()
            result = {"messages": messages, "summary": daily_lines(messages)}
        elif action == "region":
            if data.get("region") not in SHARDS:
                raise ValueError("區域不正確")
            settings = config()
            settings["region"] = data["region"]
            _vault.write("config", settings)
            result = status()
        elif action == "logout":
            with _vault.lock("auth"):
                for name in ("session", "config", "friend_dm", "friend_messages", "friend_snapshot", "mobile_daily"):
                    _vault.write(name, {})
            result = status()
        else:
            raise ValueError("未知操作")
        return json.dumps({"ok": True, "data": result}, ensure_ascii=False)
    except AuthError:
        return json.dumps({"ok": False, "auth_required": True,
                           "error": "Riot 需要重新驗證。按登入即可在網頁完成驗證，不必複製 Cookie。"}, ensure_ascii=False)
    except Exception as exc:
        from .riot import DataError
        detail = str(exc) if isinstance(exc, (ValueError, DataError)) else "連線或資料服務暫時無法完成，請稍後重試。"
        return json.dumps({"ok": False, "error": detail}, ensure_ascii=False)
