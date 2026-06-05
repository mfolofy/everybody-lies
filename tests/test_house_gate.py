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
