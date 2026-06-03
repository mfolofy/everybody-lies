"""House Diagnostics — Ghost-wide performance tracking for review participants.

Tracks Diagnostic scores (0-100) for every agent, specialist, and Cuddy.
Detects review loops and triggers Cuddy tiebreak based on daily grades.

Score storage: docs/reviews/diagnostics/ledger.json (repo-resident, syncs on git pull)

Identity model:
  - Hermes agents: resolved from Co-Authored-By commit attribution (static identity)
  - OpenCode/Claude Code agents: session-declared "Agent (Framework / model-id) — role"
  - Specialists (Foreman, Taub, Cuddy, etc.): keyed by name + model

Grade scale:
  90-100  Attending
  75-89   Resident
  60-74   Intern
  40-59   Med Student
  0-39    Liability
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import get_reviews_dir

# ── Constants ─────────────────────────────────────────────────────────────────

GRADE_LABELS = [
    (90, "Attending"),
    (75, "Resident"),
    (60, "Intern"),
    (40, "Med Student"),
    (0,  "Liability"),
]

SCORE_DELTAS = {
    "p1_confirmed":          +8,
    "p2_confirmed":          +4,
    "p3_confirmed":          +2,
    "finding_contradicted":  -5,
    "finding_reversed":      -8,
    "false_positive":        -12,
    "cuddy_tiebreak_correct": +10,
    "cuddy_tiebreak_wrong":  -15,
    "submitter_clean_pass":  +10,
    "submitter_extra_round": -5,
    "submitter_loop_victim": +3,   # reviewer caused the loop
}

LOOP_THRESHOLD = 3          # rounds with no new unique P1s → specialist dispute
TIEBREAK_MARGIN = 5         # within this many points → Cuddy uses judgment
BASELINE_SCORE  = 70        # starting score for new entities
DECAY_DAYS      = 7         # daily scores weighted over this window


# ── Storage paths ─────────────────────────────────────────────────────────────

def get_diagnostics_dir() -> Path:
    d = get_reviews_dir() / "diagnostics"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_ledger_path() -> Path:
    return get_diagnostics_dir() / "ledger.json"


def get_daily_log_path(date: Optional[str] = None) -> Path:
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return get_diagnostics_dir() / f"daily-{date}.jsonl"


# ── Grade helpers ─────────────────────────────────────────────────────────────

def score_to_label(score: float) -> str:
    for threshold, label in GRADE_LABELS:
        if score >= threshold:
            return label
    return "Liability"


def format_score(score: float) -> str:
    return f"{score:.0f} ({score_to_label(score)})"


# ── Identity parsing ──────────────────────────────────────────────────────────

# Parses "Mike (Claude Code / claude-sonnet-4-6)" or "Samuel (Hermes/Tiger)"
_IDENTITY_RE = re.compile(
    r"(?P<name>\w+)\s*\((?P<framework>[^/]+)/\s*(?P<model_or_node>[^)]+)\)"
)

def parse_attribution(coauthored_by: str) -> dict:
    """Parse a Co-Authored-By line into identity dict."""
    m = _IDENTITY_RE.search(coauthored_by)
    if not m:
        return {"raw": coauthored_by, "key": coauthored_by.strip()}
    name = m.group("name").strip()
    framework = m.group("framework").strip()
    model_or_node = m.group("model_or_node").strip()
    # Hermes agents: node name (Tiger, Mako, VPS). Others: model id.
    is_hermes = framework.lower() == "hermes"
    key = f"{name}/{framework}/{model_or_node}"
    return {
        "name": name,
        "framework": framework,
        "model": None if is_hermes else model_or_node,
        "node": model_or_node if is_hermes else None,
        "is_hermes": is_hermes,
        "key": key,
    }


def specialist_key(specialist_name: str, model: str) -> str:
    """Stable key for a specialist+model combination."""
    short = specialist_name.split("(")[0].strip().replace(" ", "_").lower()
    return f"specialist/{short}/{model or 'unknown'}"


# ── Ledger I/O ────────────────────────────────────────────────────────────────

def _empty_entity(display_name: str) -> dict:
    return {
        "display": display_name,
        "lifetime_score": float(BASELINE_SCORE),
        "daily_scores": {},          # "YYYY-MM-DD": float
        "events": [],                # list of event dicts (last 500)
        "total_commits": 0,
        "total_reviews": 0,
        "false_positives": 0,
        "clean_passes": 0,
        "loops_caused": 0,
        "tiebreaks_correct": 0,
        "tiebreaks_wrong": 0,
    }


def load_ledger() -> dict:
    path = get_ledger_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_ledger(ledger: dict) -> None:
    path = get_ledger_path()
    path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")


def get_entity(ledger: dict, key: str, display_name: str) -> dict:
    if key not in ledger:
        ledger[key] = _empty_entity(display_name)
    return ledger[key]


# ── Daily score helpers ───────────────────────────────────────────────────────

def today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def get_daily_score(entity: dict, date: Optional[str] = None) -> float:
    """Return today's running score, initialised from lifetime if no entry yet."""
    date = date or today_str()
    if date not in entity["daily_scores"]:
        entity["daily_scores"][date] = entity["lifetime_score"]
    return entity["daily_scores"][date]


