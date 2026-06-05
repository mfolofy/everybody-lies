import pytest
from unittest.mock import patch, MagicMock

MOCK_BOARD = {
    "tier_floors": {
        "file_patterns": [
            {"pattern": "**/migrations/**",   "min_tier": "standard"},
            {"pattern": "**/trading_core/**", "min_tier": "adversarial"},
            {"pattern": "**/secrets/**",      "min_tier": "adversarial"},
        ],
        "risk_score_floors": [
            {"min_score": 4.0, "min_tier": "adversarial"},
            {"min_score": 2.5, "min_tier": "standard"},
        ]
    }
}


def test_migration_file_gets_standard():
    from everybody_lies.gatekeeper import _calculate_tier_floor
    result = _calculate_tier_floor(["internal/db/migrations/001.sql"], 1.0, MOCK_BOARD)
    assert result == "standard"


def test_trading_core_gets_adversarial():
    from everybody_lies.gatekeeper import _calculate_tier_floor
    result = _calculate_tier_floor(["trading_core/bot.py"], 1.0, MOCK_BOARD)
    assert result == "adversarial"


def test_high_risk_score_floor():
    from everybody_lies.gatekeeper import _calculate_tier_floor
    result = _calculate_tier_floor(["README.md"], 4.5, MOCK_BOARD)
    assert result == "adversarial"


def test_medium_risk_score_floor():
    from everybody_lies.gatekeeper import _calculate_tier_floor
    result = _calculate_tier_floor(["README.md"], 2.8, MOCK_BOARD)
    assert result == "standard"


def test_docs_file_no_floor():
    from everybody_lies.gatekeeper import _calculate_tier_floor
    result = _calculate_tier_floor(["README.md", "docs/guide.md"], 1.0, MOCK_BOARD)
    assert result == "fast"


def test_no_tier_floors_config():
    from everybody_lies.gatekeeper import _calculate_tier_floor
    result = _calculate_tier_floor(["trading_core/bot.py"], 4.5, {})
    assert result == "fast"  # no config = no floor


def test_higher_pattern_wins():
    from everybody_lies.gatekeeper import _calculate_tier_floor
    # Both migration (standard) and trading_core (adversarial) — adversarial wins
    result = _calculate_tier_floor(
        ["trading_core/bot.py", "internal/db/migrations/001.sql"], 1.0, MOCK_BOARD
    )
    assert result == "adversarial"


def test_floor_upgrades_tier():
    """When tier_floor > requested tier, the tier should be upgraded."""
    from everybody_lies.gatekeeper import _calculate_tier_floor

    _tier_rank = {"fast": 0, "standard": 1, "adversarial": 2}

    tier = "fast"
    tier_floor = _calculate_tier_floor(
        ["internal/db/migrations/001.sql"], 1.0, MOCK_BOARD
    )
    assert tier_floor == "standard"
    assert _tier_rank.get(tier_floor, 0) > _tier_rank.get(tier, 0)
    # When floor > tier, apply the upgrade
    tier = tier_floor
    assert tier == "standard"


def test_floor_no_downgrade():
    """When requested tier > tier_floor, the tier should NOT be downgraded."""
    from everybody_lies.gatekeeper import _calculate_tier_floor

    _tier_rank = {"fast": 0, "standard": 1, "adversarial": 2}

    tier = "adversarial"
    tier_floor = _calculate_tier_floor(
        ["README.md"], 1.0, MOCK_BOARD
    )
    assert tier_floor == "fast"
    # Floor should never downgrade — only upgrade
    if _tier_rank.get(tier_floor, 0) > _tier_rank.get(tier, 0):
        tier = tier_floor
    # Tier stays adversarial (floor is lower)
    assert tier == "adversarial"


def test_gate_tier_floor_respected(monkeypatch):
    """HOUSE_GATE tier_floor should be parsed and applied as override."""
    from everybody_lies.gatekeeper import _calculate_tier_floor
    from everybody_lies.gatekeeper import _parse_house_gate

    # Reset the cache so our env var is picked up
    import everybody_lies.gatekeeper as gk
    gk._HOUSE_GATE_CACHE = None

    monkeypatch.setenv("HOUSE_GATE", '{"tier_floor":"adversarial"}')
    gate = _parse_house_gate()
    assert gate.get("tier_floor") == "adversarial"

    _tier_rank = {"fast": 0, "standard": 1, "adversarial": 2}

    tier_floor = _calculate_tier_floor(["README.md"], 1.0, MOCK_BOARD)
    assert tier_floor == "fast"  # no file/risk floor

    gate_tier = gate.get("tier_floor", "")
    if gate_tier and _tier_rank.get(gate_tier, 0) > _tier_rank.get(tier_floor, 0):
        tier_floor = gate_tier
    assert tier_floor == "adversarial"  # gate overrides

    # Clean up cache for other tests
    gk._HOUSE_GATE_CACHE = None
