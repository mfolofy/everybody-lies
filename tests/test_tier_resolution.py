"""Tests for the tier-resolution and Cuddy-convergence fixes.

Regression guard for the night jen_mailbox.py took 11 review rounds:
  - a 1.8-risk one-file utility must run "fast", not be forced to "standard"
  - Cuddy's approach-level FAIL must not hard-block on fast/standard tiers
"""
import re

from everybody_lies.gatekeeper import (
    _resolve_effective_tier,
    _recommend_tier,
    _cuddy_should_block,
    _is_routing_gap_complaint,
    P1_PATTERNS,
)

# Use the gate's REAL patterns — no local duplicate that can drift out of sync.
_P1_PATTERNS = P1_PATTERNS


def _text_has_p1(text: str) -> bool:
    """Mirror the gate's blocking-P1 detection (gatekeeper.py ~L1935)."""
    return any(re.search(p, text, re.MULTILINE | re.IGNORECASE) for p in P1_PATTERNS)


# ── Issue #1: honor the risk-recommended tier ──────────────────────────────

def test_low_risk_default_caller_gets_fast():
    """The exact jen_mailbox.py case: risk 1.8 -> fast, caller passed the
    default 'standard' (not explicit). House must run 'fast', not 'standard'."""
    rec = _recommend_tier(1.8)
    assert rec == "fast"
    eff = _resolve_effective_tier(
        requested_tier="standard", recommended_tier=rec,
        tier_floor="fast", tier_explicit=False,
    )
    assert eff == "fast"


def test_explicit_tier_is_respected():
    """If the caller explicitly pins --tier standard, honor it even on low risk."""
    eff = _resolve_effective_tier(
        requested_tier="standard", recommended_tier="fast",
        tier_floor="fast", tier_explicit=True,
    )
    assert eff == "standard"


def test_floor_is_hard_minimum_even_for_default_caller():
    """A low recommendation can never drop below the file/risk/gate floor."""
    eff = _resolve_effective_tier(
        requested_tier="standard", recommended_tier="fast",
        tier_floor="adversarial", tier_explicit=False,
    )
    assert eff == "adversarial"


def test_floor_is_hard_minimum_even_when_explicit():
    eff = _resolve_effective_tier(
        requested_tier="fast", recommended_tier="fast",
        tier_floor="standard", tier_explicit=True,
    )
    assert eff == "standard"


def test_high_risk_default_caller_gets_adversarial():
    rec = _recommend_tier(4.5)
    assert rec == "adversarial"
    eff = _resolve_effective_tier(
        requested_tier="standard", recommended_tier=rec,
        tier_floor="fast", tier_explicit=False,
    )
    assert eff == "adversarial"


# ── Issue #2: Cuddy convergence ────────────────────────────────────────────

def test_cuddy_approach_fail_does_not_block_on_fast():
    """An approach-level FAIL ('simpler alternative exists') with no P1 must NOT
    block on the fast tier — this is what looped 11 times."""
    resp = (
        "## Differential Diagnosis\n"
        "- Alternative: use pure heuristics instead of an LLM\n"
        "- Ruled out?: NO\n\n"
        "## Summary\n- **Verdict:** FAIL (a simpler approach exists)\n"
    )
    assert _cuddy_should_block(resp, "fast", _P1_PATTERNS) is False


def test_cuddy_approach_fail_does_not_block_on_standard():
    resp = "## Summary\n- **Verdict:** FAIL (use Zapier instead)\n"
    assert _cuddy_should_block(resp, "standard", _P1_PATTERNS) is False


def test_cuddy_approach_fail_blocks_on_adversarial():
    resp = "## Summary\n- **Verdict:** FAIL (a simpler approach exists)\n"
    assert _cuddy_should_block(resp, "adversarial", _P1_PATTERNS) is True


def test_cuddy_genuine_p1_blocks_on_every_tier():
    """A real P1 (approach obviates the code) blocks even on fast."""
    resp = (
        "- **Severity:** P1\n"
        "- **Issue:** this entire script is a one-liner in the stdlib\n"
        "## Summary\n- **Verdict:** FAIL\n"
    )
    for tier in ("fast", "standard", "adversarial"):
        assert _cuddy_should_block(resp, tier, _P1_PATTERNS) is True


def test_cuddy_pass_never_blocks():
    resp = "## Summary\n- **Verdict:** PASS (all alternatives ruled out)\n"
    for tier in ("fast", "standard", "adversarial"):
        assert _cuddy_should_block(resp, tier, _P1_PATTERNS) is False


# ── Issue #4: routing-gap complaint must not block ─────────────────────────

def test_routing_gap_complaint_detected():
    resp = (
        "## Findings\n- **Severity:** P1\n- **Issue:** the jen_mailbox.py "
        "content is missing, I cannot review it.\n"
    )
    assert _is_routing_gap_complaint(resp) is True


def test_normal_finding_is_not_routing_gap():
    resp = (
        "## Findings\n- **Severity:** P2\n- **Issue:** missing error handling "
        "on the network call at line 42.\n"
    )
    assert _is_routing_gap_complaint(resp) is False


# ── Regression: phantom P1 from a PASS summary line (2026-06-19) ────────────
# A specialist that PASSES emits "- **P1 (blocking): 0". DeepSeek often bolds
# the count ("- **P1 (blocking):** 0"), which slipped past the zero-count guard
# and was read as a real P1 — false-blocking clean commits a different
# specialist each round. These guard that exact line, in every formatting.

def test_zero_count_summary_does_not_trigger_p1():
    for line in (
        "- **P1 (blocking):** 0",      # bold count — the actual bug
        "- P1 (blocking): 0",          # plain
        "**P1 (blocking):** 0",        # bold, no bullet
        "- **P1 (blocking):**  0",     # extra space
        "- P1 (blocking):0",           # no space
    ):
        assert _text_has_p1(line) is False, f"phantom P1 on: {line!r}"


def test_zero_count_in_full_pass_summary_does_not_trigger_p1():
    resp = (
        "## Findings\nNo findings. The diff is content-only.\n\n"
        "## Summary\n"
        "- **Total findings:** 0\n"
        "- **P1 (blocking):** 0\n"
        "- **P2 (high):** 0\n"
        "- **Verdict:** PASS\n"
    )
    assert _text_has_p1(resp) is False


def test_real_p1_still_detected():
    for line in (
        "- **Severity:** P1",
        "- **P1 — SQL injection in the query builder**",
        "- **P1: unguarded KeyError on lead['company']**",
        "Severity: P1 (blocking)",
        "- **P1 (blocking):** 2",       # a NON-zero count must still block
    ):
        assert _text_has_p1(line) is True, f"missed real P1 on: {line!r}"
