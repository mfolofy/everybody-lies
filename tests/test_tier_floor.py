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
