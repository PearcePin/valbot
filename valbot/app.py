from contextlib import asynccontextmanager
import json
import logging
import threading
import time

from fastapi import FastAPI, Request, HTTPException
from starlette.concurrency import run_in_threadpool
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
import httpx

from . import flex
from .auth import RiotAuth
from .line import LineClient
from .queue import Inbox
from .riot import RiotClient
from .service import BotService
from .storage import Vault
from . import friends

log = logging.getLogger("valbot")
COMMANDS = {"商店", "夜市", "配件", "錢包", "戰績", "牌位"} | friends.FRIEND_COMMANDS


def process_event(event, config, vault, line):
    # Re-check authorization in the worker, including queued events after a config change.
    source = event.get("source") or {}
    if source.get("type") != "user" or source.get("userId") != config["line_user_id"]:
        return
    if event.get("type") == "follow":
        messages = flex.messages([flex.menu()])
    elif event.get("type") == "message":
        command = (event.get("message") or {}).get("text", "").strip()
        if command not in COMMANDS:
            messages = flex.messages([flex.menu()])
        else:
            try:
                if command in friends.FRIEND_COMMANDS:
                    messages = friends.command(vault, command)
                else:
                    with httpx.Client(timeout=12) as client:
                        messages = BotService(RiotClient(config, RiotAuth(vault), client)).command(command)
            except Exception as exc:
                # Log exception types only; never tokens, response bodies or request URLs.
                log.warning("Command failed (%s)", type(exc).__name__)
                from .auth import AuthError
                detail = "登入已失效，請在主機重新執行 setup.py。" if isinstance(exc, AuthError) \
                    else "資料服務暫時無法使用，請稍後再試。"
                messages = flex.messages([flex.notice("查詢暫時無法完成", detail)])
            # Reply tokens are single-use; put the menu first in the same reply request.
            messages = flex.messages([flex.menu()], "Valorant · 指令中心") + messages
    else:
        return
    line.reply(event["replyToken"], messages)


def create_app(config=None, vault=None, line=None):
    stop = threading.Event()

    def worker(app):
        while not stop.is_set():
            try:
                job = app.state.inbox.claim()
                if not job:
                    stop.wait(0.25)
                    continue
                event_id, event = job
                try:
                    # Reply tokens are short-lived: discard stale inbox entries after a long outage.
                    if time.time() - event.get("timestamp", 0) / 1000 < 55:
                        process_event(event, app.state.config, app.state.vault, app.state.line)
                except Exception as exc:
                    log.warning("Reply failed (%s)", type(exc).__name__)
                finally:
                    app.state.inbox.finish(event_id)
            except Exception as exc:
                log.error("Inbox worker failed (%s)", type(exc).__name__)
                stop.wait(1)

    @asynccontextmanager
    async def lifespan(app):
        app.state.vault = vault or Vault()
        app.state.config = config or app.state.vault.read("config")
        if not app.state.config:
            raise RuntimeError("請先執行 setup.py。")
        app.state.line = line or LineClient(app.state.config["line_access_token"])
        app.state.parser = WebhookParser(app.state.config["line_channel_secret"])
        app.state.inbox = Inbox(app.state.vault)
        stop.clear()
        thread = threading.Thread(target=worker, args=(app,), daemon=True, name="valbot-inbox")
        thread.start()
        friend_thread = None
        if app.state.config.get("line_access_token"):
            friend_thread = threading.Thread(target=friends.worker,
                                            args=(app.state.config, app.state.vault, stop),
                                            daemon=True, name="valbot-friends")
            friend_thread.start()
        yield
        stop.set()
        await run_in_threadpool(thread.join, 2)
        if friend_thread:
            await run_in_threadpool(friend_thread.join, 2)

    app = FastAPI(title="Valorant LINE Bot", lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/webhook")
    async def webhook(request: Request):
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 256 * 1024:
                raise HTTPException(413, "Payload too large")
        try:
            body = raw.decode("utf-8")
            app.state.parser.parse(body, request.headers.get("x-line-signature", ""))
        except InvalidSignatureError:
            raise HTTPException(400, "Invalid signature") from None
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(400, "Invalid payload") from None
        for event in json.loads(body).get("events", []):
            source = event.get("source") or {}
            if source.get("type") != "user" or source.get("userId") != app.state.config["line_user_id"]:
                continue
            if event.get("type") in {"follow", "message"} and event.get("replyToken") and event.get("webhookEventId"):
                await run_in_threadpool(app.state.inbox.enqueue, event)
        return {"status": "ok"}

    return app


app = create_app()
