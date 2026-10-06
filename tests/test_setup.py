from types import SimpleNamespace
from unittest.mock import Mock

import setup
from valbot.auth import AuthError
from valbot.storage import Vault


def test_setup_keeps_url_login_when_optional_ssid_fails(tmp_path, monkeypatch):
    live = Vault(tmp_path / "live")
    staged = Vault(tmp_path / "staged")
    original = {"puuid": "owner", "access_token": "valid-token", "expires_at": 9999999999}
    auth = Mock()
    auth.import_browser.side_effect = lambda uri: staged.write("session", original)
    auth.import_ssid.side_effect = AuthError("Cookie rejected")
    monkeypatch.setattr(setup, "RiotAuth", Mock(return_value=auth))
    monkeypatch.setattr(setup.webbrowser, "open", Mock())
    prompts = iter(["ap", "2"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(prompts))
    values = iter(["https://playvalorant.com/opt_in#access_token=valid-token", "line-token", "line-secret",
                   "U" + "1" * 32])
    monkeypatch.setattr(setup, "required", lambda *args, **kwargs: next(values))
    cookies = iter(["rejected-cookie", ""])
    monkeypatch.setattr(setup, "getpass", lambda prompt: next(cookies))
    riot = Mock()
    riot.storefront.return_value = {"SkinsPanelLayout": {}}
    monkeypatch.setattr(setup, "RiotClient", Mock(return_value=riot))
    line = Mock()
    monkeypatch.setattr(setup, "LineClient", Mock(return_value=line))
    args = SimpleNamespace(login_method="browser", legacy_auth=False, no_schedule=True)
    assert setup.configure(live, staged, args) == 0
    assert live.read("session") == original
    assert live.read("config")["riot_puuid"] == "owner"
    line.push.assert_called_once()
