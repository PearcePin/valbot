import time
from unittest.mock import Mock

import httpx
import pytest

from valbot.auth import RiotAuth, AuthError, token_from_url
from valbot.storage import Vault


def test_token_requires_correct_redirect():
    with pytest.raises(AuthError):
        token_from_url("https://evil.example/#access_token=secret")
    with pytest.raises(AuthError):
        token_from_url("https://playvalorant.com/opt_in#no_token=1")
    token = token_from_url("https://playvalorant.com/opt_in#access_token=abc&expires_in=60")
    assert token["access_token"] == "abc"
    assert time.time() < token["expires_at"] <= time.time() + 60


@pytest.mark.parametrize("url", [
    " https://playvalorant.com/opt_in/#access_token=abc&expires_in=60 ",
    "https://www.playvalorant.com/zh-tw/opt_in#access_token=abc&expires_in=60",
    "https://playvalorant.com/zh-tw/?access_token=abc&expires_in=60",
    "https://auth.riotgames.com/callback#access_token=abc&expires_in=60",
    "https://authenticate.riotgames.com/callback#/login?access_token=abc&expires_in=60",
    "https%3A%2F%2Fplayvalorant.com%2Fopt_in%23access_token%3Dabc%26expires_in%3D60",
])
def test_browser_callback_variants(url):
    assert token_from_url(url)["access_token"] == "abc"


def test_missing_token_error_explains_alternatives():
    with pytest.raises(AuthError, match="ssid"):
        token_from_url("https://playvalorant.com/zh-tw/")
    with pytest.raises(AuthError, match="有效時間"):
        token_from_url("https://playvalorant.com/opt_in#access_token=abc&expires_in=bad")
    with pytest.raises(AuthError, match="id_token"):
        token_from_url("https://playvalorant.com/opt_in#id_token=secret&token_type=Bearer")


def test_callback_page_is_never_fetched_even_if_it_would_return_404(tmp_path):
    auth = RiotAuth(Vault(tmp_path))
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.path == "/userinfo":
            return httpx.Response(200, json={"sub": "owner"})
        if request.url.host == "entitlements.auth.riotgames.com":
            return httpx.Response(200, json={"entitlements_token": "ent"})
        return httpx.Response(404)

    auth.client = lambda cookies=(): httpx.Client(transport=httpx.MockTransport(handler))
    result = auth.import_browser("https://auth.riotgames.com/nonexistent#access_token=private-token")
    assert result["puuid"] == "owner"
    assert len(seen) == 2
    assert not any("private-token" in url or "nonexistent" in url for url in seen)


@pytest.mark.parametrize("stage", ["userinfo", "entitlement"])
def test_api_error_identifies_stage_without_leaking_credentials(tmp_path, stage):
    auth = RiotAuth(Vault(tmp_path))

    def handler(request):
        if (stage == "userinfo" and request.url.path == "/userinfo") or (
                stage == "entitlement" and request.url.host == "entitlements.auth.riotgames.com"):
            return httpx.Response(401, json={"private": "private-token"})
        return httpx.Response(200, json={"sub": "owner"})

    auth.client = lambda cookies=(): httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(AuthError) as error:
        auth.import_browser("https://playvalorant.com/opt_in#access_token=private-token")
    assert stage in str(error.value)
    assert "401" in str(error.value)
    assert "private-token" not in str(error.value)
    assert auth.vault.read("session") == {}


@pytest.mark.parametrize("callback", [
    "https://playvalorant.com/opt_in#access_token=abc&expires_in=3600",
    "https://auth.riotgames.com/callback#access_token=abc&expires_in=3600",
    "https://authenticate.riotgames.com/callback#/login?access_token=abc&expires_in=3600",
])
def test_ssid_login_does_not_require_pasted_callback(tmp_path, callback):
    auth = RiotAuth(Vault(tmp_path))
    cookies_seen = []

    def handler(request):
        if request.url.path == "/authorize":
            cookies_seen.append(request.headers.get("cookie", ""))
            return httpx.Response(302, headers={"location": callback})
        if request.url.path == "/userinfo":
            return httpx.Response(200, json={"sub": "owner"})
        return httpx.Response(200, json={"entitlements_token": "ent"})

    auth.client = lambda cookies=(): httpx.Client(transport=httpx.MockTransport(handler))
    assert auth.import_ssid("private-cookie")["puuid"] == "owner"
    assert cookies_seen == ["ssid=private-cookie"]
    assert auth.vault.read("session")["cookies"][0]["value"] == "private-cookie"


