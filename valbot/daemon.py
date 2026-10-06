"""Supervise Bot + Quick Tunnel; Linux service or Windows foreground launcher."""
import logging
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import sys
import threading
import time

import httpx

from .line import LineClient
from .storage import ROOT, data_dir, load_config

log = logging.getLogger("valbot.service")
TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com\b")


def wait_health(url, stop, seconds=90):
    deadline = time.monotonic() + seconds
    with httpx.Client(timeout=5, follow_redirects=False) as client:
        while not stop.is_set() and time.monotonic() < deadline:
            try:
                response = client.get(url)
                if response.status_code == 200 and response.json().get("status") == "ok":
                    return
            except (httpx.HTTPError, ValueError, AttributeError):
                pass
            stop.wait(2)
    raise RuntimeError("服務健康檢查未通過。")


def sync_webhook(base, token, stop):
    if not TUNNEL_URL.fullmatch(base):
        raise ValueError("不是有效的 Quick Tunnel 網址。")
    wait_health(base + "/health", stop)
    if stop.is_set():
        return
    active = LineClient(token).configure_webhook(base + "/webhook")
    log.info("Webhook verified and updated: %s/webhook", base)
    if not active:
        log.warning("Enable Use webhook in LINE Developers Console to receive commands.")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config()
    binary = Path(os.environ.get("VALBOT_CLOUDFLARED", data_dir() / ("cloudflared.exe" if os.name == "nt" else "cloudflared"))).resolve()
    if not binary.is_file() or not os.access(binary, os.X_OK):
        log.error("cloudflared is missing or not executable: %s", binary)
        return 1
    stop = threading.Event()
    events = queue.Queue()
    children = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    try:
        bot = subprocess.Popen([sys.executable, "-m", "uvicorn", "valbot.app:app", "--host", "127.0.0.1",
                                "--port", "8000"], cwd=ROOT)
        children.append(bot)
        wait_health("http://127.0.0.1:8000/health", stop, seconds=30)
        if bot.poll() is not None:
            raise RuntimeError("Bot 未成功啟動，請確認 8000 埠沒有其他程序占用。")
        if stop.is_set():
            return 0
        tunnel = subprocess.Popen([str(binary), "tunnel", "--no-autoupdate", "--protocol", "http2",
                                   "--url", "http://127.0.0.1:8000"], cwd=ROOT,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                  encoding="utf-8", errors="replace")
        children.append(tunnel)

        def read_logs():
            for line in tunnel.stdout:
                match = TUNNEL_URL.search(line)
                if match:
                    events.put(("url", match.group()))
                elif " ERR " in line:
                    log.warning("cloudflared reported a connection error; attempting to reconnect.")

        def configure(base):
            try:
                sync_webhook(base, config["line_access_token"], stop)
                events.put(("ready", base))
            except Exception as exc:
                # Never log request headers, tokens, or LINE response bodies.
                log.error("Webhook setup failed (%s)", type(exc).__name__)
                events.put(("failed", None))

        threading.Thread(target=read_logs, daemon=True).start()
        url = None
        deadline = time.monotonic() + 180
        ready = False
        while not stop.is_set():
            if any(child.poll() is not None for child in children):
                raise RuntimeError("Bot 或 Tunnel 已退出。")
            if not ready and time.monotonic() > deadline:
                raise RuntimeError("Tunnel／Webhook 初始化逾時。")
            try:
                kind, value = events.get(timeout=1)
            except queue.Empty:
                continue
            if kind == "url" and value != url:
                url = value
                log.info("Tunnel URL: %s", url)
                threading.Thread(target=configure, args=(url,), daemon=True).start()
            elif kind == "ready":
                ready = True
                log.info("Bot service is ready.")
            elif kind == "failed":
                raise RuntimeError("Webhook 初始化失敗；服務將重新啟動。")
        return 0
    except Exception as exc:
        log.error("Service stopped (%s)", type(exc).__name__)
        return 1
    finally:
        stop.set()
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()


if __name__ == "__main__":
    sys.exit(main())
