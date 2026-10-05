from __future__ import annotations

import time
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from .storage import Vault

AUTH = "https://auth.riotgames.com"
PARAMS = {"client_id": "play-valorant-web-prod", "redirect_uri": "https://playvalorant.com/opt_in",
          "response_type": "token id_token", "scope": "account openid", "nonce": "1"}
LOGIN_URL = AUTH + "/authorize?" + urlencode(PARAMS)


class AuthError(RuntimeError):
    pass


def json_response(response: httpx.Response) -> dict:
    if response.status_code >= 400:
        raise AuthError(f"Riot 登入回應 HTTP {response.status_code}；請使用瀏覽器登入或稍後重試。")
    try:
        return response.json()
    except ValueError as exc:
        raise AuthError("Riot 登入需要瀏覽器驗證（可能是 CAPTCHA），請切換瀏覽器模式。") from exc


def token_from_url(uri: str) -> dict:
    parsed = urlsplit(uri)
    if parsed.scheme != "https" or parsed.hostname != "playvalorant.com" or parsed.path != "/opt_in":
        raise AuthError("請貼上 Riot 登入完成後 playvalorant.com/opt_in 的完整網址。")
    fields = parse_qs(parsed.fragment)
    if not fields.get("access_token"):
        raise AuthError("網址沒有 access_token；請重新完成 Riot 登入。")
    return {"access_token": fields["access_token"][0],
            "id_token": fields.get("id_token", [""])[0],
            "expires_at": time.time() + int(fields.get("expires_in", ["3600"])[0])}


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
        entitlement = json_response(client.post("https://entitlements.auth.riotgames.com/api/token/v1",
                                                headers=bearer, json={}))
        user = json_response(client.get(AUTH + "/userinfo", headers=bearer))
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
            if parsed.hostname == "playvalorant.com" and "access_token=" in parsed.fragment:
                return uri
            if parsed.scheme != "https" or parsed.hostname not in {
                "auth.riotgames.com", "authenticate.riotgames.com"}:
                break
            response = client.get(uri)
            if response.status_code not in {301, 302, 303, 307, 308}:
                break
            from urllib.parse import urljoin
            uri = urljoin(uri, response.headers.get("location", ""))
        raise AuthError("工作階段失效或需要互動驗證，請重新執行 setup.py 登入。")

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

    def session(self, force=False) -> dict:
        with self.vault.lock("auth"):
            session = self.vault.read("session")
            if not session:
                raise AuthError("尚未登入 Riot，請執行 setup.py。")
            if not force and session["expires_at"] > time.time() + 90:
                return session
            if not session.get("cookies"):
                raise AuthError("Riot 憑證已過期；瀏覽器模式需提供 ssid 才能自動更新，請重新設定。")
            with self.client(session["cookies"]) as client:
                return self.finish(client, self.redirect_uri(client, LOGIN_URL))
