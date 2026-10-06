from __future__ import annotations

import time
import base64
import json
import os
from pathlib import Path
from http.cookies import SimpleCookie, CookieError
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

import httpx

from .storage import Vault

AUTH = "https://auth.riotgames.com"
PARAMS = {"client_id": "play-valorant-web-prod", "redirect_uri": "https://playvalorant.com/opt_in",
          "response_type": "token id_token", "scope": "account openid", "nonce": "1"}
LOGIN_URL = AUTH + "/authorize?" + urlencode(PARAMS)
CALLBACK_HOSTS = {"playvalorant.com", "www.playvalorant.com", "auth.riotgames.com",
                  "authenticate.riotgames.com", "account.riotgames.com"}
PAGE_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"


class AuthError(RuntimeError):
    pass


def json_response(response: httpx.Response, stage="Riot 登入") -> dict:
    if response.status_code >= 400:
        if response.status_code == 401:
            detail = "憑證已過期或不是有效的 access_token，請重新登入並複製最新網址。"
        elif response.status_code == 403:
            detail = "Riot 拒絕存取，可能需要額外網頁驗證或存在網路限制。"
        else:
            detail = "這是 Riot API 回應，不是瀏覽器最後那個 404 網頁；請回報此階段與狀態碼。"
        raise AuthError(f"{stage}失敗（HTTP {response.status_code}）。{detail}")
    try:
        result = response.json()
    except ValueError as exc:
        raise AuthError(f"{stage}回傳非 JSON 資料，可能需要網頁驗證；請回報此階段。") from exc
    if not isinstance(result, dict):
        raise AuthError(f"{stage}回傳格式不符，請回報此階段。")
    return result


def token_from_url(uri: str) -> dict:
    uri = uri.strip().strip('\"\'')
    # A browser/copy tool may percent-encode the whole callback URL.
    for _ in range(2):
        if uri.lower().startswith("https%"):
            uri = unquote(uri)
    try:
        parsed = urlsplit(uri)
    except ValueError as exc:
        raise AuthError("登入網址格式無法解析，請重新複製完整網址。") from exc
    if parsed.scheme != "https" or parsed.hostname not in CALLBACK_HOSTS:
        raise AuthError("請貼上 Riot／playvalorant.com 登入跳轉網址，或執行 --check-browser-url 檢查；不接受其他網站。")
    fragment = parsed.fragment.partition("?")[2] if "?" in parsed.fragment else parsed.fragment.lstrip("/?")
    fields = {**parse_qs(parsed.query), **parse_qs(fragment)}
    if not fields.get("access_token"):
        if fields.get("id_token") or fields.get("token_type"):
            raise AuthError("網址雖然包含 token 字樣，但沒有 access_token；id_token／token_type 不能當作 API 憑證。")
        raise AuthError("這個網址沒有 access_token。請用精靈開啟的連結登入，完成後立刻複製含 #access_token= 的網址；"
                        "若瀏覽器已清除該片段，請改用 ssid 或 Windows Riot Client 登入。")
    try:
        expires_in = int(fields.get("expires_in", ["3600"])[0])
        if not 0 < expires_in <= 86400:
            raise ValueError
    except ValueError as exc:
        raise AuthError("登入網址的有效時間格式錯誤，請重新複製完整網址。") from exc
    return {"access_token": fields["access_token"][0],
            "id_token": fields.get("id_token", [""])[0],
            "expires_at": time.time() + expires_in}


