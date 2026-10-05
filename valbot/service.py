from __future__ import annotations

from . import flex
from .riot import RiotClient, offer_item, price, CURRENCIES


class BotService:
    def __init__(self, riot: RiotClient):
        self.riot = riot
        self.assets = riot.assets

    def store_cards(self, store: dict, kind: str):
        if kind == "商店":
            panel = store.get("SkinsPanelLayout") or {}
            offers = panel.get("SingleItemStoreOffers") or []
            if not offers and panel.get("SingleItemOffers"):
                catalog = self.riot.request("/store/v1/offers").get("Offers", [])
                lookup = {x["OfferID"]: x for x in catalog}
                offers = [lookup.get(uuid, {"OfferID": uuid}) for uuid in panel["SingleItemOffers"]]
            remaining = panel.get("SingleItemOffersRemainingDurationInSeconds")
        elif kind == "夜市":
            panel = store.get("BonusStore") or {}
            offers = panel.get("BonusStoreOffers") or []
            remaining = panel.get("BonusStoreRemainingDurationInSeconds")
            if not offers:
                return flex.notice("夜市尚未開放", "夜市開放時會自動加入每日推播。")
        else:
            panel = store.get("AccessoryStore") or {}
            offers = panel.get("AccessoryStoreOffers") or []
            remaining = panel.get("AccessoryStoreRemainingDurationInSeconds")
        if not offers:
            return flex.notice(kind, "Riot 目前未提供商店項目。")
        return flex.carousel([flex.item_card(offer_item(x, self.assets), kind, remaining) for x in offers])

    def bundles(self, store):
        featured = store.get("FeaturedBundle") or {}
        bundles = featured.get("Bundles") or ([featured["Bundle"]] if featured.get("Bundle") else [])
        cards = []
        for bundle in bundles:
            public = self.assets.lookup("bundles", bundle.get("DataAssetID", ""))
            amount, currency = price(bundle.get("TotalDiscountedCost"))
            original, _ = price(bundle.get("TotalBaseCost"))
            if amount is None and bundle.get("Items"):
                amount = sum(x.get("DiscountedPrice", 0) for x in bundle["Items"])
                original = sum(x.get("BasePrice", 0) for x in bundle["Items"])
            cards.append(flex.item_card({"name": public.get("displayName", "精選組合包"),
                                         "image": public.get("displayIcon"), "price": amount,
                                         "original": original, "currency": currency,
                                         "discount": round(100 * (original - amount) / original)
                                         if original and amount is not None else 0},
                                        "精選組合包", bundle.get("DurationRemainingInSeconds")))
        return flex.carousel(cards) if cards else flex.notice("精選組合包", "目前沒有精選組合包。")

    def daily(self):
        store = self.riot.storefront()
        cards = [self.store_cards(store, "商店"), self.store_cards(store, "配件"), self.bundles(store)]
        if (store.get("BonusStore") or {}).get("BonusStoreOffers"):
            cards.append(self.store_cards(store, "夜市"))
        return flex.messages(cards, "Valorant 每日商店 · 配件 · 精選組合包")

    def wallet(self):
        balances = self.riot.wallet().get("Balances") or {}
        cards = []
        for uuid, name in CURRENCIES.items():
            item = self.assets.lookup("currencies", uuid)
            row = [flex.text(name, "lg", weight="bold"),
                   flex.text(f"{balances[uuid]:,}" if uuid in balances else "未提供", "xxl", flex.RED,
                             weight="bold")]
            if item.get("displayIcon"):
                row.insert(0, flex.image(item["displayIcon"], size="xxs"))
            cards.append(flex.box(row, "horizontal", spacing="md", alignItems="center",
                                  paddingAll="12px", backgroundColor=flex.PANEL, cornerRadius="10px"))
        return flex.bubble("錢包餘額", cards)

    def rank(self):
        mmr = self.riot.mmr()
        content = self.riot.content()
        season = next((x["ID"] for x in content.get("Seasons", [])
                       if x.get("IsActive") and x.get("Type", "").lower() == "act"), None)
        seasonal = (mmr.get("QueueSkills") or {}).get("competitive", {}).get("SeasonalInfoBySeasonID") or {}
        current = seasonal.get(season) or {}
        badge = self.assets.rank(current.get("CompetitiveTier", 0))
        latest = mmr.get("LatestCompetitiveUpdate") or {}
        details = [flex.text(badge.get("tierName", "未定級"), "xxl", weight="bold"),
                   flex.text(f"{current.get('RankedRating', 0)} RR", "xl", flex.RED),
                   flex.progress("牌位進度", current.get("RankedRating", 0), 100)]
        if latest.get("MatchID"):
            delta = latest.get("RankedRatingEarned", 0)
            details.append(flex.text(f"最近競技對戰 {delta:+d} RR", "md",
                                     flex.GREEN if delta >= 0 else flex.RED))
            if latest.get("SeasonID") != season:
                details.append(flex.text("最近競技對戰屬於過往賽季", "xs", flex.MUTED))
        icon = badge.get("largeIcon") or badge.get("smallIcon")
        hero = flex.box([flex.image(icon, size="md", aspectRatio="1:1")],
                        backgroundColor=flex.PANEL, paddingAll="20px") if icon else None
        return flex.bubble("當前競技牌位", details, hero)

    def missions(self):
        contracts = self.riot.contracts()
        missions = contracts.get("Missions") or []
        if not missions:
            return flex.notice("任務", "目前沒有可用任務。請登入遊戲更新進度後再查詢。")
        definitions = {x["uuid"]: x for x in self.assets.get("missions")}
        cards = []
        for mission in missions:
            definition = definitions.get(mission["ID"], {})
            objectives = definition.get("objectives") or []
            lookup = {x["objectiveUuid"]: x for x in objectives}
            contents = [flex.text("已完成" if mission.get("Complete") else "進行中", "sm", flex.GREEN)]
            for uuid, value in (mission.get("Objectives") or {}).items():
                objective = lookup.get(uuid, {})
                contents.append(flex.progress(objective.get("displayName") or "任務目標 " + uuid[:8],
                                              value, objective.get("value")))
            if definition.get("xpGrant"):
                contents.append(flex.text(f"獎勵 {definition['xpGrant']:,} XP", "sm", flex.RED))
            if mission.get("ExpirationTime"):
                contents.append(flex.text("截止 " + mission["ExpirationTime"], "xs", flex.MUTED))
            cards.append(flex.bubble(definition.get("title") or definition.get("displayName")
                                     or "任務 " + mission["ID"][:8], contents))
        return flex.carousel(cards)

    def battlepass(self):
        contracts = self.riot.contracts()
        content = self.riot.content()
        active = {x["ID"] for x in content.get("Seasons", []) if x.get("IsActive")}
        definitions = self.assets.get("contracts")
        definition = next((x for x in definitions if (x.get("content") or {}).get("relationType") == "Season"
                           and (x.get("content") or {}).get("relationUuid") in active), None)
        if not definition:
            return flex.notice("通行證", "公開圖庫尚未提供本期通行證，請稍後再試。")
        account = next((x for x in contracts.get("Contracts", [])
                        if x["ContractDefinitionID"] == definition["uuid"]), {})
        levels = [level for chapter in definition["content"].get("chapters", [])
                  for level in chapter.get("levels", [])]
        reached = account.get("ProgressionLevelReached", 0)
        next_level = levels[reached] if reached < len(levels) else None
        contents = [flex.text(f"等級 {reached} / {len(levels)}", "xxl", weight="bold")]
        if next_level:
            contents.append(flex.progress("距離下一階", account.get("ProgressionTowardsNextLevel", 0),
                                          next_level.get("xp")))
            reward = next_level.get("reward") or {}
            if reward.get("uuid"):
                item = self.assets.item(reward["uuid"])
                contents.append(flex.text("下一階獎勵 · " + item["name"], "sm", flex.MUTED))
                if item.get("image"):
                    contents.append(flex.image(item["image"], aspectRatio="16:9"))
        else:
            contents.append(flex.text("本期進度已完成", "md", flex.GREEN))
        return flex.bubble(definition["displayName"], contents)

    def command(self, command: str):
        command = command.strip()
        if command in {"商店", "夜市", "配件"}:
            card = self.store_cards(self.riot.storefront(), command)
        elif command == "錢包":
            card = self.wallet()
        elif command == "牌位":
            card = self.rank()
        elif command == "戰績":
            match = self.riot.latest_match()
            card = flex.match_card(match, self.riot.puuid, self.assets) if match else flex.notice("戰績", "沒有近期對戰。")
        elif command == "任務":
            card = self.missions()
        elif command == "通行證":
            card = self.battlepass()
        else:
            card = flex.menu()
        return flex.messages([card], "Valorant · " + command[:30])
