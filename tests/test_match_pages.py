import json
from unittest.mock import Mock

import httpx
import pytest

from valbot import flex
from valbot.assets import Assets
from valbot.line import LineClient
from valbot.riot import RiotClient, DataError
from valbot.service import BotService, is_match_command
from valbot.app import process_event
from valbot.storage import Vault
from tests.test_analysis import example_match
from tests.test_service import fake_riot


def test_page_can_go_past_100_matches_and_preserves_missing_detail_position(monkeypatch):
    monkeypatch.setattr(Assets, "get", lambda self, path: {"riotClientVersion": "version"})
    def handler(request):
        if "match-history" in request.url.path:
            assert request.url.params["startIndex"] == "260"
            assert request.url.params["endIndex"] == "271"
            return httpx.Response(200, json={"BeginIndex": 260, "Total": 347,
                                            "History": [{"MatchID": str(i)} for i in range(260, 271)]})
        mid = request.url.path.rsplit("/", 1)[1]
        return httpx.Response(404 if mid == "264" else 200, json={"matchInfo": {"matchId": mid}})
    auth = Mock()
    auth.session.return_value = {"puuid": "owner", "access_token": "access", "entitlements_token": "ent"}
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        result = RiotClient({"region": "ap"}, auth, http).matches_page(start=260)
    assert [item["id"] for item in result["items"]] == [str(i) for i in range(260, 270)]
    assert result["items"][4]["match"] is None
    assert result["total"] == 347 and result["has_next"]


def test_missing_total_uses_lookahead_and_ignoring_start_does_not_loop(monkeypatch):
    riot = RiotClient.__new__(RiotClient)
    riot.puuid = "owner"
    riot.request = Mock(return_value={"History": [{"MatchID": str(i)} for i in range(11)]})
    riot.match_detail = Mock(return_value={})
    assert riot.matches_page()["has_next"]
    riot.request.return_value = {"BeginIndex": 0, "History": [{"MatchID": "old"}]}
    with pytest.raises(DataError):
        riot.matches_page(start=10)


def test_ten_detailed_cards_split_payloads_and_show_page_controls():
    riot = fake_riot()
    riot.assets.lookup.return_value = {"displayName": "特務", "displayIcon": "https://example.com/agent.png"}
    riot.assets.map.return_value = {"displayName": "地圖", "splash": "https://example.com/map.png"}
    match = example_match()
    riot.matches_page.return_value = {"items": [{"id": str(i), "match": match} for i in range(10)],
                                     "total": 235, "has_next": True}
    messages = BotService(riot).command("戰績 2")
    riot.matches_page.assert_called_once_with(start=10, limit=10)
    assert len(messages) == 3
    assert [len(x["contents"]["contents"]) for x in messages[1:]] == [5, 5]
    content = json.dumps(messages, ensure_ascii=False)
    assert "戰績 1" in content and "戰績 3" in content and "235" in content
    assert "最近第 11 場" in content and "最近第 20 場" in content
    LineClient.models(flex.messages([flex.menu()]) + messages)


def test_last_partial_page_has_no_next_button_and_no_fake_missing_match_stats():
    riot = fake_riot()
    riot.matches_page.return_value = {"items": [{"id": "missing", "match": None}],
                                     "total": 21, "has_next": False}
    messages = BotService(riot).command("戰績 3")
    content = json.dumps(messages, ensure_ascii=False)
    assert "戰績 2" in content and "下一頁" not in content
    assert "最近第 21 場" in content and "K / D / A" not in content
    LineClient.models(messages)


def test_match_page_command_takes_priority_over_private_message_composition(tmp_path, monkeypatch):
    import valbot.app as app_module
    vault, line, service = Vault(tmp_path), Mock(), Mock()
    config = {"line_user_id": "owner-line", "riot_puuid": "owner"}
    vault.write("friend_dm", {"identity": "owner:owner-line", "status": "composing", "created_at": 9999999999})
    monkeypatch.setattr(app_module, "RiotClient", Mock())
    monkeypatch.setattr(app_module, "BotService", Mock(return_value=service))
    service.command.return_value = flex.messages([flex.notice("戰績", "第二頁")])
    event = {"type": "message", "replyToken": "reply", "source": {"type": "user", "userId": "owner-line"},
             "message": {"text": "戰績 2"}}
    process_event(event, config, vault, line)
    service.command.assert_called_once_with("戰績 2")
    assert vault.read("friend_dm")["status"] == "composing"
    assert line.reply.call_args.args[1][0]["contents"] == flex.menu()


@pytest.mark.parametrize("command", ["戰績 0", "戰績 -1", "戰績 x", "戰績 1000000"])
def test_invalid_match_page_is_not_requested(command):
    assert not is_match_command(command)
