from unittest.mock import Mock

import httpx

from valbot.assets import Assets
from valbot.riot import RiotClient


def test_storefront_v3_fallback_only_on_missing_endpoint(monkeypatch):
    monkeypatch.setattr(Assets, "get", lambda self, path: {"riotClientVersion": "version"})
    paths = []

    def handler(request):
        paths.append((request.method, request.url.path))
        if "/v3/" in request.url.path:
            return httpx.Response(404, json={})
        return httpx.Response(200, json={"SkinsPanelLayout": {}})

    auth = Mock()
    auth.session.return_value = {"puuid": "owner", "access_token": "access", "entitlements_token": "ent"}
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        riot = RiotClient({"region": "br"}, auth, http)
        assert riot.base == "https://pd.na.a.pvp.net"
        assert riot.storefront() == {"SkinsPanelLayout": {}}
    assert paths == [("POST", "/store/v3/storefront/owner"), ("GET", "/store/v2/storefront/owner")]


def test_auth_expiry_retries_with_new_bearer(monkeypatch):
    monkeypatch.setattr(Assets, "get", lambda self, path: {"riotClientVersion": "version"})
    seen = []

    def handler(request):
        seen.append(request.headers["Authorization"])
        return httpx.Response(401 if len(seen) == 1 else 200, json={"Balances": {}})

    auth = Mock()
    auth.session.side_effect = [{"puuid": "owner", "access_token": "old", "entitlements_token": "ent"},
                                {"puuid": "owner", "access_token": "new", "entitlements_token": "ent"}]
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        assert RiotClient({"region": "ap"}, auth, http).wallet() == {"Balances": {}}
    assert seen == ["Bearer old", "Bearer new"]
    auth.session.assert_called_with(force=True)