def apply_delta(ledger: dict, key: str, display_name: str, event_type: str,
                note: str = "", rfc_id: str = "") -> float:
    """Apply a score delta to an entity. Returns new daily score."""
    delta = SCORE_DELTAS.get(event_type, 0)
    entity = get_entity(ledger, key, display_name)
    date = today_str()
    current = get_daily_score(entity, date)
    new_score = max(0.0, min(100.0, current + delta))
    entity["daily_scores"][date] = new_score
    # Lifetime = 7-day weighted average
    recent = sorted(entity["daily_scores"].items())[-DECAY_DAYS:]
    entity["lifetime_score"] = sum(s for _, s in recent) / len(recent)
    # Append event (cap at 500)
    entity["events"].append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "delta": delta,
        "score_after": new_score,
        "rfc_id": rfc_id,
        "note": note,
    })
    entity["events"] = entity["events"][-500:]
    # Update counters
    if event_type == "false_positive":
        entity["false_positives"] += 1
    elif event_type == "submitter_clean_pass":
        entity["clean_passes"] += 1
    elif event_type == "cuddy_tiebreak_correct":
        entity["tiebreaks_correct"] += 1
    elif event_type == "cuddy_tiebreak_wrong":
        entity["tiebreaks_wrong"] += 1
    return new_score


# ── Review round parsing ──────────────────────────────────────────────────────

_P_SEVERITY_RE = re.compile(r"\*\*P([1-4])\b", re.IGNORECASE)
_VERDICT_RE    = re.compile(r"\[(?:APPROVED|REJECTED|BYPASSED)\]", re.IGNORECASE)


def parse_findings_from_md(md_text: str) -> dict[str, list[int]]:
    """Extract per-specialist finding severities from a House markdown report.

    Returns: {"Dr. Eric Foreman": [1, 2, 2], "Dr. Chris Taub": [1], ...}
    """
    results: dict[str, list[int]] = {}
    current_specialist = None
    for line in md_text.splitlines():
        # Detect specialist section header
        specialist_match = re.match(
            r"###\s+(Dr\.\s+\w[\w\s]+?)(?:\s*--|\s*$)", line
        )
        if specialist_match:
            current_specialist = specialist_match.group(1).strip()
            results.setdefault(current_specialist, [])
            continue
        if current_specialist:
            for m in _P_SEVERITY_RE.finditer(line):
                results[current_specialist].append(int(m.group(1)))
    return results


def count_unique_p1s(findings: dict[str, list[int]]) -> int:
    return sum(1 for sevs in findings.values() for s in sevs if s == 1)


# ── Loop detection ────────────────────────────────────────────────────────────

class LoopDetector:
    """Tracks rounds per RFC and fires when loop threshold is crossed."""

    def __init__(self):
        self._rounds: dict[str, list[int]] = {}  # rfc_id → [unique_p1_count per round]

    def record_round(self, rfc_id: str, unique_p1s: int) -> bool:
        """Record a review round. Returns True if loop threshold crossed."""
        self._rounds.setdefault(rfc_id, []).append(unique_p1s)
        rounds = self._rounds[rfc_id]
        if len(rounds) < LOOP_THRESHOLD:
            return False
        # Loop = last N rounds all have same or fewer unique P1s with no decrease
        recent = rounds[-LOOP_THRESHOLD:]
        return all(p == recent[0] for p in recent) or recent[-1] >= recent[0]

    def round_count(self, rfc_id: str) -> int:
        return len(self._rounds.get(rfc_id, []))


# ── Tiebreak logic ────────────────────────────────────────────────────────────

