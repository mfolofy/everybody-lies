"""Tests for _assess_specialist_response and the explicit-FAIL verdict marker.

Regression guards for the 2026-07-02 adversarial review:
  - The mandated summary template puts '**Verdict:** FAIL' at the END of the
    response; head-only checks (response[:500]) never saw it.
  - Bare 'FAIL' substring matched FAILURE/FAILED in prose (false block).
  - A structured APPROVE that admits max_severity P1 slipped through clean.
  - The zero-count summary line must never scrape as a phantom P1
    (the class of bug behind dc5fca4 — also fixed in the cross-check path).
"""

from everybody_lies.gatekeeper import (
    _assess_specialist_response,
    _has_explicit_fail_verdict,
)


# ── Explicit FAIL verdict marker ─────────────────────────────────────────────

def test_fail_verdict_at_end_of_long_response_detected():
    """The verdict line lives at the END of the template — a >500-char body
    before it must not hide it (the old head-only check missed this)."""
    body = "## Findings\n" + ("- **Severity:** P4\n- **Issue:** style nit\n" * 30)
    resp = body + "\n## Summary\n- **Verdict:** FAIL\n"
    assert _has_explicit_fail_verdict(resp) is True


def test_plain_verdict_fail_detected():
    assert _has_explicit_fail_verdict("Verdict: FAIL") is True
    assert _has_explicit_fail_verdict("VERDICT: FAIL") is True


def test_pass_verdict_not_detected():
    assert _has_explicit_fail_verdict("## Summary\n- **Verdict:** PASS\n") is False


def test_template_echo_pass_or_fail_not_detected():
    """Echoing the template line 'PASS (...) or FAIL (...)' must not fire."""
    resp = "- **Verdict:** PASS (all alternatives ruled out) or FAIL (simpler approach exists)"
    # PASS immediately follows the Verdict marker — FAIL is only the echo.
    assert _has_explicit_fail_verdict(resp) is False


def test_prose_failure_words_not_detected():
    """FAILURE/FAILED in ordinary prose must not read as a FAIL verdict."""
    resp = ("## Findings\n- **Severity:** P3\n"
            "- **Issue:** login FAILURE handling swallows the exception. "
            "The FAILED branch logs nothing.\n"
            "## Summary\n- **Verdict:** PASS\n")
    assert _has_explicit_fail_verdict(resp) is False


# ── _assess_specialist_response: structured path ─────────────────────────────

def test_structured_reject_p1_is_hard():
    resp = ('```verdict\n{"verdict": "REJECT", "max_severity": "P1", '
            '"blocking_findings": ["secret in diff"]}\n```')
    a = _assess_specialist_response("Foreman", resp)
    assert a["blocks"] is True
    assert a["hard_p1"] is True


def test_structured_reject_p2_blocks_but_not_hard():
    resp = ('```verdict\n{"verdict": "REJECT", "max_severity": "P2", '
            '"blocking_findings": ["missing auth check"]}\n```')
    a = _assess_specialist_response("Foreman", resp)
    assert a["blocks"] is True
    assert a["hard_p1"] is False


def test_structured_approve_clean_passes():
    resp = ('```verdict\n{"verdict": "APPROVE", "max_severity": "NONE", '
            '"blocking_findings": []}\n```')
    a = _assess_specialist_response("Foreman", resp)
    assert a["blocks"] is False
    assert a["hard_p1"] is False


def test_contradictory_approve_with_p1_blocks_appealably():
    """APPROVE + max_severity P1 is incoherent — must block (appealable),
    never slip through as a clean pass and never become a hard P1."""
    resp = ('```verdict\n{"verdict": "APPROVE", "max_severity": "P1", '
            '"blocking_findings": []}\n```')
    a = _assess_specialist_response("Foreman", resp)
    assert a["blocks"] is True
    assert a["hard_p1"] is False
    assert a["finding"] and "contradictory" in a["finding"]


# ── _assess_specialist_response: heuristic (no structured block) path ────────

def test_unstructured_real_p1_blocks_as_appealable_heuristic():
    resp = ("## Findings\n- **Severity:** P1\n- **Issue:** SQL injection\n"
            "## Summary\n- **Verdict:** FAIL\n")
    a = _assess_specialist_response("Foreman", resp)
    assert a["blocks"] is True
    assert a["hard_p1"] is False
    assert a["finding"] and "HEURISTIC" in a["finding"]


def test_unstructured_zero_count_summary_is_clean_pass():
    """The mandated zero-count summary line must not scrape as a phantom P1.
    This exact text appears in EVERY clean unstructured response — and, before
    the cross-check fix, the substring 'P1' in it failed every adversarial run."""
    resp = ("## Findings\nNo findings.\n\n## Summary\n"
            "- Total findings: 0\n"
            "- **P1 (blocking):** 0\n"
            "- **P2 (high):** 0\n"
            "- **Verdict:** PASS\n")
    a = _assess_specialist_response("Foreman", resp)
    assert a["blocks"] is False
    assert a["hard_p1"] is False


def test_unstructured_fail_verdict_at_end_blocks():
    """An explicit FAIL verdict past the 500-char head must still block."""
    body = "## Findings\n" + ("- **Severity:** P3\n- **Issue:** naming\n" * 40)
    resp = body + "\n## Summary\n- **Verdict:** FAIL\n"
    a = _assess_specialist_response("Foreman", resp)
    assert a["blocks"] is True
    assert a["hard_p1"] is False
