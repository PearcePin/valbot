"""Interactive configuration wizard (not a setuptools package installer)."""
import argparse
import os
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
from valbot.auth import RiotAuth, AuthError, LOGIN_URL, token_from_url
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
    parser.add_argument("--login-method", choices=["local", "browser", "password"],
                        help="指定登入方式；Windows 推薦 local，不需 ssid 或貼網址")
    parser.add_argument("--check-browser-url", action="store_true", help="只診斷瀏覽器網址與 Riot token，不改設定")
    args = parser.parse_args()
    print("Valorant LINE Bot · 設定精靈 v2（支援網址診斷；密碼不會保存）")
    vault = Vault()
    if args.schedule_only:
        if not vault.read("config"):
            raise RuntimeError("請先完成設定。")
        print(register_schedule())
        return
    # A failed reconfiguration must not replace the live account's session.
    with tempfile.TemporaryDirectory(dir=vault.directory, prefix="setup-") as stage:
        if args.check_browser_url:
            return check_browser_url(Vault(Path(stage)))
        return configure(vault, Vault(Path(stage)), args)


def check_browser_url(staged_vault):
    print("瀏覽器顯示 404 不影響這個檢查；程式只解析 token，不會開啟貼上的網頁。")
    uri = required("貼上含 access_token 的完整網址（隱藏輸入）：", secret=True)
    token_from_url(uri)
    print("網址解析成功：找到 access_token；接著向 Riot 驗證。")
    try:
        RiotAuth(staged_vault).import_browser(uri)
    except httpx.HTTPError as exc:
        raise AuthError(f"連線 Riot 驗證介面失敗（{type(exc).__name__}）；請確認網路與主機時間。") from exc
    print("Riot 帳號驗證與遊戲授權成功。未修改正式設定、未傳送 LINE 訊息。")
    print("請重新執行 setup.py --login-method browser，選 2 網址模式；長期排程仍需 ssid。")
    return 0


