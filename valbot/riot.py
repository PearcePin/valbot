from __future__ import annotations

import base64
import json

import httpx

from .assets import Assets
from .auth import RiotAuth, AuthError

PLATFORM = base64.b64encode(json.dumps({"platformType": "PC", "platformOS": "Windows",
                                      "platformOSVersion": "10.0.19042.1.256.64bit",
                                      "platformChipset": "Unknown"}).encode()).decode()
VP = "85ad13f7-3d1b-5128-9eb2-7cd8a66ba429"
RP = "e59aa87c-4cbf-517a-5983-6e81511be9b7"
KC = "85ca954a-41f2-ce94-9b45-8ca3dd39a00d"
CURRENCIES = {VP: "VP", RP: "RP", KC: "KC"}
SHARDS = {"ap": "ap", "na": "na", "eu": "eu", "kr": "kr", "br": "na", "latam": "na"}


class DataError(RuntimeError):
    pass


class RiotClient:
    def __init__(self, config: dict, auth: RiotAuth, client: httpx.Client):
        self.config, self.auth, self.client = config, auth, client
        self.assets = Assets(client)
        self.session = auth.session()
        self.puuid = self.session["puuid"]
        if config.get("riot_puuid") and config["riot_puuid"] != self.puuid:
            raise AuthError("設定與登入帳號不一致，請重新執行 setup.py。")
        self.base = f"https://pd.{SHARDS[config['region']]}.a.pvp.net"
        self.version = self.assets.get("version")["riotClientVersion"]

    def request(self, path: str, *, method="GET", shared=False):
        shard = SHARDS[self.config["region"]]
        base = f"https://shared.{shard}.a.pvp.net" if shared else self.base
        for attempt in range(2):
            headers = {"Authorization": "Bearer " + self.session["access_token"],
                       "X-Riot-Entitlements-JWT": self.session["entitlements_token"],
                       "X-Riot-ClientVersion": self.version, "X-Riot-ClientPlatform": PLATFORM}
            response = self.client.request(method, base + path, headers=headers,
                                           **({"json": {}} if method == "POST" else {}))
            if response.status_code == 401 and attempt == 0:
                self.session = self.auth.session(force=True)
                if self.session["puuid"] != self.puuid:
                    raise AuthError("登入帳號已變更，請重新啟動服務。")
                continue
            if response.status_code >= 400:
                raise DataError(f"Riot 資料介面 HTTP {response.status_code}；請確認區域、登入與服務狀態。")
            try:
                result = response.json()
            except ValueError as exc:
                raise DataError("Riot 資料介面回傳非 JSON 資料。") from exc
            if isinstance(result, dict) and result.get("errorCode"):
                raise DataError("Riot 暫時無法提供此資料，請稍後重試。")
            return result

    def storefront(self):
        # Modern v3 first, retain older shard compatibility only for missing endpoints.
        try:
            return self.request(f"/store/v3/storefront/{self.puuid}", method="POST")
        except DataError as exc:
            if "HTTP 404" not in str(exc) and "HTTP 405" not in str(exc):
                raise
            return self.request(f"/store/v2/storefront/{self.puuid}")

    def wallet(self):
        return self.request(f"/store/v1/wallet/{self.puuid}")

    def content(self):
        return self.request("/content-service/v3/content", shared=True)

    def recent_matches(self, limit=5):
        if not 1 <= limit <= 5:
            raise ValueError("戰績查詢數量須為 1 至 5 場。")
        return [self.match_detail(entry["MatchID"]) for entry in self.match_history(limit)]

    def match_history(self, limit=10):
        if not 1 <= limit <= 100:
            raise ValueError("戰績紀錄數量須為 1 至 100 場。")
        return (self.request(f"/match-history/v1/history/{self.puuid}?startIndex=0&endIndex={limit}")
                .get("History") or [])[:limit]

    def match_detail(self, match_id):
        return self.request("/match-details/v1/matches/" + match_id)

    def competitive_updates(self, limit=10):
        return (self.request(f"/mmr/v1/players/{self.puuid}/competitiveupdates?startIndex=0&endIndex={limit}&queue=competitive")
                .get("Matches") or [])[:limit]

    def mmr(self):
        return self.request(f"/mmr/v1/players/{self.puuid}")


def price(cost: dict | None) -> tuple[int | None, str]:
    if not cost:
        return None, "VP"
    currency, amount = next(iter(cost.items()))
    return amount, CURRENCIES.get(currency, "代幣")


def offer_item(wrapper: dict, assets: Assets) -> dict:
    offer = wrapper.get("Offer", wrapper)
    rewards = offer.get("Rewards") or []
    uuid = rewards[0]["ItemID"] if rewards else offer.get("OfferID", "unknown")
    item = assets.item(uuid)
    original, currency = price(offer.get("Cost"))
    discounted, _ = price(wrapper.get("DiscountCosts") or wrapper.get("DiscountedCost") or offer.get("Cost"))
    discount = wrapper.get("DiscountPercent", 0)
    # Riot may use fractional bundle discounts and whole night-market percentages.
    if 0 < discount < 1:
        discount *= 100
    return {**item, "original": original, "price": discounted, "currency": currency,
            "discount": round(discount)}
