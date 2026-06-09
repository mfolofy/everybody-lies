"""
test_tutor_drift.py — Tests for tutor_drift pre-commit check.

Run: python -m pytest everybody-lies/pre_commit/checks/test_tutor_drift.py -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

# Ensure sibling module is importable
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

from tutor_drift import check_tutor_drift, _version_satisfies


# ── Helpers ──────────────────────────────────────────────────────────────────

def _write_temp_manifest(dirpath: str, classes: list[dict]) -> str:
    """Write a temporary MANIFEST.json and return its path."""
    path = os.path.join(dirpath, "MANIFEST.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "classes": classes}, fh)
    return path


def _write_temp_profiles(dirpath: str, profiles: dict[str, dict]) -> str:
    """Write a temporary loader.py containing BASE_PROFILES and return path."""
    path = os.path.join(dirpath, "loader.py")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# Auto-generated test profile module\n")
        fh.write("BASE_PROFILES = ")
        fh.write(repr(profiles))
        fh.write("\n")
    return path


# ── Unit: version parsing ────────────────────────────────────────────────────


def test_version_satisfies_equal():
    assert _version_satisfies("1.0", ">=1.0") is True
    assert _version_satisfies("2.0", ">=1.0") is True
    assert _version_satisfies("0.5", ">=1.0") is False
    assert _version_satisfies("1.3", ">=1.0") is True


def test_version_satisfies_strict():
    assert _version_satisfies("1.0", "==1.0") is True
    assert _version_satisfies("1.1", "==1.0") is False
    assert _version_satisfies("0.5", "!=1.0") is True
    assert _version_satisfies("1.0", "!=1.0") is False


def test_version_satisfies_greater():
    assert _version_satisfies("2.0", ">1.0") is True
    assert _version_satisfies("1.0", ">1.0") is False
    assert _version_satisfies("0.5", "<1.0") is True
    assert _version_satisfies("2.0", "<1.0") is False
    assert _version_satisfies("1.0", "<=1.0") is True
    assert _version_satisfies("2.0", "<=1.0") is False


def test_version_satisfies_invalid():
    """Unparseable versions or constraints should return False (safe)."""
    assert _version_satisfies("blah", ">=1.0") is False
    assert _version_satisfies("1.0", "blah") is False
    assert _version_satisfies("1", ">=1.0") is False   # missing minor
    assert _version_satisfies("1.0", ">=1") is False   # malformed constraint


# ── Integration: drift check ─────────────────────────────────────────────────


def test_matching_no_warnings():
    """Matching manifest + profiles → only 'ok' findings and info for orphans."""
    manifest_classes = [
        {"id": "security", "version": "2.0", "domain": "app-security",
         "rules_count": 18, "standards": [], "description": "sec"},
        {"id": "audit", "version": "1.0", "domain": "compliance",
         "rules_count": 18, "standards": [], "description": "aud"},
    ]
    profiles = {
        "security": {
            "tutor_refs": {"security": ">=2.0", "audit": ">=1.0"},
        },
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        manifest_path = _write_temp_manifest(tmpdir, manifest_classes)
        profile_path = _write_temp_profiles(tmpdir, profiles)
        findings = check_tutor_drift(manifest_path, profile_path)

    # Should have 2 'ok' findings (both refs satisfied) and no warns
    ok_findings = [f for f in findings if f["severity"] == "ok"]
    warn_findings = [f for f in findings if f["severity"] == "warn"]

    assert len(ok_findings) == 2
    assert len(warn_findings) == 0
    assert "security >=2.0 satisfied" in ok_findings[0]["message"]
    assert "audit >=1.0 satisfied" in ok_findings[1]["message"]


def test_profile_refs_missing_class():
    """Profile refs a class not in manifest → warn."""
    manifest_classes = [
        {"id": "audit", "version": "1.0", "domain": "compliance",
         "rules_count": 18, "standards": [], "description": "aud"},
    ]
    profiles = {
        "infra": {
            "tutor_refs": {"security": ">=2.0", "audit": ">=1.0"},
        },
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        manifest_path = _write_temp_manifest(tmpdir, manifest_classes)
        profile_path = _write_temp_profiles(tmpdir, profiles)
        findings = check_tutor_drift(manifest_path, profile_path)

    warns = [f for f in findings if f["severity"] == "warn"]
    oks = [f for f in findings if f["severity"] == "ok"]

    assert len(oks) == 1  # audit ref satisfied
    assert len(warns) == 1  # security ref missing
    assert "security" in warns[0]["message"]
    assert "does not exist" in warns[0]["message"]


def test_profile_requires_higher_version():
    """Profile requires version > manifest → warn."""
    manifest_classes = [
        {"id": "security", "version": "1.0", "domain": "app-security",
         "rules_count": 18, "standards": [], "description": "sec"},
    ]
    profiles = {
        "infra": {
            "tutor_refs": {"security": ">=2.0"},
        },
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        manifest_path = _write_temp_manifest(tmpdir, manifest_classes)
        profile_path = _write_temp_profiles(tmpdir, profiles)
        findings = check_tutor_drift(manifest_path, profile_path)

    warns = [f for f in findings if f["severity"] == "warn"]
    assert len(warns) == 1
    assert "requires security >=2.0" in warns[0]["message"]


def test_extra_classes_info():
    """Classes in manifest not referenced by any profile → info."""
    manifest_classes = [
        {"id": "brushes", "version": "1.3", "domain": "ui-ux",
         "rules_count": 12, "standards": [], "description": "ui"},
        {"id": "security", "version": "2.0", "domain": "app-security",
         "rules_count": 18, "standards": [], "description": "sec"},
    ]
    profiles = {
        "security": {
            "tutor_refs": {"security": ">=2.0"},
        },
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        manifest_path = _write_temp_manifest(tmpdir, manifest_classes)
        profile_path = _write_temp_profiles(tmpdir, profiles)
        findings = check_tutor_drift(manifest_path, profile_path)

    infos = [f for f in findings if f["severity"] == "info"]
    assert len(infos) == 1
    assert "brushes" in infos[0]["message"]
    assert "not referenced" in infos[0]["message"]


def test_missing_manifest_graceful():
    """Missing manifest file → empty findings (no crash)."""
    manifest_path = "/nonexistent/path/MANIFEST.json"

    with tempfile.TemporaryDirectory() as tmpdir:
        profiles = {"security": {"tutor_refs": {"audit": ">=1.0"}}}
        profile_path = _write_temp_profiles(tmpdir, profiles)
        findings = check_tutor_drift(manifest_path, profile_path)

    assert findings == []


def test_missing_profile_file_graceful():
    """Missing profile file → empty findings (no crash)."""
    profile_path = "/nonexistent/path/loader.py"

    with tempfile.TemporaryDirectory() as tmpdir:
        manifest_classes = [
            {"id": "audit", "version": "1.0", "domain": "compliance",
             "rules_count": 18, "standards": [], "description": "aud"},
        ]
        manifest_path = _write_temp_manifest(tmpdir, manifest_classes)
        findings = check_tutor_drift(manifest_path, profile_path)

    assert findings == []


def test_missing_tutor_refs_on_profile():
    """Profile without tutor_refs → no findings generated for that profile."""
    manifest_classes = [
        {"id": "audit", "version": "1.0", "domain": "compliance",
         "rules_count": 18, "standards": [], "description": "aud"},
        {"id": "security", "version": "2.0", "domain": "app-security",
         "rules_count": 18, "standards": [], "description": "sec"},
    ]
    profiles = {
        "old_profile": {
            "name": "Legacy Agent",
            # No tutor_refs at all
            "domain": "legacy",
        },
        "security": {
            "tutor_refs": {"security": ">=2.0"},
        },
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        manifest_path = _write_temp_manifest(tmpdir, manifest_classes)
        profile_path = _write_temp_profiles(tmpdir, profiles)
        findings = check_tutor_drift(manifest_path, profile_path)

    # security ref satisfied → ok
    # audit not referenced → info
    # old_profile has no tutor_refs → no findings
    oks = [f for f in findings if f["severity"] == "ok"]
    infos = [f for f in findings if f["severity"] == "info"]
    warns = [f for f in findings if f["severity"] == "warn"]

    assert len(oks) == 1
    assert len(infos) == 1  # audit is orphaned
    assert len(warns) == 0


def test_wrong_manifest_format_graceful():
    """Malformed JSON or wrong structure → graceful empty."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bad_manifest = os.path.join(tmpdir, "MANIFEST.json")
        with open(bad_manifest, "w") as fh:
            fh.write("not json at all")

        profile_path = _write_temp_profiles(tmpdir, {"p": {}})
        findings = check_tutor_drift(bad_manifest, profile_path)

    assert findings == []


def test_wrong_profile_module_graceful():
    """Profile file that raises on import → graceful empty."""
    with tempfile.TemporaryDirectory() as tmpdir:
        manifest_classes = [
            {"id": "audit", "version": "1.0", "domain": "compliance",
             "rules_count": 18, "standards": [], "description": "aud"},
        ]
        manifest_path = _write_temp_manifest(tmpdir, manifest_classes)

        bad_profile = os.path.join(tmpdir, "loader.py")
        with open(bad_profile, "w") as fh:
            fh.write("raise RuntimeError('boom')\n")

        findings = check_tutor_drift(manifest_path, bad_profile)

    assert findings == []


if __name__ == "__main__":
    sys.exit(0 if all(True for _ in []) else 1)
