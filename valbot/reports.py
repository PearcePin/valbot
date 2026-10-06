"""Persistent, owner-only post-match reports with LINE retry-key deduplication."""
import logging
import time
import uuid

import httpx

from . import flex
from .auth import RiotAuth
from .line import LineClient
from .riot import RiotClient

log = logging.getLogger("valbot.reports")
REPORT_COMMANDS = {"自動戰報", "自動戰報開啟", "自動戰報關閉"}


def enabled(vault):
    return vault.read("report_preferences").get("enabled", True)


def command(vault, text):
    if text in {"自動戰報開啟", "自動戰報關閉"}:
        with vault.lock("report_state"):
            desired = text == "自動戰報開啟"
            if desired != enabled(vault):
                # Toggling starts a new baseline; don't report games played while disabled.
                vault.write("report_state", {})
            vault.write("report_preferences", {"enabled": desired})
    state = vault.read("report_state")
    status = {"ready": "正在偵測新對戰", "error": "查詢或推播失敗，稍後重試", "disabled": "已關閉"}
    detail = status.get(state.get("status"), "等待建立對戰紀錄")
    if state.get("updated_at") and time.time() - state["updated_at"] > 180:
        detail = "監聽狀態已過期；請確認主機服務正在執行"
    return flex.messages([flex.bubble("自動戰報", [
        flex.text("賽後推播 " + ("開啟" if enabled(vault) else "關閉"), "lg", weight="bold"),
        flex.text(detail, "sm", flex.MUTED),
        flex.text("每 60 秒檢查一次，Riot 公布完整結算後推播。首次啟動／重新開啟先建立紀錄，舊對戰不推送。", "xs", flex.MUTED),
        *[flex.box([flex.text(label, "sm")], paddingAll="12px", backgroundColor=flex.PANEL,
                   action={"type": "message", "label": label, "text": label})
          for label in ("自動戰報開啟", "自動戰報關閉")]])])


def accepted_retry(exc):
    from linebot.v3.messaging.exceptions import ApiException
    headers = {str(k).lower(): v for k, v in (getattr(exc, "headers", None) or {}).items()}
    return isinstance(exc, ApiException) and exc.status == 409 and bool(headers.get("x-line-accepted-request-id"))


def poll(config, vault, riot, line, now=None):
    now = time.time() if now is None else now
    # A single lock prevents toggles and another worker racing with delivery/checkpoint.
    with vault.lock("report_state"):
        if not enabled(vault):
            vault.write("report_state", {"status": "disabled", "updated_at": now})
            return
        state = vault.read("report_state")
        identity = riot.puuid + ":" + config["line_user_id"]
        history = riot.match_history(100)
        ids = list(dict.fromkeys(x["MatchID"] for x in history if x.get("MatchID")))
        if state.get("identity") != identity:
            vault.write("report_state", {"identity": identity, "seen": ids, "pending": {},
                                          "status": "ready", "updated_at": now})
            return
        seen = state.get("seen") or []
        pending = state.get("pending") or {}
        # Keep retries even if a match has rolled out of history. Oldest new game goes first.
        queue = list(pending) + [mid for mid in reversed(ids) if mid not in seen and mid not in pending]
        # Bound catch-up work per poll so status/toggle commands can acquire the lock promptly.
        for mid in queue[:3]:
            job = pending.get(mid)
            if job is None:
                match = riot.match_detail(mid)
                if not (match.get("matchInfo") or {}).get("isCompleted"):
                    continue
                # Persist exact payload/key before delivery, so restart retries the same request.
                update = None
                if (match.get("matchInfo") or {}).get("queueID") == "competitive":
                    try:
                        update = next((x for x in riot.competitive_updates(10) if x.get("MatchID") == mid), None)
                    except Exception:
                        pass  # An optional RR outage must not block the completed match report.
                messages = flex.messages([flex.menu(), flex.match_card(match, riot.puuid, riot.assets, "自動戰報", rr_update=update)], "Valorant · 賽後戰報")
                job = {"key": str(uuid.uuid4()), "messages": messages, "created_at": now}
                pending[mid] = job
                state.update(pending=pending, status="ready", updated_at=now)
                vault.write("report_state", state)
            # LINE retains retry keys for 24h; don't risk a duplicate after an ambiguous old delivery.
            if now - job["created_at"] < 23 * 3600:
                try:
                    line.push(config["line_user_id"], job["messages"], job["key"])
                except Exception as exc:
                    if not accepted_retry(exc):
                        raise
            else:
                log.warning("Expired report retry skipped to avoid duplicate delivery")
            seen.append(mid)
            pending.pop(mid, None)
            state.update(seen=seen[-200:], pending=pending, status="ready", updated_at=now)
            vault.write("report_state", state)
        state.update(seen=seen[-200:], pending=pending, status="ready", updated_at=now)
        vault.write("report_state", state)


def worker(config, vault, stop):
    while not stop.is_set():
        try:
            if enabled(vault):
                with httpx.Client(timeout=12) as http:
                    poll(config, vault, RiotClient(config, RiotAuth(vault), http),
                         LineClient(config["line_access_token"]))
            else:
                with vault.lock("report_state"):
                    vault.write("report_state", {"status": "disabled", "updated_at": time.time()})
        except Exception as exc:
            log.warning("Post-match monitor failed (%s)", type(exc).__name__)
            with vault.lock("report_state"):
                state = vault.read("report_state")
                state.update(status="error", updated_at=time.time())
                vault.write("report_state", state)
        stop.wait(60)
