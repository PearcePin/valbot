from unittest.mock import Mock

import httpx
import pytest

from valbot.assets import Assets
from valbot import flex
from valbot.line import LineClient


@pytest.mark.parametrize("uuid", ["skin", "level", "chroma"])
def test_skin_children_inherit_parent_tier_and_shop_night_share_background(uuid):
    assets = Assets(Mock())
    assets.memory = {"weapons/skins": [{"uuid": "skin", "displayName": "造型", "contentTierUuid": "tier",
        "levels": [{"uuid": "level"}], "chromas": [{"uuid": "chroma", "fullRender": "https://example.com/weapon.png"}]}],
        "contenttiers": [{"uuid": "tier", "displayName": "尊爵", "highlightColor": "d1548d33",
                          "displayIcon": "https://example.com/tier.png"}]}
    item = assets.item(uuid)
    assert item["tier_color"] == "#D1548D"
    for section in ("商店", "夜市"):
        card = flex.item_card({**item, "price": 1775, "original": 2000, "discount": 20, "currency": "VP"}, section)
        assert card["hero"]["backgroundColor"] == "#D1548D"
        LineClient.models(flex.messages([card]))


def test_missing_tier_metadata_preserves_weapon_and_uses_default_background():
    client = Mock()
    client.get.side_effect = httpx.ConnectError("unavailable")
    assets = Assets(client)
    assets.memory = {"weapons/skins": [{"uuid": "skin", "displayName": "造型", "contentTierUuid": "missing",
                                      "displayIcon": "https://example.com/weapon.png"}]}
    # Avoid relying on an existing on-disk contenttiers cache.
    assets.lookup = Mock(side_effect=httpx.ConnectError("unavailable"))
    item = assets.item("skin")
    assert item["image"] == "https://example.com/weapon.png"
    assert flex.item_card(item, "商店")["hero"]["backgroundColor"] == flex.PANEL