def local_session() -> dict:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if os.name != "nt" or not local_app_data:
        raise AuthError("Riot Client 登入僅支援 Windows；Ubuntu 請選擇瀏覽器 ssid 模式。")
    lockfile = Path(local_app_data) / "Riot Games" / "Riot Client" / "Config" / "lockfile"
    try:
        _, _, port, password, protocol = lockfile.read_text(encoding="utf-8").strip().split(":")
        if protocol != "https" or not 1 <= int(port) <= 65535:
            raise ValueError
    except (OSError, ValueError) as exc:
        raise AuthError("找不到可用的 Riot Client。請先開啟 Riot Client、登入並啟動 VALORANT 到主選單，保持開啟後重試。") from exc
    try:
        # Riot Client's self-signed TLS is allowed ONLY on this fixed loopback URL.
        # Never send the lockfile credential through system proxies or remote redirects.
        with httpx.Client(verify=False, trust_env=False, timeout=10, follow_redirects=False) as client:
            response = client.get(f"https://127.0.0.1:{port}/entitlements/v1/token", auth=("riot", password))
            result = json_response(response)
    except httpx.HTTPError as exc:
        raise AuthError("無法連線本機 Riot Client。請保持 Riot Client 與遊戲開啟，登入完成後重試。") from exc
    if not all(result.get(key) for key in ("accessToken", "token", "subject")):
        raise AuthError("Riot Client 尚未完成登入，請先進入 VALORANT 主選單再重試。")
    try:
        payload = result["accessToken"].split(".")[1]
        expiry = float(json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["exp"])
    except (ValueError, KeyError, IndexError, TypeError):
        expiry = time.time() + 300
    if expiry <= time.time():
        raise AuthError("Riot Client 憑證已過期，請在 Riot Client 重新登入後重試。")
    return {"access_token": result["accessToken"], "entitlements_token": result["token"],
            "puuid": result["subject"], "expires_at": expiry, "source": "local", "cookies": []}


