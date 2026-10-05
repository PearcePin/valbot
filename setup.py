"""Interactive configuration wizard (not a setuptools package installer)."""
import argparse
from datetime import datetime
from getpass import getpass
import re
import subprocess
import tempfile
import webbrowser
from pathlib import Path

import httpx
from linebot.v3.messaging.exceptions import ApiException

from valbot import flex
from valbot.auth import RiotAuth, AuthError, LOGIN_URL
from valbot.line import LineClient
from valbot.riot import RiotClient, SHARDS
from valbot.schedule import register_schedule
from valbot.storage import Vault


def required(prompt, secret=False):
    while True:
        value = getpass(prompt) if secret else input(prompt).strip()
        if value:
            return value
        print("不可留空。")


def main():
    parser = argparse.ArgumentParser(description="Valorant LINE Bot 設定精靈")
    parser.add_argument("--no-schedule", action="store_true")
    parser.add_argument("--schedule-only", action="store_true")
    parser.add_argument("--legacy-auth", action="store_true", help="舊版 Riot 帳密驗證協定（相容用途）")
    args = parser.parse_args()
    print("Valorant LINE Bot · 設定精靈（密碼不會保存）")
    vault = Vault()
    if args.schedule_only:
        if not vault.read("config"):
            raise RuntimeError("請先完成設定。")
        print(register_schedule())
        return
    # A failed reconfiguration must not replace the live account's session.
    with tempfile.TemporaryDirectory(dir=vault.directory, prefix="setup-") as stage:
        return configure(vault, Vault(Path(stage)), args)


def configure(vault, staged_vault, args):
    region = input("區域 [AP/NA/EU/KR/BR/LATAM]（預設 AP）：").strip().lower() or "ap"
    while region not in SHARDS:
        region = required("請選擇 AP/NA/EU/KR/BR/LATAM：").lower()
    auth = RiotAuth(staged_vault)
    mode = input("登入方式 [1 帳密 / 2 瀏覽器]（預設 1）：").strip() or "1"
    if mode == "1":
        username = required("Riot 登入帳號（不是顯示名稱）：")
        password = required("Riot 密碼：", secret=True)
        try:
            auth.login(username, password, lambda: required("Riot 2FA 驗證碼：", secret=True),
                       legacy=args.legacy_auth)
        except (AuthError, httpx.HTTPError) as exc:
            print(str(exc) if isinstance(exc, AuthError) else "Riot 登入網路失敗。")
            mode = "2"
        finally:
            del password
    if mode == "2":
        print("請在瀏覽器完成 Riot 登入與 2FA，然後複製跳轉後的完整網址（含 #access_token）。")
        print(LOGIN_URL)
        webbrowser.open(LOGIN_URL)
        uri = required("登入完成網址（隱藏輸入）：", secret=True)
        print("若要無人值守更新：從 auth.riotgames.com 的瀏覽器 Cookie 複製 ssid；它等同登入憑證。")
        ssid = getpass("ssid（隱藏輸入，可空白；空白時約一小時後需重新登入）：").strip()
        auth.import_browser(uri, ssid)
        if ssid:
            auth.session(force=True)
    elif mode != "1":
        raise RuntimeError("不支援的登入方式。")
    config = {"region": region, "line_access_token": required("LINE Channel Access Token：", secret=True),
              "line_channel_secret": required("LINE Channel Secret（Webhook 簽章驗證必要）：", secret=True),
              "line_user_id": required("LINE User ID（U 開頭）：")}
    config["riot_puuid"] = staged_vault.read("session")["puuid"]
    if not re.fullmatch(r"U[0-9a-fA-F]{32}", config["line_user_id"]):
        raise RuntimeError("LINE User ID 格式錯誤。")
    print("測試 Riot 商店、LINE Token 與收件人...")
    with httpx.Client(timeout=20) as client:
        riot = RiotClient(config, auth, client)
        store = riot.storefront()
        if "SkinsPanelLayout" not in store:
            raise RuntimeError("Riot 回應未含商店；請確認區域與帳號。")
        # Prewarm public assets to reduce webhook reply latency on first query.
        for endpoint in ("weapons/skins", "buddies", "playercards", "sprays", "playertitles", "currencies",
                         "bundles", "maps", "agents", "competitivetiers", "missions", "contracts"):
            riot.assets.get(endpoint)
    line = LineClient(config["line_access_token"])
    line.validate_token()
    line.validate_user(config["line_user_id"])
    import uuid
    line.push(config["line_user_id"], flex.messages([flex.menu()], "Valorant 設定完成"), str(uuid.uuid4()))
    with vault.lock("auth"):
        vault.write("config", config)
        vault.write("session", staged_vault.read("session"))
    print("登入與 LINE 推播測試完成，設定已加密保存。")
    print("每日 08:05 依主機本地時區，現在：", datetime.now().astimezone().isoformat())
    if not args.no_schedule:
        try:
            print(register_schedule())
        except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
            print(f"排程建立失敗（{type(exc).__name__}），設定已保留。修正後執行 setup.py --schedule-only。")
            return 1
    print("啟動 Webhook：python -m uvicorn valbot.app:app --host 127.0.0.1 --port 8000")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        print("\n設定已中止。")
        raise SystemExit(1)
    except ApiException as exc:
        print(f"LINE 驗證失敗（HTTP {exc.status}），請確認 Token、User ID、好友狀態與額度。")
        raise SystemExit(1)
    except Exception as exc:
        # Avoid printing httpx URLs or LINE bodies containing private data.
        print(str(exc) if isinstance(exc, (AuthError, RuntimeError)) else f"設定失敗（{type(exc).__name__}）。")
        raise SystemExit(1)
