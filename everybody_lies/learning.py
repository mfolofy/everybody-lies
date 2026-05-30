"""Learning engine — dismissal tracking + cross-review problem detection.

Two unique features nobody else has:
1. Dismissal learning: tracks which findings get ignored → auto-suggests suppression
2. Cross-review problem detection: ITIL problem management across reviews
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import get_config_dir


# ── Suppression Rules ─────────────────────────────────────────────────────────

SUPPRESS_PATH = get_config_dir() / "suppress.toml"  # user-defined suppressions
DISMISSALS_PATH = get_config_dir() / "dismissals.json"  # auto-tracked dismissals


def load_suppression_rules() -> dict[str, set[str]]:
    """Load user-defined suppression rules.

    Returns: {rule_name: set of file_patterns} to suppress.
    Empty dict if no suppression file exists.
    """
    path = get_config_dir() / "suppress.toml"
    if not path.exists():
        return {}

    rules: dict[str, set[str]] = {}
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib
        except ImportError:
            # No TOML parser available — fall back to simple line-based format
            content = path.read_text(encoding="utf-8")
            for line in content.split("\n"):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("=")
                if len(parts) == 2:
                    rule = parts[0].strip()
                    pattern = parts[1].strip().strip('"').strip("'")
                    rules.setdefault(rule, set()).add(pattern)
            return rules

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        for rule_name, patterns in data.get("suppress", {}).items():
            if isinstance(patterns, list):
                rules[rule_name] = set(patterns)
            elif isinstance(patterns, str):
                rules[rule_name] = {patterns}
    except Exception:
        pass

    return rules


def is_suppressed(rule_name: str, file_path: str,
                  suppression_rules: Optional[dict[str, set[str]]] = None) -> bool:
    """Check if a finding should be suppressed based on rules.

    Args:
        rule_name: The rule that fired (e.g., 'trailing-whitespace')
        file_path: The file path the finding is in
        suppression_rules: Pre-loaded rules dict, or None to load from disk

    Returns:
        True if this finding should be suppressed (not reported)
    """
    if suppression_rules is None:
        suppression_rules = load_suppression_rules()

    if not suppression_rules:
        return False

    # Check exact rule match
    patterns = suppression_rules.get(rule_name, set())
    if "*" in patterns:
        return True

    for pattern in patterns:
        import fnmatch
        if fnmatch.fnmatch(file_path, pattern):
            return True

    return False


def track_dismissal(rule_name: str, finding_text: str) -> dict:
    """Track a dismissal of a finding. Called when user dismisses a finding.

    Returns updated dismissal stats for that rule.
    """
    dismissals = {}
    if DISMISSALS_PATH.exists():
        try:
            dismissals = json.loads(DISMISSALS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    entry = dismissals.setdefault(rule_name, {
        "count": 0,
        "last_dismissed": None,
        "examples": [],
    })
    entry["count"] += 1
    entry["last_dismissed"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if finding_text[:200] not in entry["examples"]:
        entry["examples"].append(finding_text[:200])
    entry["examples"] = entry["examples"][-3:]  # keep last 3

    DISMISSALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    DISMISSALS_PATH.write_text(json.dumps(dismissals, indent=2), encoding="utf-8")

    return entry


def get_suppression_suggestions(threshold: int = 3) -> list[str]:
    """Get rules that have been dismissed enough times to suggest suppression.

    Args:
        threshold: Number of dismissals before suggesting suppression

    Returns:
        List of rule names that should be considered for suppression
    """
    if not DISMISSALS_PATH.exists():
        return []

    try:
        dismissals = json.loads(DISMISSALS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []

    suggestions = []
    for rule_name, data in dismissals.items():
        if data.get("count", 0) >= threshold:
            suggestions.append(rule_name)

    return sorted(suggestions)


def format_suppression_suggestions() -> str:
    """Format suppression suggestions for display in House's synthesis."""
    suggestions = get_suppression_suggestions()
    if not suggestions:
        return ""

    lines = ["## Housekeeping: Consider Suppressing These Rules", ""]
    existing = load_suppression_rules()

    for rule in suggestions:
        if rule in existing and "*" in existing[rule]:
            continue  # already fully suppressed
        lines.append(
            f"- **{rule}**: dismissed {_get_dismissal_count(rule)} times. "
            f"Add `{rule} = \"*\"` to `~/.everybody-lies/suppress.toml` to suppress."
        )

    lines.append("")
    lines.append("*Less noise = more signal. Even House knows when to stop talking.*")
    return "\n".join(lines)


def _get_dismissal_count(rule_name: str) -> int:
    """Get dismissal count for a rule."""
    if not DISMISSALS_PATH.exists():
        return 0
    try:
        dismissals = json.loads(DISMISSALS_PATH.read_text(encoding="utf-8"))
        return dismissals.get(rule_name, {}).get("count", 0)
    except Exception:
        return 0


# ── Cross-Review Problem Detection ────────────────────────────────────────────

