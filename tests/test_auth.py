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
