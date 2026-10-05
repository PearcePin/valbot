"""Export reviewable Flex examples using public assets and clearly marked demo data.

Run from the project root: python -m tools.export_flex_samples
Paste one message's contents into LINE Flex Message Simulator.
"""
import json

import httpx

from valbot import flex
from valbot.assets import Assets
from valbot.line import LineClient
from valbot.storage import ROOT


def main():
    with httpx.Client(timeout=20) as client:
        assets = Assets(client)
        skins = [x for x in assets.get("weapons/skins") if x.get("levels") and x.get("chromas")
                 and x["chromas"][0].get("fullRender")][:6]
        daily, night = [], []
        for i, skin in enumerate(skins):
            item = assets.item(skin["levels"][0]["uuid"])
            demo = {**item, "price": 1775, "original": 1775, "discount": 0, "currency": "VP"}
            if i < 4:
                daily.append(flex.item_card(demo, "每日商店 · 示範價格", 72000))
            night.append(flex.item_card({**demo, "price": 1243, "discount": 30}, "夜市 · 示範價格", 172800))
        card = next(x for x in assets.get("playercards") if x.get("largeArt"))
        accessory = flex.item_card({"name": card["displayName"], "image": card["largeArt"], "price": 4500,
                                   "currency": "KC", "discount": 0}, "配件 · 示範價格")
        map_info = next(x for x in assets.get("maps") if x.get("splash"))
        agent = next(x for x in assets.get("agents") if x.get("isPlayableCharacter"))
        match = {"matchInfo": {"mapId": map_info["mapUrl"], "queueID": "示範 competitive"},
                 "players": [{"subject": "demo", "characterId": agent["uuid"], "teamId": "Red",
                              "stats": {"kills": 24, "deaths": 15, "assists": 7,
                                        "score": 5940, "roundsPlayed": 22}}],
                 "teams": [{"teamId": "Red", "won": True, "roundsWon": 13},
                           {"teamId": "Blue", "won": False, "roundsWon": 9}]}
        badge = assets.rank(20)
        rank = flex.bubble("牌位 · 示範數據", [flex.text(badge["tierName"], "xxl", weight="bold"),
                            flex.progress("RR", 68, 100), flex.text("最近一場 +22 RR", "md", flex.GREEN)],
                           flex.box([flex.image(badge["largeIcon"], size="md", aspectRatio="1:1")],
                                    backgroundColor=flex.PANEL, paddingAll="20px"))
        mission = flex.bubble("任務 · 示範數據", [flex.progress("造成傷害", 12500, 18000),
                                                flex.text("獎勵 12,000 XP", "sm", flex.RED)])
        messages = flex.messages([flex.menu(), flex.carousel(daily), flex.carousel(night), accessory,
                                  flex.match_card(match, "demo", assets), rank, mission], "Valorant Flex 示範")
        LineClient.models(messages)
    directory = ROOT / "examples"
    directory.mkdir(exist_ok=True)
    (directory / "flex-messages.json").write_text(json.dumps(messages, ensure_ascii=False, indent=2),
                                                  encoding="utf-8")
    print("Exported examples/flex-messages.json (demo data, real public image URLs).")


if __name__ == "__main__":
    main()
