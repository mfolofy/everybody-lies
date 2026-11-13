"""Optional daily model-call cap: counted in stats.json, fails closed. All calls mocked."""
import json

import pytest

import everybody_lies.gatekeeper as g
from everybody_lies.budget import BudgetExceeded, calls_today, check_and_record_call
from everybody_lies.config import get_stats_path
from everybody_lies.providers import call_llm
from conftest import DIFF


def test_no_cap_means_no_counting_and_no_stats_file(house_home, fake_claude, monkeypatch):
    monkeypatch.setenv("EVERYBODY_LIES_PROVIDER", "claude-code")
    for _ in range(5):
        call_llm("claude-sonnet-5-5", "s", "u")
    assert len(fake_claude) == 5
    assert not get_stats_path().exists()


def test_cap_stops_before_the_next_call_and_says_how_to_override(house_home, fake_claude, monkeypatch):
    monkeypatch.setenv("EVERYBODY_LIES_PROVIDER", "claude-code")
    monkeypatch.setenv("EVERYBODY_LIES_DAILY_CALL_CAP", "2")
    call_llm("claude-sonnet-5-5", "s", "u")
    call_llm("claude-sonnet-5-5", "s", "u")
    with pytest.raises(BudgetExceeded) as exc:
        call_llm("claude-sonnet-5-5", "s", "u")
    assert len(fake_claude) == 2  # the third call never reached the CLI
    msg = str(exc.value)
    assert "2 of 2" in msg and "EVERYBODY_LIES_DAILY_CALL_CAP" in msg and "chart.local.json" in msg
    assert calls_today() == 2


def test_counts_live_in_existing_stats_store_and_keep_other_data(house_home, monkeypatch):
    monkeypatch.setenv("EVERYBODY_LIES_DAILY_CALL_CAP", "5")
    stats = get_stats_path()
    stats.parent.mkdir(parents=True, exist_ok=True)
    stats.write_text(json.dumps({"reviews": [{"rfc_id": "RFC-1"}]}), encoding="utf-8")
    check_and_record_call()
    data = json.loads(stats.read_text(encoding="utf-8"))
    assert data["reviews"] == [{"rfc_id": "RFC-1"}]
    assert list(data["usage"].values()) == [{"calls": 1}]


def test_old_days_are_pruned_and_a_new_day_starts_at_zero(house_home, monkeypatch):
    monkeypatch.setenv("EVERYBODY_LIES_DAILY_CALL_CAP", "1")
    stats = get_stats_path()
    stats.parent.mkdir(parents=True, exist_ok=True)
    old = {f"2020-01-{d:02d}": {"calls": 99} for d in range(1, 21)}
    stats.write_text(json.dumps({"usage": old}), encoding="utf-8")
    check_and_record_call()  # yesterday's 99 do not count today
    usage = json.loads(stats.read_text(encoding="utf-8"))["usage"]
    assert len(usage) == 14 and calls_today() == 1


def test_zero_or_off_disables_the_cap(house_home, monkeypatch):
    monkeypatch.setenv("EVERYBODY_LIES_DAILY_CALL_CAP", "0")
    for _ in range(3):
        check_and_record_call()
    assert not get_stats_path().exists()


def test_cap_from_local_chart(house_home, monkeypatch):
    home, work = house_home
    (work / ".house").mkdir()
    (work / ".house" / "chart.local.json").write_text(json.dumps({"limits": {"daily_call_cap": 1}}), encoding="utf-8")
    check_and_record_call()
    with pytest.raises(BudgetExceeded):
        check_and_record_call()


def test_run_review_fails_closed_never_degraded_approve(house_home, fake_claude, monkeypatch, capsys):
    """Cap of 1: Cuddy uses the only call, the specialist hits the cap. Must be BLOCKED,
    not the 'all providers down -> APPROVED (DEGRADED)' path."""
    monkeypatch.setenv("EVERYBODY_LIES_PROVIDER", "claude-code")
    monkeypatch.setenv("EVERYBODY_LIES_DAILY_CALL_CAP", "1")
    result = g.run_review(diff_text=DIFF, files=["app/mod.py"], title="capped", tier="fast", tier_explicit=True)
    assert result["verdict"] == "BLOCKED"
    assert result["status"] == "budget_exceeded"
    assert "EVERYBODY_LIES_DAILY_CALL_CAP" in result["reason"]
    assert len(fake_claude) == 1
    out = capsys.readouterr().out
    assert "BLOCKED" in out and "NOT approved" in out


def test_cli_exit_code_is_nonzero_for_blocked_and_stuck(monkeypatch):
    import sys
    import everybody_lies.cli as cli
    for verdict in ("BLOCKED", "STUCK"):
        monkeypatch.setattr(cli, "run_review", lambda **kw: {"verdict": verdict})
        monkeypatch.setattr(sys, "argv", ["everybody-lies", "--diff", "x"])
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 1