def resolve_tiebreak(
    ledger: dict,
    specialist_a_key: str,
    specialist_b_key: str,
    submitter_key: Optional[str] = None,
    cuddy_key: str = "specialist/cuddy/deepseek-v4-flash",
) -> dict:
    """Determine loop tiebreak winner based on daily grades.

    Returns dict with: winner, loser, method, scores, recommendation
    """
    date = today_str()
    score_a = get_daily_score(get_entity(ledger, specialist_a_key, specialist_a_key), date)
    score_b = get_daily_score(get_entity(ledger, specialist_b_key, specialist_b_key), date)
    submitter_score = None
    if submitter_key:
        submitter_score = get_daily_score(
            get_entity(ledger, submitter_key, submitter_key), date
        )

    gap = abs(score_a - score_b)
    within_margin = gap <= TIEBREAK_MARGIN

    if within_margin:
        method = "cuddy_judgment"
        winner = None  # Cuddy decides manually
        loser  = None
        recommendation = (
            f"Specialists within {gap:.0f} pts (margin={TIEBREAK_MARGIN}). "
            "Cuddy uses judgment. Submitter score noted for context: "
            f"{submitter_score:.0f}" if submitter_score else "no submitter data."
        )
    else:
        if score_a >= score_b:
            winner, loser = specialist_a_key, specialist_b_key
            winner_score, loser_score = score_a, score_b
        else:
            winner, loser = specialist_b_key, specialist_a_key
            winner_score, loser_score = score_b, score_a

        # Submitter override: if submitter outperforms the loser by >10pts, note it
        submitter_note = ""
        if submitter_score and submitter_score > loser_score + 10:
            submitter_note = (
                f" Submitter ({submitter_score:.0f}) outperforms losing specialist "
                f"({loser_score:.0f}) — pushback carries weight."
            )

        method = "grade_tiebreak"
        recommendation = (
            f"{winner} wins (daily {winner_score:.0f} vs {loser_score:.0f}, "
            f"gap={gap:.0f}pts). {loser} finding overruled.{submitter_note}"
        )

    return {
        "winner": winner,
        "loser": loser,
        "method": method,
        "score_a": score_a,
        "score_b": score_b,
        "submitter_score": submitter_score,
        "within_margin": within_margin,
        "recommendation": recommendation,
    }


# ── Commit event recording ────────────────────────────────────────────────────

def record_commit_event(
    rfc_id: str,
    verdict: str,               # APPROVED | REJECTED | BYPASSED
    rounds: int,
    submitter_key: str,
    submitter_display: str,
    specialist_findings: dict[str, list[int]],  # specialist_name → [severity ints]
    specialist_models: dict[str, str],           # specialist_name → model_id
    loop_detected: bool = False,
    bypass_was_reviewer_fault: bool = False,
) -> dict:
    """Process a completed review and apply all score deltas.

    Returns summary dict suitable for the morning report.
    """
    ledger = load_ledger()
    date = today_str()
    summary = {
        "rfc_id": rfc_id,
        "date": date,
        "verdict": verdict,
        "rounds": rounds,
        "submitter": submitter_key,
        "deltas": [],
        "loop_detected": loop_detected,
    }

    # ── Submitter scoring ──
    if verdict == "APPROVED" and rounds == 1:
        apply_delta(ledger, submitter_key, submitter_display,
                    "submitter_clean_pass", rfc_id=rfc_id)
        summary["deltas"].append((submitter_key, "submitter_clean_pass"))
    else:
        extra = max(0, rounds - 1)
        for _ in range(extra):
            apply_delta(ledger, submitter_key, submitter_display,
                        "submitter_extra_round", rfc_id=rfc_id)
        if extra:
            summary["deltas"].append((submitter_key, f"submitter_extra_round x{extra}"))

    if loop_detected and bypass_was_reviewer_fault:
        apply_delta(ledger, submitter_key, submitter_display,
                    "submitter_loop_victim", rfc_id=rfc_id,
                    note="Loop caused by contradicting reviewers")
        summary["deltas"].append((submitter_key, "submitter_loop_victim"))

    # ── Specialist scoring ──
    for specialist_name, severities in specialist_findings.items():
        model = specialist_models.get(specialist_name, "unknown")
        key = specialist_key(specialist_name, model)
        display = f"{specialist_name} ({model})"
        # Confirmed findings = severities that appear in the final fixed commit
        # Heuristic: if APPROVED, assume P1/P2s were real; if BYPASSED, treat as false positives
        if verdict in ("APPROVED",):
            for sev in severities:
                etype = {1: "p1_confirmed", 2: "p2_confirmed"}.get(sev, "p3_confirmed")
                apply_delta(ledger, key, display, etype, rfc_id=rfc_id)
                summary["deltas"].append((key, etype))
        elif verdict == "BYPASSED":
            for sev in severities:
                if sev <= 2:
                    apply_delta(ledger, key, display, "false_positive", rfc_id=rfc_id)
                    summary["deltas"].append((key, "false_positive"))
        # Contradiction detection across specialists (same P1 claimed by both = possible contradiction)
        # Simple heuristic: if multiple specialists found P1s in the same round on a bypass, penalise
        if loop_detected:
            apply_delta(ledger, key, display, "finding_contradicted",
                        note="Part of loop", rfc_id=rfc_id)
            summary["deltas"].append((key, "finding_contradicted"))

    save_ledger(ledger)

    # Append to daily log
    log_path = get_daily_log_path(date)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(summary) + "\n")

    return summary


