"""Optional daily cap on model calls, counted in the existing stats store.

Off by default. Turn it on with `limits.daily_call_cap` in chart.json (or the
repo-level `.house/chart.local.json`) or the EVERYBODY_LIES_DAILY_CALL_CAP
environment variable (the variable wins; 0 or "off" means no cap).

The count lives in stats.json under "usage" (one entry per UTC day, the last
14 days kept). Calls are only counted while a cap is set. The cap fails CLOSED:
when it is hit, call_llm raises BudgetExceeded before the next model call and
the gatekeeper blocks the review. It never degrades to an approval.

Tokens are not capped: House only passes a max_tokens ceiling to the provider
and does not estimate usage, so there is nothing reliable to count.
"""

import json
import os
from datetime import datetime, timezone

from .config import get_stats_path, load_chart, get_limit

CAP_ENV_VAR = "EVERYBODY_LIES_DAILY_CALL_CAP"
_KEEP_DAYS = 14


class BudgetExceeded(RuntimeError):
    """The daily model-call cap is used up. Must block, never pass."""


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def get_daily_call_cap() -> int | None:
    """Return the configured daily call cap, or None when no cap is set."""
    try:
        chart = load_chart()
    except (OSError, ValueError):
        chart = {}  # run_review already validated the chart; do not mask a call here
    return get_limit(chart, "daily_call_cap", CAP_ENV_VAR)


def _read_stats() -> dict:
    path = get_stats_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def calls_today() -> int:
    """Number of model calls counted so far today (UTC)."""
    usage = _read_stats().get("usage", {})
    return int(usage.get(_today(), {}).get("calls", 0))


def check_and_record_call() -> None:
    """Gate one model call. Raises BudgetExceeded when the cap is used up.

    No cap set: does nothing (no stats file is touched).
    """
    cap = get_daily_call_cap()
    if cap is None:
        return
    stats = _read_stats()
    usage = stats.setdefault("usage", {})
    today = _today()
    used = int(usage.get(today, {}).get("calls", 0))
    if used >= cap:
        raise BudgetExceeded(
            f"Daily model-call cap reached: {used} of {cap} calls used today (UTC). "
            f"Blocked, not approved. To continue: raise the cap with "
            f"{CAP_ENV_VAR}=<higher number> (0 = no cap) or limits.daily_call_cap "
            f"in .house/chart.local.json. The count resets at 00:00 UTC."
        )
    usage[today] = {"calls": used + 1}
    for day in sorted(usage)[:-_KEEP_DAYS]:
        del usage[day]
    path = get_stats_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    os.replace(tmp, path)
