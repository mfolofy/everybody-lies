"""Tests for _parse_structured_verdict — the deterministic verdict parser.

Verifies that:
  - Clean, well-formed APPROVE blocks are parsed correctly.
  - Clean, well-formed REJECT blocks (P1/P2) are parsed correctly.
  - Malformed JSON inside a verdict block returns conservative REJECT (never silently approves).
  - A response with NO verdict block returns None (triggers fallback).
  - Partial/unexpected keys are tolerated with safe defaults.
  - Case-insensitive fence matching works.
"""

import pytest
from everybody_lies.gatekeeper import _parse_structured_verdict


# ── Happy path: APPROVE ────────────────────────────────────────────────────────

def test_approve_clean():
    response = '''## Summary
- Total findings: 0
- **Verdict:** PASS

```verdict
{"verdict": "APPROVE", "max_severity": "NONE", "blocking_findings": []}
```
'''
    result = _parse_structured_verdict(response)
    assert result is not None
    assert result["verdict"] == "APPROVE"
    assert result["max_severity"] == "NONE"
    assert result["blocking_findings"] == []


def test_approve_p3_only():
    response = '''## Summary
- P3 (medium): 2
- **Verdict:** PASS

```verdict
{"verdict": "APPROVE", "max_severity": "P3", "blocking_findings": []}
```
'''
    result = _parse_structured_verdict(response)
    assert result is not None
    assert result["verdict"] == "APPROVE"
    assert result["max_severity"] == "P3"
    assert result["blocking_findings"] == []


# ── Happy path: REJECT ─────────────────────────────────────────────────────────

def test_reject_p1():
    response = '''## Findings
- **Severity:** P1
- **File:** app.py:42
- **Issue:** SQL injection

```verdict
{"verdict": "REJECT", "max_severity": "P1", "blocking_findings": ["app.py:42 SQL injection in execute()"]}
```
'''
    result = _parse_structured_verdict(response)
    assert result is not None
    assert result["verdict"] == "REJECT"
    assert result["max_severity"] == "P1"
    assert len(result["blocking_findings"]) == 1
    assert "SQL injection" in result["blocking_findings"][0]


def test_reject_p2():
    response = '''```verdict
{"verdict": "REJECT", "max_severity": "P2", "blocking_findings": ["missing auth check on /admin"]}
```
'''
    result = _parse_structured_verdict(response)
    assert result is not None
    assert result["verdict"] == "REJECT"
    assert result["max_severity"] == "P2"


# ── Safety: malformed JSON inside block → conservative REJECT, never approve ──

def test_malformed_json_returns_reject():
    """A broken JSON block must NEVER silently approve — default to REJECT."""
    response = '''```verdict
{verdict: APPROVE, max_severity: NONE}
```
'''
    result = _parse_structured_verdict(response)
    assert result is not None
    assert result["verdict"] == "REJECT", "Malformed JSON must default to REJECT (safe)"
    assert "_parse_error" in result


def test_empty_json_object_returns_reject():
    """An empty JSON object has no verdict key — must default to REJECT."""
    response = '''```verdict
{}
```
'''
    result = _parse_structured_verdict(response)
    assert result is not None
    assert result["verdict"] == "REJECT"


def test_unknown_verdict_value_returns_reject():
    """An unrecognised verdict string (e.g. 'PASS') must default to REJECT."""
    response = '''```verdict
{"verdict": "PASS", "max_severity": "NONE", "blocking_findings": []}
```
'''
    result = _parse_structured_verdict(response)
    assert result is not None
    assert result["verdict"] == "REJECT", "Unknown verdict value must default to REJECT"


def test_unknown_severity_returns_none_severity():
    """Unrecognised max_severity normalises to NONE."""
    response = '''```verdict
{"verdict": "APPROVE", "max_severity": "P9", "blocking_findings": []}
```
'''
    result = _parse_structured_verdict(response)
    assert result is not None
    assert result["max_severity"] == "NONE"


def test_blocking_findings_not_list_is_normalised():
    """blocking_findings must always be a list — non-list values are normalised."""
    response = '''```verdict
{"verdict": "REJECT", "max_severity": "P2", "blocking_findings": "missing auth"}
```
'''
    result = _parse_structured_verdict(response)
    assert result is not None
    assert isinstance(result["blocking_findings"], list)


# ── No block present → returns None (fallback path) ──────────────────────────

def test_no_verdict_block_returns_none():
    """Old-style response with no verdict block must return None (triggers regex fallback)."""
    response = '''## Summary
- P1 (blocking): 0
- **Verdict:** PASS
'''
    result = _parse_structured_verdict(response)
    assert result is None


def test_prose_only_response_returns_none():
    """Plain prose with no fence returns None."""
    result = _parse_structured_verdict("The code looks clean. APPROVE.")
    assert result is None


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_case_insensitive_fence_tag():
    """The ```VERDICT fence tag should be matched case-insensitively."""
    response = '''```VERDICT
{"verdict": "APPROVE", "max_severity": "NONE", "blocking_findings": []}
```
'''
    result = _parse_structured_verdict(response)
    assert result is not None
    assert result["verdict"] == "APPROVE"


def test_verdict_block_with_extra_whitespace():
    """Whitespace around the JSON is tolerated."""
    response = '```verdict\n   {"verdict": "APPROVE", "max_severity": "P4", "blocking_findings": []}   \n```'
    result = _parse_structured_verdict(response)
    assert result is not None
    assert result["verdict"] == "APPROVE"


def test_multiple_verdict_blocks_uses_last():
    """If two verdict blocks appear, the LAST one is authoritative — the prompt
    says 'emit this EXACTLY at the end'. An earlier block (e.g. an echoed
    template example) must not mask the real final verdict."""
    response = '''```verdict
{"verdict": "APPROVE", "max_severity": "NONE", "blocking_findings": []}
```

Some extra text

```verdict
{"verdict": "REJECT", "max_severity": "P1", "blocking_findings": ["critical bug"]}
```
'''
    result = _parse_structured_verdict(response)
    assert result is not None
    # Last block wins — the final REJECT must not be masked by the earlier APPROVE
    assert result["verdict"] == "REJECT"
    assert result["max_severity"] == "P1"


def test_echoed_template_example_does_not_mask_real_verdict():
    """Models sometimes repeat the prompt's example block before the real one.
    The echo ('APPROVE or REJECT') parses as a conservative REJECT — it must
    not override the model's actual final APPROVE."""
    response = '''The required format is:

```verdict
{"verdict": "APPROVE or REJECT", "max_severity": "P1/P2/P3/P4/NONE", "blocking_findings": []}
```

## Findings
None.

```verdict
{"verdict": "APPROVE", "max_severity": "NONE", "blocking_findings": []}
```
'''
    result = _parse_structured_verdict(response)
    assert result is not None
    assert result["verdict"] == "APPROVE"
