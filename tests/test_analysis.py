from copy import deepcopy
import json

from valbot.analysis import match_stats, recent_summary
from valbot import flex
from valbot.line import LineClient
from tests.test_service import fake_riot


def example_match():
    return {"matchInfo": {"isCompleted": True, "queueID": "competitive"},
            "players": [{"subject": "owner", "teamId": "Red", "stats": {
                "kills": 2, "deaths": 1, "assists": 1, "score": 500, "roundsPlayed": 2}},
                {"subject": "enemy", "teamId": "Blue", "stats": {"score": 300, "roundsPlayed": 2}}],
            "teams": [{"teamId": "Red", "won": True, "roundsWon": 2},
                      {"teamId": "Blue", "won": False, "roundsWon": 0}],
            "roundResults": [
                {"bombPlanter": "owner", "playerStats": [
                    {"subject": "owner", "damage": [{"damage": 200, "headshots": 1, "bodyshots": 3, "legshots": 0}],
                     "kills": [{"killer": "owner", "victim": "enemy", "roundTime": 1000},
                               {"killer": "owner", "victim": "enemy2", "roundTime": 2000}], "economy": {"spent": 1000}},
                    {"subject": "enemy", "kills": []}]},
                {"bombDefuser": "owner", "playerStats": [
                    {"subject": "owner", "damage": [{"damage": 100, "headshots": 1, "bodyshots": 0, "legshots": 0}],
                     "kills": [], "economy": {"spent": 3000}},
                    {"subject": "enemy", "kills": [{"killer": "enemy", "victim": "owner", "roundTime": 500}]}]}]}


def test_round_damage_aim_opening_duels_objectives_and_economy():
    match = example_match()
    stats = match_stats(match, "owner")
    assert (stats["acs"], stats["adr"], stats["hs"], stats["kd"]) == (250, 150, 40, 2)
    assert (stats["first_kills"], stats["first_deaths"], stats["plants"], stats["defuses"]) == (1, 1, 1, 1)
    assert stats["multikills"][2] == 1 and stats["best_round"] == 2
    assert stats["spent"] == 2000 and stats["position"] == 1
    card = flex.match_card(match, "owner", fake_riot().assets)
    LineClient.models(flex.messages([card]))


def test_sparse_rounds_and_missing_kda_never_claim_zero():
    match = example_match()
    match["roundResults"].pop()
    match["players"][0]["stats"].pop("kills")
    stats = match_stats(match, "owner")
    assert stats["adr"] is None and stats["hs"] is None
    assert stats["first_kills"] is None and stats["multikills"] is None
    assert recent_summary([match], "owner")["kills"] is None


def test_summary_weights_by_rounds_and_hits_not_per_game_means():
    first = example_match()
    second = deepcopy(first)
    second["players"][0]["stats"].update(score=3000, roundsPlayed=10)
    # Missing round coverage should make aggregate ADR unknown.
    summary = recent_summary([first, second], "owner")
    assert summary["acs"] == 291.7 and summary["adr"] is None
    assert summary["wins"] == 2


def test_high_rank_rr_is_not_a_fake_100_point_promotion_bar():
    from valbot.service import BotService
    riot = fake_riot()
    riot.assets.rank.return_value = {"tierName": "神話 I"}
    riot.content.return_value = {"Seasons": [{"ID": "now", "Type": "act", "Name": "本季", "IsActive": True}]}
    riot.mmr.return_value = {"QueueSkills": {"competitive": {"SeasonalInfoBySeasonID": {
        "now": {"CompetitiveTier": 24, "RankedRating": 350, "NumberOfGames": 20,
                "NumberOfWinsWithPlacements": 12, "LeaderboardRank": 100, "GamesNeededForRating": 0}}}}}
    riot.competitive_updates.return_value = [{"MatchID": "last", "SeasonID": "now", "RankedRatingEarned": -10,
                                            "RankedRatingAfterUpdate": 350, "RankedRatingBeforeUpdate": 360,
                                            "RankedRatingPerformanceBonus": 0, "AFKPenalty": 0}]
    cards = BotService(riot).rank()
    content = json.dumps(cards, ensure_ascii=False)
    assert "350 RR" in content and "60.0%" in content and "-10 RR" in content
    assert "RR 進度" not in content and "排行榜第 100 名" in content
    LineClient.models(flex.messages([cards]))


def test_five_detailed_cards_with_rr_fit_line_payload_and_missing_optional_rr_is_safe():
    from valbot.service import BotService
    riot = fake_riot()
    riot.assets.lookup.return_value = {"displayName": "測試特務", "displayIcon": "https://example.com/agent.png"}
    riot.assets.map.return_value = {"displayName": "測試地圖", "splash": "https://example.com/map.png"}
    matches = []
    updates = []
    for i in range(5):
        match = example_match()
        match["matchInfo"].update(matchId=str(i), gameStartMillis=1700000000000, gameLengthMillis=1800000)
        match["players"][0]["stats"]["abilityCasts"] = {"grenadeCasts": 10, "ability1Casts": 15,
                                                       "ability2Casts": 20, "ultimateCasts": 3}
        matches.append(match)
        updates.append({"MatchID": str(i), "RankedRatingEarned": 20, "RankedRatingAfterUpdate": 80,
                        "RankedRatingBeforeUpdate": 60, "RankedRatingPerformanceBonus": 3, "AFKPenalty": 0})
    riot.matches_page.return_value = {"items": [{"id": str(i), "match": m} for i, m in enumerate(matches)],
                                     "total": 5, "has_next": False}
    riot.competitive_updates.return_value = updates
    messages = BotService(riot).command("戰績")
    assert len(messages) == 2
    assert "本場競技積分 +20 RR" in json.dumps(messages, ensure_ascii=False)
    assert len(json.dumps(messages[-1]["contents"], ensure_ascii=False).encode()) < 50000
    LineClient.models(messages)
    riot.competitive_updates.side_effect = RuntimeError()
    assert len(BotService(riot).command("戰績")) == 2