def configure(vault, staged_vault, args):
    region = input("區域 [AP/NA/EU/KR/BR/LATAM]（預設 AP）：").strip().lower() or "ap"
    while region not in SHARDS:
        region = required("請選擇 AP/NA/EU/KR/BR/LATAM：").lower()
    auth = RiotAuth(staged_vault)
    default = "3" if os.name == "nt" else "2"
    mode = {"local": "3", "browser": "2", "password": "1"}.get(args.login_method)
    while mode not in {"1", "2", "3"}:
        mode = input("登入方式 [1 帳密 / 2 瀏覽器 / 3 已登入的 Riot Client（Windows 推薦）]"
                     f"（預設 {default}）：").strip() or default
    if mode == "3":
        print("請先開啟 Riot Client，登入自己的帳號並啟動 VALORANT 到主選單。")
        print("此模式自動讀取本機登入，不需要輸入密碼、ssid 或網址。每日推播時 Riot Client 也需保持登入並開啟。")
        while True:
            try:
                auth.import_local()
                print("已讀取本機 Riot Client 登入。")
                break
            except AuthError as exc:
                print(str(exc))
                choice = input("開啟並登入後按 Enter 重試；輸入 2 改用瀏覽器；輸入 q 離開：").strip().lower()
                if choice == "q":
                    return 1
                if choice == "2":
                    mode = "2"
                    break
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
        print("瀏覽器登入：完成 Riot 登入與 2FA。ssid 能否自動更新，須以 Riot 實際驗證結果為準。")
        print(LOGIN_URL)
        webbrowser.open(LOGIN_URL)
        browser_method = input("[1 ssid / 2 access_token 網址 / 3 Riot 完整 Cookie（ssid 失敗時）]（預設 1）：").strip() or "1"
        if browser_method == "1":
            print("1. 在剛開啟的瀏覽器完成 Riot 登入與 2FA。")
            input("完成登入後按 Enter，我會開啟 Cookie 檢視用的網頁：")
            webbrowser.open("https://auth.riotgames.com/")
            print("2. 在這個 auth.riotgames.com 分頁按 F12（或 Ctrl+Shift+I）；顯示 404 也沒關係。")
            print("3. Chrome/Edge：選 Application（應用程式，若沒看到按上方 >>）。")
            print("   左側 Storage（儲存空間）→ Cookies → https://auth.riotgames.com。")
            print("   Firefox：選 Storage（儲存空間）→ Cookies → https://auth.riotgames.com。")
            print("4. 找 Name 為 ssid 的那一列；雙擊 Value（值）欄位，複製完整值。")
            print("   不是 Wi-Fi 的 SSID，不要複製 Name、整列或其他網站的 Cookie。")
            print("   找不到 ssid：確認登入與檢視 Cookie 使用同一個瀏覽器／設定檔，且已完成 2FA。")
            print("詳細步驟見 docs/login.md。ssid 等同登入憑證，請勿貼到聊天或 GitHub。")
            while True:
                ssid = required("貼上 ssid 的 Value（隱藏輸入；q 離開）：", secret=True).strip()
                if ssid.lower() == "q":
                    return 1
                try:
                    auth.import_ssid(ssid)
                    break
                except (AuthError, httpx.HTTPError) as exc:
                    print(str(exc) if isinstance(exc, AuthError) else "Riot 連線失敗，請稍後重試。")
                    choice = input("Enter 重貼 ssid；2 改貼登入網址；3 改用完整 Cookie；q 離開：").strip().lower()
                    if choice == "q":
                        return 1
                    if choice in {"2", "3"}:
                        browser_method = choice
                        break
        if browser_method == "3":
            print("在已登入的瀏覽器按 F12 → Network（網路）→ 勾 Preserve log（保留紀錄）。")
            print("重新開啟上方登入連結，找到 Request URL 為 https://auth.riotgames.com/authorize 的請求。")
            print("在 Headers → Request Headers 中，複製 Cookie 欄位的整個值（應含 ssid=...）。")
            print("只複製這個 Riot 網域的 Cookie 欄位，不要複製所有標頭或其他網站的 Cookie。")
            print("詳見 docs/login.md；內容是登入憑證，只貼入本機精靈。")
            while True:
                cookie_header = required("Riot Cookie 欄位值（隱藏輸入；q 離開）：", secret=True)
                if cookie_header.strip().lower() == "q":
                    return 1
                try:
                    auth.import_cookie_header(cookie_header)
                    print("完整 Cookie 自動更新測試成功。")
                    break
                except (AuthError, httpx.HTTPError) as exc:
                    print(str(exc) if isinstance(exc, AuthError) else "Cookie 更新測試連線失敗。")
                    choice = input("Enter 重新貼完整 Cookie；2 改用網址暫時測試；q 離開：").strip().lower()
                    if choice == "q":
                        return 1
                    if choice == "2":
                        browser_method = "2"
                        break
        if browser_method == "2":
            print("登入後的網頁顯示 404 沒關係；只要網址含有效的 access_token 就能驗證。")
            print("帳號管理頁／一般首頁不是登入憑證。完整網址需包含 #access_token=...。")
            print("例如：https://playvalorant.com/opt_in#access_token=...&id_token=...&expires_in=3600")
            print("網址會先驗證成功再詢問 ssid；格式有誤可原地重試。")
            while True:
                uri = required("登入完成網址（隱藏輸入；q 離開）：", secret=True).strip()
                if uri.lower() == "q":
                    return 1
                try:
                    auth.import_browser(uri)
                    break
                except (AuthError, httpx.HTTPError) as exc:
                    print(str(exc) if isinstance(exc, AuthError) else "Riot 連線失敗，請稍後重試。")
            print("網址模式憑證通常僅約一小時有效；每日排程需 ssid 或 Windows Riot Client 模式。")
            ssid = getpass("ssid 的 Value（可空白；取得步驟見 docs/login.md）：").strip()
            while ssid:
                original = staged_vault.read("session")
                try:
                    updated = auth.import_ssid(ssid)
                    if original["puuid"] != updated["puuid"]:
                        staged_vault.write("session", original)
                        raise AuthError("網址與 ssid 屬於不同 Riot 帳號；已保留網址登入，請使用同一個帳號的 ssid。")
                    print("Cookie 自動更新測試成功。")
                    break
                except (AuthError, httpx.HTTPError) as exc:
                    print(str(exc) if isinstance(exc, AuthError) else "Cookie 更新測試連線失敗。")
                    print("已保留成功的網址登入。可重新貼 ssid，或按 Enter 留空以暫時測試。")
                    ssid = getpass("重新貼 ssid（Enter 略過）：").strip()
            if not ssid:
                print("目前只有短效網址 token，沒有驗證成功的 Cookie；過期後須手動登入，不能保證每日排程。")
        elif browser_method not in {"1", "3"}:
            raise AuthError("請選擇 1（ssid）、2（網址）或 3（完整 Cookie）。")
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
                         "bundles", "maps", "agents", "competitivetiers"):
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