def test_full_cookie_import_keeps_other_auth_cookies_for_refresh(tmp_path):
    auth = RiotAuth(Vault(tmp_path))
    seen = []

    def handler(request):
        if request.url.path == "/authorize":
            seen.append(request.headers.get("cookie", ""))
            return httpx.Response(302, headers={"location":
                "https://playvalorant.com/opt_in#access_token=abc&expires_in=3600"})
        if request.url.path == "/userinfo":
            return httpx.Response(200, json={"sub": "owner"})
        return httpx.Response(200, json={"entitlements_token": "ent"})

    auth.client = lambda cookies=(): httpx.Client(transport=httpx.MockTransport(handler))
    auth.import_cookie_header("Cookie: ssid=private; asid=another-cookie")
    assert "ssid=private" in seen[0]
    assert "asid=another-cookie" in seen[0]
    assert {x["name"] for x in auth.vault.read("session")["cookies"]} == {"ssid", "asid"}
    with pytest.raises(AuthError):
        auth.import_cookie_header("Cookie: ssid=private\nAuthorization: Bearer secret")


def test_failed_cookie_update_does_not_replace_valid_url_session(tmp_path):
    vault = Vault(tmp_path)
    original = {"access_token": "known-valid", "puuid": "owner", "expires_at": time.time() + 3600}
    vault.write("session", original)
    auth = RiotAuth(vault)
    auth.client = lambda cookies=(): httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, text="interactive login required")))
    with pytest.raises(AuthError, match="Cookie 自動更新未完成"):
        auth.import_ssid("rejected-cookie")
    assert vault.read("session") == original


def test_local_client_refresh_never_changes_account(tmp_path, monkeypatch):
    import valbot.auth as auth_module
    vault = Vault(tmp_path)
    auth = RiotAuth(vault)
    original = {"source": "local", "puuid": "owner", "expires_at": 0, "cookies": []}
    vault.write("session", original)
    monkeypatch.setattr(auth_module, "local_session", lambda: {**original, "puuid": "other"})
    with pytest.raises(AuthError, match="另一個帳號"):
        auth.session()
    assert vault.read("session")["puuid"] == "owner"
    monkeypatch.setattr(auth_module, "local_session", lambda: {**original, "expires_at": time.time() + 3600})
    assert auth.session()["expires_at"] > time.time()


def test_local_client_credentials_only_go_to_loopback(tmp_path, monkeypatch):
    import valbot.auth as auth_module
    from types import SimpleNamespace
    import base64
    import json
    folder = tmp_path / "Riot Games" / "Riot Client" / "Config"
    folder.mkdir(parents=True)
    (folder / "lockfile").write_text("RiotClient:123:45678:local-only-password:https")
    monkeypatch.setattr(auth_module, "os", SimpleNamespace(name="nt", environ={"LOCALAPPDATA": str(tmp_path)}))
    payload = base64.urlsafe_b64encode(json.dumps({"exp": time.time() + 3600}).encode()).decode().rstrip("=")
    real_client = httpx.Client
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"accessToken": "header." + payload + ".signature",
                                        "token": "ent", "subject": "owner"})

    def client(**kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(auth_module.httpx, "Client", client)
    assert auth_module.local_session()["puuid"] == "owner"
    assert str(seen[0].url) == "https://127.0.0.1:45678/entitlements/v1/token"
    assert seen[0].headers["Authorization"].startswith("Basic ")


def test_mfa_retry_and_password_not_saved(tmp_path):
    requests = []
    attempts = 0

    def handler(request):
        nonlocal attempts
        requests.append(request)
        if request.url.path == "/api/v1/authorization":
            if request.method == "POST":
                return httpx.Response(200, json={"type": "auth"})
            import json
            body = json.loads(request.content)
            if body["type"] == "auth":
                return httpx.Response(200, json={"type": "multifactor"})
            attempts += 1
            if attempts == 1:
                return httpx.Response(200, json={"type": "multifactor", "error": "invalid_code"})
            return httpx.Response(200, json={"type": "response", "response": {"parameters": {
                "uri": "https://playvalorant.com/opt_in#access_token=abc&expires_in=3600"}}})
        if request.url.path == "/userinfo":
            return httpx.Response(200, json={"sub": "player"})
        return httpx.Response(200, json={"entitlements_token": "ent"})

    auth = RiotAuth(Vault(tmp_path))
    auth.client = lambda cookies=(): httpx.Client(transport=httpx.MockTransport(handler))
    get_code = Mock(side_effect=["wrong", "right"])
    session = auth.login("owner", "private-password", get_code)
    assert get_code.call_count == 2
    assert session["puuid"] == "player"
    assert "private-password" not in str(auth.vault.read("session"))


def test_expired_session_needs_interactive_login(tmp_path):
    vault = Vault(tmp_path)
    vault.write("session", {"expires_at": 0, "cookies": []})
    with pytest.raises(AuthError, match="過期"):
        RiotAuth(vault).session()


def test_vault_ciphertext_round_trip(tmp_path):
    vault = Vault(tmp_path)
    vault.write("config", {"token": "private-secret"})
    assert b"private-secret" not in (tmp_path / "config.enc").read_bytes()
    assert Vault(tmp_path).read("config") == {"token": "private-secret"}