# ── Morning report ────────────────────────────────────────────────────────────

def generate_morning_report(date: Optional[str] = None) -> str:
    """Generate previous-day performance report card."""
    if date is None:
        from datetime import timedelta
        yesterday = (datetime.now(timezone.utc).date() - __import__('datetime').timedelta(days=1))
        date = yesterday.strftime("%Y-%m-%d")

    ledger = load_ledger()
    log_path = get_daily_log_path(date)

    lines = []
    if log_path.exists():
        lines = [json.loads(l) for l in log_path.read_text(encoding="utf-8").splitlines() if l.strip()]

    report = [f"HOUSE DIAGNOSTICS — {date}", "=" * 40]

    if not lines:
        report.append("No review activity recorded.")
        return "\n".join(report)

    total_commits  = len(lines)
    loops          = sum(1 for l in lines if l.get("loop_detected"))
    bypasses       = sum(1 for l in lines if l.get("verdict") == "BYPASSED")
    clean_passes   = sum(1 for l in lines if l.get("rounds") == 1 and l.get("verdict") == "APPROVED")

    report.append(f"Commits reviewed : {total_commits}")
    report.append(f"Clean passes     : {clean_passes}")
    report.append(f"Loops triggered  : {loops}")
    report.append(f"Bypasses         : {bypasses}")
    report.append("")

    # Submitters
    submitters = {}
    for entry in lines:
        sk = entry.get("submitter")
        if sk and sk in ledger:
            submitters[sk] = ledger[sk]

    if submitters:
        report.append("Submitters:")
        for key, entity in sorted(submitters.items(), key=lambda x: -get_daily_score(x[1], date)):
            score = get_daily_score(entity, date)
            prev  = entity["lifetime_score"]
            delta = score - prev
            sign  = "+" if delta >= 0 else ""
            report.append(f"  {entity['display']:<30} {score:>5.0f} ({sign}{delta:.0f})  {score_to_label(score)}")
        report.append("")

    # Specialists
    specialists = {k: v for k, v in ledger.items() if k.startswith("specialist/")}
    if specialists:
        report.append("Specialists:")
        for key, entity in sorted(specialists.items(), key=lambda x: -get_daily_score(x[1], date)):
            score = get_daily_score(entity, date)
            prev  = entity["lifetime_score"]
            delta = score - prev
            sign  = "+" if delta >= 0 else ""
            fp    = entity.get("false_positives", 0)
            fp_note = f"  ← {fp} false positive(s)" if fp else ""
            report.append(
                f"  {entity['display']:<35} {score:>5.0f} ({sign}{delta:.0f})  "
                f"{score_to_label(score)}{fp_note}"
            )
        report.append("")

    # Recommendations
    report.append("Recommendations:")
    for key, entity in specialists.items():
        score = get_daily_score(entity, date)
        fp    = entity.get("false_positives", 0)
        if score < 60:
            report.append(f"  ⚠  {entity['display']} at Intern level — review calibration needed")
        if fp >= 2:
            report.append(f"  ⚠  {entity['display']} — {fp} false positives, domain routing suggested")

    return "\n".join(report)


# ── CLI entry ─────────────────────────────────────────────────────────────────

def main_report(argv=None):
    """Print morning report. Usage: python -m everybody_lies.diagnostics [YYYY-MM-DD]"""
    import sys
    date = argv[0] if argv else None
    print(generate_morning_report(date))


if __name__ == "__main__":
    import sys
    main_report(sys.argv[1:])
