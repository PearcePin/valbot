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
        from .analysis import match_time
        mmr, content = self.riot.mmr(), self.riot.content()
        seasons = content.get("Seasons") or []
        season = next((x["ID"] for x in seasons if x.get("IsActive")
                       and x.get("Type", "").lower() == "act"), None)
        queue = (mmr.get("QueueSkills") or {}).get("competitive") or {}
        seasonal = queue.get("SeasonalInfoBySeasonID") or {}
        current = seasonal.get(season) or {}
        tier = current.get("CompetitiveTier", 0)
        badge = self.assets.rank(tier)
        rr = current.get("RankedRating")
        wins = current.get("NumberOfWinsWithPlacements", current.get("NumberOfWins"))
        games = current.get("NumberOfGames")
        rate = round(wins / games * 100, 1) if wins is not None and games else None
        details = [flex.text(badge.get("tierName", "未定級"), "xxl", weight="bold"),
                   flex.text(flex.display(rr, " RR"), "xl", flex.RED),
                   flex.metrics([("本季場次", games), ("勝場（含定級）" if "NumberOfWinsWithPlacements" in current else "勝場", wins),
                                 ("本季勝率", flex.display(rate, "%"))])]
        placements = current.get("GamesNeededForRating", queue.get("CurrentSeasonGamesNeededForRating"))
        if placements is not None:
            details.append(flex.text(f"定級剩餘 {placements} 場" if placements else "本季定級已完成", "sm", flex.MUTED))
        if tier and tier < 24 and rr is not None:
            details.append(flex.progress("RR 進度", rr, 100))
        elif tier >= 24:
            details.append(flex.text("神話／輻能以 RR 與排行榜資格為準", "xs", flex.MUTED))
        if current.get("LeaderboardRank", 0) > 0:
            details.append(flex.text(f"排行榜第 {current['LeaderboardRank']:,} 名", "md", flex.GREEN))
        for key, label in (("NumberOfWins", "勝場（不含定級）"), ("CapstoneWins", "高階勝場"),
                           ("TotalWinsNeededForRank", "牌位所需勝場")):
            if key in current:
                details.append(flex.text(f"{label}：{current[key]}", "xs", flex.MUTED))
        if "TotalGamesNeededForLeaderboard" in queue:
            details.append(flex.text(f"排行榜所需總場次：{queue['TotalGamesNeededForLeaderboard']}", "xs", flex.MUTED))
        winning_tiers = sorted((int(k), v) for k, v in (current.get("WinsByTier") or {}).items()
                               if str(k).isdigit() and isinstance(v, (int, float)) and v > 0)
        if winning_tiers:
            peak_tier = self.assets.rank(winning_tiers[-1][0])
            details.append(flex.text("本季最高勝場段位：" + peak_tier.get("tierName", str(winning_tiers[-1][0])), "sm", flex.GREEN))
        for key, label in (("IsLeaderboardAnonymized", "排行榜匿名"), ("IsActRankBadgeHidden", "隱藏賽季徽章")):
            if key in mmr:
                details.append(flex.text(label + ("：是" if mmr[key] else "：否"), "xs", flex.MUTED))
        icon = badge.get("largeIcon") or badge.get("smallIcon")
        hero = flex.box([flex.image(icon, size="md", aspectRatio="1:1")],
                        backgroundColor=flex.PANEL, paddingAll="20px") if icon else None
        cards = [flex.bubble("本季競技牌位", details, hero)]
        # Optional RR endpoint failure must not erase the base rank information.
        try:
            updates = self.riot.competitive_updates(10)
        except Exception:
            updates = []
        if not isinstance(updates, list):
            updates = []
        latest = mmr.get("LatestCompetitiveUpdate") or {}
        if not updates and latest.get("MatchID"):
            updates = [latest]
        rows = []
        deltas = [x["RankedRatingEarned"] for x in updates if x.get("SeasonID") == season
                  and isinstance(x.get("RankedRatingEarned"), (int, float))]
        if deltas:
            rows.append(flex.text(f"最近 {len(deltas)} 場本季積分合計 {sum(deltas):+} RR", "lg", flex.GREEN if sum(deltas) >= 0 else flex.RED))
        for update in updates[:5]:
            delta = update.get("RankedRatingEarned")
            label = f"{delta:+} RR" if isinstance(delta, (int, float)) else "RR 未提供"
            map_info = self.assets.map(update.get("MapID", ""))
            parts = [flex.text(match_time(update) + " · " + map_info.get("displayName", "對戰"), "xs", flex.MUTED),
                     flex.text(label, "lg", flex.GREEN if delta is not None and delta >= 0 else flex.RED),
                     flex.text(f"RR {flex.display(update.get('RankedRatingBeforeUpdate'))} → {flex.display(update.get('RankedRatingAfterUpdate'))}", "sm")]
            before, after = update.get("TierBeforeUpdate"), update.get("TierAfterUpdate")
            if before is not None and after is not None:
                parts.append(flex.text(self.assets.rank(before).get("tierName", str(before)) + " → " +
                                       self.assets.rank(after).get("tierName", str(after)), "xs", flex.MUTED))
            parts.append(flex.text("表現加成 " + flex.display(update.get("RankedRatingPerformanceBonus")) +
                                   " · AFK 懲罰 " + flex.display(update.get("AFKPenalty")), "xs", flex.MUTED))
            if update.get("SeasonID") != season:
                parts.append(flex.text("此場屬於其他賽季", "xxs", flex.MUTED))
            rows.append(flex.box(parts, spacing="sm", paddingAll="10px", backgroundColor=flex.PANEL, cornerRadius="8px"))
        cards.append(flex.bubble("近期競技 RR 變動", rows or [flex.text("尚無競技積分紀錄", "sm", flex.MUTED)]))
        history_rows = []
        # Riot content provides chronological acts; retain the latest six with account records.
        acts = [x for x in seasons if x.get("Type", "").lower() == "act" and x.get("ID") in seasonal]
        acts.sort(key=lambda x: x.get("StartTime", ""), reverse=True)
        for act in acts[:6]:
            record = seasonal[act["ID"]]
            old_badge = self.assets.rank(record.get("CompetitiveTier", 0))
            history_rows.append(flex.box([flex.text(act.get("Name") or act["ID"][:8], "sm", weight="bold"),
                                         flex.text(old_badge.get("tierName", "未定級") + " · " + flex.display(record.get("RankedRating"), " RR"), "md"),
                                         flex.text(f"{flex.display(record.get('NumberOfGames'))} 場 · {flex.display(record.get('NumberOfWinsWithPlacements', record.get('NumberOfWins')))} 勝", "xs", flex.MUTED)],
                                        paddingAll="10px", backgroundColor=flex.PANEL, cornerRadius="8px"))
        if history_rows:
            cards.append(flex.bubble("近期賽季紀錄", history_rows))
        return flex.carousel(cards)

    def command(self, command: str):
        command = command.strip()
        if command in {"商店", "夜市", "配件"}:
            card = self.store_cards(self.riot.storefront(), command)
        elif command == "錢包":
            card = self.wallet()
        elif command == "牌位":
            card = self.rank()
        elif command == "戰績":
            matches = self.riot.recent_matches()
            if matches:
                try:
                    updates = self.riot.competitive_updates(10)
                except Exception:
                    updates = []
                lookup = {x["MatchID"]: x for x in updates if x.get("MatchID")} if isinstance(updates, list) else {}
                return flex.messages([flex.summary_card(matches, self.riot.puuid),
                                      flex.carousel([flex.match_card(match, self.riot.puuid, self.assets,
                                                                     title=f"最近第 {i} 場",
                                                                     rr_update=lookup.get((match.get("matchInfo") or {}).get("matchId")))
                                                     for i, match in enumerate(matches, start=1)])],
                                     "Valorant · 最近五場戰績分析")
            card = flex.notice("戰績", "沒有近期對戰。")
        else:
            card = flex.menu()
        return flex.messages([card], "Valorant · " + command[:30])
