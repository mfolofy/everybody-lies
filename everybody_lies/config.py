"""Configuration paths and defaults. All overridable via environment variables."""

import os
from pathlib import Path


def get_config_dir() -> Path:
    """Get the everybody-lies config directory.

    Resolution order:
    1. $EVERYBODY_LIES_HOME
    2. $XDG_CONFIG_HOME/everybody-lies  (Linux/macOS XDG)
    3. ~/.everybody-lies                 (default)
    """
    if env_home := os.environ.get("EVERYBODY_LIES_HOME"):
        return Path(env_home)
    if xdg_home := os.environ.get("XDG_CONFIG_HOME"):
        return Path(xdg_home) / "everybody-lies"
    return Path.home() / ".everybody-lies"


def get_chart_path() -> Path:
    """Resolve chart.json path.

    1. $EVERYBODY_LIES_CHART          — explicit path
    2. <config_dir>/chart.json        — user override
    3. Bundled with package            — default
    """
    if env_path := os.environ.get("EVERYBODY_LIES_CHART"):
        return Path(env_path)
    user_path = get_config_dir() / "chart.json"
    if user_path.exists():
        return user_path
    return Path(__file__).resolve().parent / "chart.json"


# Backward compatibility alias — original name still works
get_review_board_path = get_chart_path


def get_reviews_dir() -> Path:
    """Directory for review reports."""
    return get_config_dir() / "reviews"


def get_stats_path() -> Path:
    """Path to review statistics JSON."""
    return get_config_dir() / "stats.json"


def get_dynamic_fellows_path() -> Path:
    """Path to persisted dynamic fellows."""
    return get_config_dir() / "dynamic_fellows.json"


def ensure_config_dir() -> Path:
    """Create config directory if it doesn't exist. Returns the path."""
    path = get_config_dir()
    path.mkdir(parents=True, exist_ok=True)
    (path / "reviews").mkdir(parents=True, exist_ok=True)
    return path
