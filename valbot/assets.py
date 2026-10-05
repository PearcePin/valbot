from __future__ import annotations

import json
import time

import httpx

from .storage import atomic_write, data_dir


class Assets:
    """Public metadata cache. Unknown UUIDs are shown honestly without invented image URLs."""

    def __init__(self, client: httpx.Client):
        self.client = client
        self.memory = {}

    def get(self, endpoint: str):
        if endpoint in self.memory:
            return self.memory[endpoint]
        cache = data_dir() / ("assets-" + endpoint.replace("/", "-") + ".json")
        if cache.exists() and time.time() - cache.stat().st_mtime < 21600:
            result = json.loads(cache.read_text(encoding="utf-8"))
        else:
            try:
                response = self.client.get("https://valorant-api.com/v1/" + endpoint,
                                           params={"language": "zh-TW"})
                response.raise_for_status()
                result = response.json()["data"]
                atomic_write(cache, json.dumps(result).encode())
            except (httpx.HTTPError, ValueError, KeyError):
                if not cache.exists():
                    raise
                result = json.loads(cache.read_text(encoding="utf-8"))
        self.memory[endpoint] = result
        return result

    def item(self, uuid: str) -> dict:
        for endpoint in ("weapons/skins", "buddies", "playercards", "sprays", "playertitles", "currencies"):
            for item in self.get(endpoint):
                children = [item, *(item.get("levels") or []), *(item.get("chromas") or [])]
                if any(x.get("uuid", "").lower() == uuid.lower() for x in children):
                    child = next(x for x in children if x.get("uuid", "").lower() == uuid.lower())
                    return {"name": child.get("displayName") or item["displayName"],
                            "image": item.get("largeArt") or child.get("fullRender")
                            or (item.get("chromas") or [{}])[0].get("fullRender")
                            or child.get("displayIcon") or item.get("displayIcon")}
        return {"name": "未知物品 · " + uuid[:8], "image": None}

    def lookup(self, endpoint: str, uuid: str) -> dict:
        return next((x for x in self.get(endpoint) if x.get("uuid") == uuid), {})

    def map(self, path: str) -> dict:
        return next((x for x in self.get("maps") if x.get("mapUrl") == path or x["uuid"] == path), {})

    def rank(self, tier: int) -> dict:
        latest = self.get("competitivetiers")[-1]
        return next((x for x in latest["tiers"] if x["tier"] == tier), {"tierName": "未定級"})
