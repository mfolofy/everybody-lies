"""Configuration paths and defaults. All overridable via environment variables."""

import json
import os
import subprocess
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


def get_local_chart_path() -> Path:
    """Path of the optional repo-level chart override, `.house/chart.local.json`.

    Resolved against the current git work tree root (so it works from any
    sub-directory), falling back to the current directory outside a repo.
    """
    try:
        top = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL, timeout=5,
        ).decode("utf-8", errors="replace").strip()
    except (OSError, subprocess.SubprocessError):
        top = ""
    root = Path(top) if top else Path.cwd()
    return root / ".house" / "chart.local.json"


def deep_merge(base, override):
    """Deep-merge `override` over `base` and return the result (inputs untouched).

    - dicts merge key by key; a key set to null in the override wins (resets it);
    - lists of objects that ALL carry an "id" merge by id (so one specialist can
      be tweaked without restating the whole list; new ids are appended);
    - any other value in the override replaces the base value.
    """
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = deep_merge(base[key], value) if key in base else value
        return merged
    if (isinstance(base, list) and isinstance(override, list)
            and all(isinstance(x, dict) and "id" in x for x in base + override)):
        merged_list = list(base)
        index = {item["id"]: i for i, item in enumerate(merged_list)}
        for item in override:
            if item["id"] in index:
                merged_list[index[item["id"]]] = deep_merge(merged_list[index[item["id"]]], item)
            else:
                merged_list.append(item)
        return merged_list
    return override


def apply_local_chart(chart: dict) -> dict:
    """Deep-merge `.house/chart.local.json` (if present) over a loaded chart.

    A malformed override raises ValueError: a silently ignored override would
    drop limits (round cap, daily cap) the repo owner asked for.
    """
    path = get_local_chart_path()
    if not path.is_file():
        return chart
    try:
        override = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(override, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return deep_merge(chart, override)


def load_chart() -> dict:
    """Load the effective chart: chart.json (see get_chart_path) + local override."""
    with open(get_chart_path(), encoding="utf-8") as f:
        return apply_local_chart(json.load(f))


def get_limit(chart: dict, key: str, env_var: str):
    """Resolve an optional integer limit from `chart["limits"][key]`.

    The environment variable wins over the chart. Unset/null, 0, "off" or
    "none" mean no limit (returns None). Anything else must be a positive
    integer, otherwise ValueError (never silently ignored).
    """
    raw = os.environ.get(env_var, "").strip()
    if not raw:
        raw = (chart or {}).get("limits", {}).get(key)
    if raw is None or str(raw).strip().lower() in ("", "0", "off", "none", "null"):
        return None
    try:
        value = int(str(raw).strip())
    except ValueError:
        raise ValueError(f"limit '{key}' must be a whole number, got {raw!r}") from None
    if value < 0:
        raise ValueError(f"limit '{key}' must not be negative, got {value}")
    return value or None


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


def get_appeals_log_path() -> Path:
    """Path to appeals.jsonl — audit log of all bypass appeals."""
    return get_reviews_dir() / "appeals.jsonl"


def get_commit_log_path() -> Path:
    """Path to house-commits.jsonl — one entry per commit that went through House.

    Each line is a JSON object:
    {
      "commit": "<sha>",          # git commit hash (short)
      "rfc_id": "RFC-...",        # House review that approved this commit
      "verdict": "APPROVED",      # APPROVED | BYPASSED
      "rounds": 2,                # how many review rounds it took
      "tier": "fast",
      "timestamp": "2026-...",
      "bypassed": false,          # true if --no-verify was used
      "bypass_reason": null       # set by post-commit hook if bypassed
    }
    """
    return get_reviews_dir() / "house-commits.jsonl"


def get_archive_dir() -> Path:
    """Directory for archived prior review rounds (preserved instead of deleted)."""
    archive = get_reviews_dir() / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    return archive


def ensure_config_dir() -> Path:
    """Create config directory if it doesn't exist. Returns the path."""
    path = get_config_dir()
    path.mkdir(parents=True, exist_ok=True)
    (path / "reviews").mkdir(parents=True, exist_ok=True)
    (path / "reviews" / "archive").mkdir(parents=True, exist_ok=True)
    return path