class RiotAuth:
    def __init__(self, vault: Vault):
        self.vault = vault

    @staticmethod
    def client(cookies=()) -> httpx.Client:
        client = httpx.Client(timeout=20, follow_redirects=False,
                              headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        for cookie in cookies:
            if cookie["domain"].lstrip(".") == "auth.riotgames.com":
                client.cookies.set(cookie["name"], cookie["value"],
                                   domain=cookie["domain"], path=cookie.get("path", "/"))
        return client

    def finish(self, client: httpx.Client, uri: str) -> dict:
        session = token_from_url(uri)
        bearer = {"Authorization": "Bearer " + session["access_token"]}
        # The callback web page itself is never requested; even a 404 page may carry a valid token.
        user = json_response(client.get(AUTH + "/userinfo", headers=bearer), "Riot 帳號驗證（userinfo）")
        entitlement = json_response(client.post("https://entitlements.auth.riotgames.com/api/token/v1",
                                                headers=bearer, json={}), "Riot 遊戲授權（entitlement）")
        if not entitlement.get("entitlements_token") or not user.get("sub"):
            raise AuthError("Riot 回傳缺少 entitlement 或帳號 ID。")
        session.update(entitlements_token=entitlement["entitlements_token"], puuid=user["sub"],
                       cookies=[{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
                                for c in client.cookies.jar if c.domain.lstrip(".") == "auth.riotgames.com"])
        self.vault.write("session", session)
        return session

    def redirect_uri(self, client: httpx.Client, uri: str) -> str:
        for _ in range(8):
            parsed = urlsplit(uri)
            # Use the same parser as pasted URLs, including Riot-host callbacks and fragment routes.
            try:
                token_from_url(uri)
            except AuthError:
                pass
            else:
                return uri
            if parsed.scheme != "https" or parsed.hostname not in {
                "auth.riotgames.com", "authenticate.riotgames.com"}:
                break
            # /authorize is a browser navigation, not a JSON API. Keep the client's
            # JSON default for userinfo/entitlements and override only page requests.
            response = client.get(uri, headers={"Accept": PAGE_ACCEPT})
            if response.status_code >= 400:
                if response.status_code == 406:
                    raise AuthError("Cookie 自動更新仍收到 HTTP 406（已使用網頁 Accept 標頭）。"
                                    "這不是 Cookie 欄位格式錯誤，可能還有 Riot 請求或環境限制；"
                                    "請回報此訊息，不必反覆複製同一份 Cookie。")
                raise AuthError(f"Cookie 自動更新被 Riot 拒絕（HTTP {response.status_code}）；"
                                "網址 token 成功不代表 Cookie 可自動更新，請重新登入或改用網址暫時測試。")
            if response.status_code not in {301, 302, 303, 307, 308}:
                break
            from urllib.parse import urljoin
            uri = urljoin(uri, response.headers.get("location", ""))
        raise AuthError("Cookie 自動更新未完成：Riot 沒有回傳 access_token，可能是 ssid 已失效、"
                        "只複製 ssid 不足以恢復工作階段，或需要瀏覽器互動驗證。可改用已驗證的網址暫時測試。")

    def login(self, username: str, password: str, get_code, *, legacy=False) -> dict:
        with self.client() as client:
            json_response(client.post(AUTH + "/api/v1/authorization", json=PARAMS))
            body = {"type": "auth", "remember": True, "language": "en_US"}
            if legacy:
                body.update(username=username, password=password)
            else:
                body["riot_identity"] = {"username": username, "password": password, "captcha": ""}
            # If Riot requires a challenge, the user completes it in the browser fallback.
            result = json_response(client.put(AUTH + "/api/v1/authorization", json=body))
            for _ in range(3):
                if result.get("type") != "multifactor":
                    break
                code = get_code()
                mfa = {"type": "multifactor"}
                if legacy:
                    mfa.update(code=code, rememberDevice=True)
                else:
                    mfa["multifactor"] = {"otp": code, "rememberDevice": True}
                result = json_response(client.put(AUTH + "/api/v1/authorization", json=mfa))
            if result.get("type") == "response":
                uri = result["response"]["parameters"]["uri"]
            elif result.get("type") == "success":
                uri = self.redirect_uri(client, result["success"]["redirect_url"])
            else:
                raise AuthError("帳密登入未完成（驗證碼錯誤、CAPTCHA 或新版登入限制）；請使用瀏覽器模式。")
            return self.finish(client, uri)

    def import_browser(self, uri: str, ssid: str = "") -> dict:
        with self.client() as client:
            if ssid:
                client.cookies.set("ssid", ssid, domain="auth.riotgames.com", path="/")
            return self.finish(client, uri)

    def import_ssid(self, ssid: str) -> dict:
        ssid = ssid.strip()
        if not ssid or any(char in ssid for char in "\r\n;"):
            raise AuthError("請只複製 ssid 那一列的 Value，不是整列或整段 Cookie。")
        with self.client() as client:
            client.cookies.set("ssid", ssid, domain="auth.riotgames.com", path="/")
            return self.finish(client, self.redirect_uri(client, LOGIN_URL))

    def import_cookie_header(self, header: str) -> dict:
        """Import only the Cookie header of a request to auth.riotgames.com."""
        header = header.strip()
        if header.lower().startswith("cookie:"):
            header = header.partition(":")[2].strip()
        if not header or "\n" in header or "\r" in header:
            raise AuthError("請只貼 Riot auth.riotgames.com 請求的 Cookie 欄位值，不是整段請求標頭。")
        cookies = SimpleCookie()
        try:
            cookies.load(header)
        except CookieError as exc:
            raise AuthError("Cookie 欄位格式無法解析，請重新複製完整 Cookie 欄位值。") from exc
        if not cookies.get("ssid"):
            raise AuthError("Cookie 欄位未含 ssid；請確認複製的是 auth.riotgames.com 的登入請求。")
        with self.client() as client:
            for name, value in cookies.items():
                client.cookies.set(name, value.value, domain="auth.riotgames.com", path="/")
            return self.finish(client, self.redirect_uri(client, LOGIN_URL))

    def import_local(self) -> dict:
        session = local_session()
        self.vault.write("session", session)
        return session

    def session(self, force=False) -> dict:
        with self.vault.lock("auth"):
            session = self.vault.read("session")
            if not session:
                raise AuthError("尚未登入 Riot，請執行 setup.py。")
            if not force and session["expires_at"] > time.time() + 90:
                return session
            if session.get("source") == "local":
                updated = local_session()
                if updated["puuid"] != session["puuid"]:
                    raise AuthError("Riot Client 已切換至另一個帳號，請切回原帳號或重新設定 Bot。")
                self.vault.write("session", updated)
                return updated
            if not session.get("cookies"):
                raise AuthError("Riot 憑證已過期；瀏覽器模式需提供 ssid 才能自動更新，請重新設定。")
            with self.client(session["cookies"]) as client:
                return self.finish(client, self.redirect_uri(client, LOGIN_URL))
