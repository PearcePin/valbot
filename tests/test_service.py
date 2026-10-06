from unittest.mock import Mock
import pytest

from linebot.v3.messaging import FlexMessage

from valbot import flex
from valbot.line import LineClient
from valbot.riot import VP, KC, offer_item
from valbot.service import BotService


def offer(uuid, amount=1775, currency=VP):
    return {"OfferID": uuid, "Cost": {currency: amount}, "Rewards": [{"ItemID": uuid}]}


def fake_riot():
    riot = Mock()
    riot.puuid = "owner"
    riot.assets.item.side_effect = lambda uuid: {"name": "測試物品 " + uuid,
                                                "image": "https://media.valorant-api.com/example.png"}
    riot.assets.lookup.return_value = {"displayName": "精選包", "displayIcon": "https://example.com/bundle.png"}
    return riot


def test_night_market_discount_and_accessory_currency():
    riot = fake_riot()
    night = offer_item({"Offer": offer("skin"), "DiscountPercent": 30, "DiscountCosts": {VP: 1243}}, riot.assets)
    assert (night["original"], night["price"], night["discount"]) == (1775, 1243, 30)
    accessory = offer_item({"Offer": offer("card", 4500, KC)}, riot.assets)
    assert accessory["currency"] == "KC"


def test_daily_contains_all_sections_and_valid_sdk_flex():
    riot = fake_riot()
    riot.storefront.return_value = {
        "SkinsPanelLayout": {"SingleItemStoreOffers": [offer(str(i)) for i in range(4)]},
        "AccessoryStore": {"AccessoryStoreOffers": [{"Offer": offer("card", 4000, KC)}]},
        "FeaturedBundle": {"Bundles": [{"DataAssetID": "bundle", "TotalDiscountedCost": {VP: 7100},
                                         "TotalBaseCost": {VP: 9000}}]},
        "BonusStore": {"BonusStoreOffers": [{"Offer": offer(str(i)), "DiscountCosts": {VP: 1000},
                                             "DiscountPercent": 40} for i in range(6)]}}
    messages = BotService(riot).daily()
    assert len(messages) == 4
    assert [len(x["contents"]["contents"]) for x in messages] == [4, 1, 1, 6]
    assert all(isinstance(model, FlexMessage) for model in LineClient.models(messages))


def test_closed_night_market_not_in_daily():
    riot = fake_riot()
    riot.storefront.return_value = {}
    assert len(BotService(riot).daily()) == 3
    assert BotService(riot).store_cards({}, "夜市")["header"]["contents"][1]["text"] == "夜市尚未開放"


def test_match_uses_own_team_and_correct_acs():
    riot = fake_riot()
    riot.assets.map.return_value = {"displayName": "蓮華古城", "splash": "https://example.com/map.png"}
    riot.assets.lookup.return_value = {"displayName": "Jett", "displayIcon": "https://example.com/agent.png"}
    match = {"matchInfo": {"mapId": "map", "queueID": "competitive"}, "players": [
        {"subject": "owner", "teamId": "Red", "characterId": "agent",
         "stats": {"kills": 20, "deaths": 12, "assists": 4, "score": 5000, "roundsPlayed": 20}}],
        "teams": [{"teamId": "Blue", "roundsWon": 7, "won": False},
                  {"teamId": "Red", "roundsWon": 13, "won": True}]}
    card = flex.match_card(match, "owner", riot.assets)
    overlay = card["hero"]["contents"][1]
    assert overlay["position"] == "absolute"
    assert overlay["contents"][0]["text"] == "勝利"
    assert overlay["contents"][1]["text"] == "13 : 7"
    assert card["body"]["contents"][1]["contents"][1]["contents"][1]["text"] == "250"
    LineClient.models(flex.messages([card]))


def test_missions_use_public_objective_uuid_and_goal():
    riot = fake_riot()
    riot.contracts.return_value = {"Missions": [{"ID": "mission", "Objectives": {"objective": 25}}]}
    riot.assets.get.return_value = [{"uuid": "mission", "title": "造成傷害", "xpGrant": 12000,
                                     "objectives": [{"objectiveUuid": "objective", "value": 100}]}]
    card = BotService(riot).missions()["contents"][0]
    assert card["header"]["contents"][1]["text"] == "造成傷害"
    assert card["body"]["contents"][1]["contents"][1]["text"] == "25 / 100"
    LineClient.models(flex.messages([card]))


def test_current_rank_does_not_use_last_seasons_rank():
    riot = fake_riot()
    riot.content.return_value = {"Seasons": [{"ID": "current", "Type": "act", "IsActive": True}]}
    riot.mmr.return_value = {"QueueSkills": {"competitive": {"SeasonalInfoBySeasonID": {
        "old": {"CompetitiveTier": 24, "RankedRating": 90}}}},
        "LatestCompetitiveUpdate": {"MatchID": "last", "SeasonID": "old", "RankedRatingEarned": 20}}
    riot.assets.rank.return_value = {"tierName": "未定級"}
    BotService(riot).rank()
    riot.assets.rank.assert_called_once_with(0)


@pytest.mark.parametrize("count", [0, 2, 5])
def test_recent_match_carousel_handles_available_history(count):
    riot = fake_riot()
    riot.assets.map.return_value = {}
    riot.assets.lookup.return_value = {}
    match = {"matchInfo": {"queueID": "competitive"}, "players": [
        {"subject": "owner", "teamId": "Red", "stats": {"score": 2000, "roundsPlayed": 10}}]}
    riot.recent_matches.return_value = [match] * count
    messages = BotService(riot).command("戰績")
    contents = messages[0]["contents"]
    if count:
        assert contents["type"] == "carousel"
        assert len(contents["contents"]) == count
        assert contents["contents"][0]["header"]["contents"][1]["text"] == "最近第 1 場 · competitive"
    else:
        assert contents["type"] == "bubble"
    LineClient.models(messages)
