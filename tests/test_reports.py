from unittest.mock import Mock

import pytest
from linebot.v3.messaging.exceptions import ApiException

from valbot import reports, flex
from valbot.storage import Vault
from tests.test_service import fake_riot
from tests.test_analysis import example_match

CONFIG = {"line_user_id": "owner-line"}


def baseline(tmp_path):
    vault, riot, line = Vault(tmp_path), fake_riot(), Mock()
    riot.match_history.return_value = [{"MatchID": "old"}]
    reports.poll(CONFIG, vault, riot, line, now=100)
    line.push.assert_not_called()
    return vault, riot, line


def test_only_new_completed_matches_report_once_in_order_across_restart(tmp_path):
    vault, riot, line = baseline(tmp_path)
    riot.match_history.return_value = [{"MatchID": "new2"}, {"MatchID": "new1"}, {"MatchID": "old"}]
    match = example_match()
    riot.match_detail.return_value = match
    reports.poll(CONFIG, vault, riot, line, now=160)
    assert [call.args[0] for call in riot.match_detail.call_args_list] == ["new1", "new2"]
    assert line.push.call_count == 2
    assert line.push.call_args.args[1][0]["contents"] == flex.menu()
    reports.poll(CONFIG, Vault(tmp_path), riot, line, now=220)
    assert line.push.call_count == 2


def test_incomplete_match_waits_until_details_ready(tmp_path):
    vault, riot, line = baseline(tmp_path)
    riot.match_history.return_value = [{"MatchID": "new"}, {"MatchID": "old"}]
    match = example_match()
    match["matchInfo"]["isCompleted"] = False
    riot.match_detail.return_value = match
    reports.poll(CONFIG, vault, riot, line, now=160)
    line.push.assert_not_called()
    match["matchInfo"]["isCompleted"] = True
    reports.poll(CONFIG, vault, riot, line, now=220)
    line.push.assert_called_once()


def test_ambiguous_timeout_retries_exact_payload_and_key_and_accepts_409(tmp_path):
    vault, riot, line = baseline(tmp_path)
    riot.match_history.return_value = [{"MatchID": "new"}, {"MatchID": "old"}]
    riot.match_detail.return_value = example_match()
    line.push.side_effect = TimeoutError()
    with pytest.raises(TimeoutError):
        reports.poll(CONFIG, vault, riot, line, now=160)
    first = line.push.call_args
    accepted = ApiException(status=409)
    accepted.headers = {"x-line-accepted-request-id": "request"}
    line.push.side_effect = accepted
    reports.poll(CONFIG, Vault(tmp_path), riot, line, now=220)
    assert line.push.call_args == first
    assert riot.match_detail.call_count == 1
    assert vault.read("report_state")["pending"] == {}


def test_disabled_and_reenabled_baseline_skips_old_games(tmp_path):
    vault, riot, line = baseline(tmp_path)
    reports.command(vault, "自動戰報關閉")
    riot.match_history.return_value = [{"MatchID": "during-off"}]
    reports.poll(CONFIG, vault, riot, line, now=160)
    line.push.assert_not_called()
    reports.command(vault, "自動戰報開啟")
    reports.poll(CONFIG, vault, riot, line, now=220)
    line.push.assert_not_called()


def test_account_or_recipient_change_never_replays_old_payload(tmp_path):
    vault, riot, line = baseline(tmp_path)
    reports.poll({"line_user_id": "different"}, vault, riot, line, now=160)
    line.push.assert_not_called()


def test_expired_retry_is_not_resent_after_line_key_expiry(tmp_path):
    vault, riot, line = baseline(tmp_path)
    riot.match_history.return_value = [{"MatchID": "new"}, {"MatchID": "old"}]
    riot.match_detail.return_value = example_match()
    line.push.side_effect = TimeoutError()
    with pytest.raises(TimeoutError):
        reports.poll(CONFIG, vault, riot, line, now=160)
    reports.poll(CONFIG, vault, riot, line, now=160 + 24 * 3600)
    assert line.push.call_count == 1
    assert vault.read("report_state")["pending"] == {}


def test_catchup_is_bounded_and_remaining_matches_are_delivered_next_poll(tmp_path):
    vault, riot, line = baseline(tmp_path)
    riot.match_history.return_value = [{"MatchID": f"new{i}"} for i in range(5, 0, -1)] + [{"MatchID": "old"}]
    riot.match_detail.return_value = example_match()
    reports.poll(CONFIG, vault, riot, line, now=160)
    assert line.push.call_count == 3
    reports.poll(CONFIG, vault, riot, line, now=220)
    assert line.push.call_count == 5
