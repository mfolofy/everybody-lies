import json
import os
import sys
import pytest
from unittest.mock import patch


def reset_gate_cache():
    import everybody_lies.gatekeeper as g
    g._HOUSE_GATE_CACHE = None


def test_parse_valid(monkeypatch):
    reset_gate_cache()
    monkeypatch.setenv("HOUSE_GATE", json.dumps({"subagents_running": False, "tier_floor": "standard"}))
    from everybody_lies.gatekeeper import _parse_house_gate
    result = _parse_house_gate()
    assert result["subagents_running"] is False
    assert result["tier_floor"] == "standard"


def test_parse_invalid_json(monkeypatch, capsys):
    reset_gate_cache()
    monkeypatch.setenv("HOUSE_GATE", "not-json{")
    from everybody_lies.gatekeeper import _parse_house_gate
    result = _parse_house_gate()
    assert result == {}
    captured = capsys.readouterr()
    assert "WARNING" in captured.err


def test_parse_not_dict(monkeypatch, capsys):
    reset_gate_cache()
    monkeypatch.setenv("HOUSE_GATE", "[1,2,3]")
    from everybody_lies.gatekeeper import _parse_house_gate
    result = _parse_house_gate()
    assert result == {}


def test_parse_empty(monkeypatch):
    reset_gate_cache()
    monkeypatch.delenv("HOUSE_GATE", raising=False)
    from everybody_lies.gatekeeper import _parse_house_gate
    assert _parse_house_gate() == {}


def test_subagents_declared_false_skips_scan(monkeypatch):
    reset_gate_cache()
    monkeypatch.setenv("HOUSE_GATE", json.dumps({"subagents_running": False}))
    monkeypatch.delenv("HOUSE_BYPASS", raising=False)
    with patch("everybody_lies.gatekeeper._count_running_opencode_subagents") as mock_count:
        from everybody_lies.gatekeeper import _check_no_running_subagents
        _check_no_running_subagents()
        mock_count.assert_not_called()


def test_subagents_declared_true_blocks(monkeypatch):
    reset_gate_cache()
    monkeypatch.setenv("HOUSE_GATE", json.dumps({"subagents_running": True}))
    monkeypatch.delenv("HOUSE_BYPASS", raising=False)
    from everybody_lies.gatekeeper import _check_no_running_subagents
    with pytest.raises(SystemExit) as exc:
        _check_no_running_subagents()
    assert exc.value.code == 1


def test_tier_floor_upgrades(monkeypatch):
    """HOUSE_GATE tier_floor='adversarial', file/risk floor='fast' → effective floor becomes adversarial.
    Requested tier='fast' → upgraded to 'adversarial'."""
    reset_gate_cache()
    monkeypatch.setenv("HOUSE_GATE", json.dumps({"tier_floor": "adversarial"}))
    from everybody_lies.gatekeeper import _parse_house_gate

    gate = _parse_house_gate()
    _tier_rank = {"fast": 0, "standard": 1, "adversarial": 2}

    # Simulate the merge logic from run_review()
    tier_floor = "fast"         # what _calculate_tier_floor() returned
    gate_tier = gate.get("tier_floor", "")
    if gate_tier and _tier_rank.get(gate_tier, 0) > _tier_rank.get(tier_floor, 0):
        tier_floor = gate_tier  # gate overrides the floor
    assert tier_floor == "adversarial"

    # Now simulate tier enforcement
    tier = "fast"               # what orchestrator requested
    if _tier_rank.get(tier_floor, 0) > _tier_rank.get(tier, 0):
        tier = tier_floor       # only upgrades, never downgrades
    assert tier == "adversarial"


def test_tier_floor_no_downgrade(monkeypatch):
    """HOUSE_GATE tier_floor='fast', requested='adversarial' → tier stays adversarial.
    tier_floor only upgrades, never downgrades."""
    reset_gate_cache()
    monkeypatch.setenv("HOUSE_GATE", json.dumps({"tier_floor": "fast"}))
    from everybody_lies.gatekeeper import _parse_house_gate

    gate = _parse_house_gate()
    _tier_rank = {"fast": 0, "standard": 1, "adversarial": 2}

    # Simulate the merge logic from run_review()
    tier_floor = "fast"         # what _calculate_tier_floor() returned
    gate_tier = gate.get("tier_floor", "")
    if gate_tier and _tier_rank.get(gate_tier, 0) > _tier_rank.get(tier_floor, 0):
        tier_floor = gate_tier
    # fast <= fast, so no override
    assert tier_floor == "fast"

    # Now simulate tier enforcement — requested is already higher
    tier = "adversarial"        # what orchestrator requested
    if _tier_rank.get(tier_floor, 0) > _tier_rank.get(tier, 0):
        tier = tier_floor
    else:
        pass  # no downgrade — tier stays adversarial
    assert tier == "adversarial"


def test_plan_authorized_is_parsed(monkeypatch):
    """plan_authorized key is accessible from HOUSE_GATE."""
    reset_gate_cache()
    ref = "SCOPE.md phase-2 step-3: full index.html rebuild"
    monkeypatch.setenv("HOUSE_GATE", json.dumps({"plan_authorized": ref}))
    from everybody_lies.gatekeeper import _parse_house_gate
    gate = _parse_house_gate()
    assert gate.get("plan_authorized") == ref


def test_cuddy_skip_is_parsed(monkeypatch):
    """cuddy_skip key is accessible from HOUSE_GATE."""
    reset_gate_cache()
    monkeypatch.setenv("HOUSE_GATE", json.dumps({"cuddy_skip": True}))
    from everybody_lies.gatekeeper import _parse_house_gate
    gate = _parse_house_gate()
    assert gate.get("cuddy_skip") is True


def test_neither_key_set_means_no_skip(monkeypatch):
    """When neither plan_authorized nor cuddy_skip is set, both evaluate falsy."""
    reset_gate_cache()
    monkeypatch.setenv("HOUSE_GATE", json.dumps({"tier_floor": "standard"}))
    from everybody_lies.gatekeeper import _parse_house_gate
    gate = _parse_house_gate()
    _plan_auth = gate.get("plan_authorized", "")
    _cuddy_skip = gate.get("cuddy_skip", False)
    assert not _plan_auth
    assert not _cuddy_skip