def detect_recurring_problems(min_occurrences: int = 3,
                              lookback_reviews: int = 20) -> list[dict]:
    """Detect ITIL problems that recur across reviews.

    Reads house_stats.json to find patterns across the last N reviews.
    When the same rule fires in min_occurrences+ reviews → create a Problem Record.

    Args:
        min_occurrences: Minimum number of reviews with this finding
        lookback_reviews: How many past reviews to analyze

    Returns:
        List of problem records: [{rule, occurrences, files, recommendation}]
    """
    stats_path = get_config_dir() / "stats.json"
    if not stats_path.exists():
        return []

    try:
        stats = json.loads(stats_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    reviews = stats.get("reviews", [])[-lookback_reviews:]
    if len(reviews) < min_occurrences:
        return []

    # We need actual finding data, not just review metadata
    # So also scan recent review JSON files for finding details
    reviews_dir = get_config_dir() / "reviews"
    rule_occurrences: dict[str, dict] = {}

    # Scan recent review JSON files
    json_files = sorted(reviews_dir.glob("house-*.json"), reverse=True)[:lookback_reviews]
    for jf in json_files:
        try:
            review = json.loads(jf.read_text(encoding="utf-8"))
        except Exception:
            continue

        # Collect findings from deterministic scan
        scan_data = review.get("deterministic_scan", {})
        for finding in scan_data.get("findings", []):
            sev = finding.get("severity", "")
            if sev not in ("P1", "P2"):
                continue
            rule = finding.get("rule", "unknown")
            entry = rule_occurrences.setdefault(rule, {
                "rule": rule,
                "severity": sev,
                "review_count": 0,
                "files": set(),
                "review_ids": [],
            })
            entry["review_count"] += 1
            if finding.get("file"):
                entry["files"].add(finding["file"])
            if review.get("rfc_id"):
                entry["review_ids"].append(review["rfc_id"])

    # Filter to rules that appear in min_occurrences+ reviews
    problems = []
    for rule, data in rule_occurrences.items():
        if data["review_count"] >= min_occurrences:
            data["files"] = sorted(data["files"])
            data["review_ids"] = data["review_ids"][-5:]  # last 5
            data["recommendation"] = _recommend_fix(data["rule"], data["severity"])
            problems.append(data)

    # Sort by review count descending
    problems.sort(key=lambda p: p["review_count"], reverse=True)
    return problems


def _recommend_fix(rule_name: str, severity: str) -> str:
    """Generate a problem management recommendation for a recurring finding."""
    recommendations = {
        "hardcoded-api-key": "Install git-secrets or truffleHog pre-commit hook. Add CI stage for secret scanning.",
        "hardcoded-password": "Install git-secrets pre-commit hook. Use .env files with .env.example pattern.",
        "hardcoded-private-key": "Never commit private keys. Use a secrets manager. Add *.pem and *.key to .gitignore.",
        "sql-string-concatenation": "Enforce parameterized queries via lint rule. Add bandit to CI pipeline (B608).",
        "os-command-injection": "Ban os.system() and shell=True via lint rule. Add bandit to CI (B602, B603, B604).",
        "debug-true-production": "Add pre-commit check that blocks DEBUG=True in non-dev configs. Use environment-specific settings files.",
        "console-log-production": "Add ESLint rule no-console: 'error' for production builds.",
        "trailing-whitespace": "Configure .editorconfig with trim_trailing_whitespace = true. Add pre-commit hook.",
        "print-statement-production": "Add flake8-print to CI pipeline. Replace with proper logging framework.",
        "commented-out-code": "Add lint rule. Enforce in code review checklist. Git history preserves old code.",
        "broad-exception-catch": "Add pylint rule W0703 (broad-except). Review in PR checklist.",
        "missing-timeout": "Add lint rule that requires timeout parameter on all HTTP calls.",
        "http-not-https": "Enforce HTTPS via CI check. Add HSTS headers. Block HTTP in production configs.",
    }
    default_rec = f"Add lint rule or pre-commit check targeting this pattern. Affects {severity}-level findings across multiple reviews."
    return recommendations.get(rule_name, default_rec)


def format_problem_alerts(problems: list[dict]) -> str:
    """Format detected problems for inclusion in House's synthesis."""
    if not problems:
        return ""

    lines = [
        "## ITIL Problem Management — Recurring Issues Detected",
        "",
    ]

    for i, p in enumerate(problems[:5], 1):  # top 5
        files_str = ", ".join(p["files"][:3])
        if len(p["files"]) > 3:
            files_str += f" +{len(p['files']) - 3} more"
        lines.append(
            f"### PROB-{i}: {p['rule']}"
        )
        lines.append(f"- **Severity:** {p['severity']}")
        lines.append(f"- **Occurrences:** {p['review_count']} reviews")
        lines.append(f"- **Affected files:** {files_str}")
        lines.append(f"- **Recent RFCs:** {', '.join(p['review_ids'])}")
        lines.append(f"- **Recommendation:** {p['recommendation']}")
        lines.append(f"- **Status:** OPEN — assigned to team")
        lines.append("")

    lines.append(
        "*\"The definition of insanity is running the same review and expecting "
        "different findings. These keep showing up. Fix the root cause, not just the code.\"*"
    )
    return "\n".join(lines)


def auto_create_problem_records(problems: list[dict]) -> None:
    """Persist problem records for audit trail."""
    if not problems:
        return

    problems_dir = get_config_dir() / "problems"
    problems_dir.mkdir(parents=True, exist_ok=True)

    for i, p in enumerate(problems[:5], 1):
        prob_id = f"PROB-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-{i:03d}"
        record = {
            "problem_id": prob_id,
            "title": f"Recurring: {p['rule']} across {p['review_count']} reviews",
            "rule": p["rule"],
            "severity": p["severity"],
            "occurrences": p["review_count"],
            "affected_files": p["files"],
            "recent_rfcs": p["review_ids"],
            "detected_by": "House (Gatekeeper) — Cross-Review Problem Detection",
            "recommendation": p["recommendation"],
            "status": "OPEN",
            "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        record_path = problems_dir / f"{prob_id}.json"
        if not record_path.exists():
            record_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
