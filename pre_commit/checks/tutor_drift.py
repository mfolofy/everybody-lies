"""
tutor_drift.py — Deterministic pre-commit check for Tutor-Mesh drift.

Compares MANIFEST.json (Tutor class registry) against Ghost Mesh
profile tutor_refs. Surfaces mismatches, missing refs, and orphaned
classes. Zero LLM calls. Never blocks commit — always suggests fixes.

Usage:
    from everybody_lies_pre_commit_checks.tutor_drift import check_tutor_drift

    findings = check_tutor_drift(MANIFEST_PATH, PROFILE_PATH)
    for f in findings:
        print(f"[{f['severity']}] {f['message']}")
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


# ── Version parsing ──────────────────────────────────────────────────────────

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)$")
_CONSTRAINT_RE = re.compile(r"^(>=|<=|>|<|==|!=)\s*(\d+\.\d+)$")


def _parse_version(raw: str) -> tuple[int, int] | None:
    """Parse a simple 'MAJOR.MINOR' version string. Returns None on failure."""
    m = _VERSION_RE.match(raw.strip())
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)))


def _parse_constraint(raw: str) -> tuple[str, tuple[int, int]] | None:
    """Parse a constraint like '>=2.0' into (operator, (major, minor))."""
    m = _CONSTRAINT_RE.match(raw.strip())
    if not m:
        return None
    ver = _parse_version(m.group(2))
    if ver is None:
        return None
    return (m.group(1), ver)


def _version_satisfies(actual_version: str, constraint: str) -> bool:
    """Check whether actual_version satisfies the constraint string.

    Examples:
        _version_satisfies("2.0", ">=1.0") → True
        _version_satisfies("0.5", ">=1.0") → False
        _version_satisfies("1.0", ">=1.0") → True
    """
    actual = _parse_version(actual_version)
    parsed = _parse_constraint(constraint)
    if actual is None or parsed is None:
        return False  # Unparseable — safety: treat as unsatisfied

    op, required = parsed
    a = actual
    r = required

    if op == ">=":
        return a >= r
    elif op == "<=":
        return a <= r
    elif op == ">":
        return a > r
    elif op == "<":
        return a < r
    elif op == "==":
        return a == r
    elif op == "!=":
        return a != r
    return False


# ── Manifest loading ─────────────────────────────────────────────────────────


def _load_manifest(manifest_path: str) -> dict[str, Any] | None:
    """Load MANIFEST.json. Returns None if file is missing or unparseable."""
    try:
        with open(manifest_path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None

    # Normalize: build a class-id → class-entry lookup
    classes = manifest.get("classes", [])
    return {c["id"]: c for c in classes}


def _load_profiles(profile_path: str) -> dict[str, dict[str, Any]] | None:
    """Dynamically import a Python module and extract BASE_PROFILES.

    Uses importlib to handle arbitrary file paths without modifying
    sys.path permanently. Returns None on any import or attribute error.
    """
    try:
        module_name = "loader"
        spec = importlib.util.spec_from_file_location(
            module_name, profile_path
        )
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except Exception:
        return None

    return getattr(module, "BASE_PROFILES", None)


# ── Core check ───────────────────────────────────────────────────────────────


def check_tutor_drift(
    manifest_path: str,
    profile_path: str,
) -> list[dict[str, str]]:
    """Check for drift between Tutor classes and mesh profile refs.

    Args:
        manifest_path: Path to MANIFEST.json (lm-tutor class registry).
        profile_path: Path to loader.py containing BASE_PROFILES.

    Returns:
        List of findings, each with 'severity' and 'message' keys.
        Severities: 'ok', 'info', 'warn'. Never raises.
    """
    findings: list[dict[str, str]] = []

    manifest = _load_manifest(manifest_path)
    profiles = _load_profiles(profile_path)

    # Graceful: empty findings if neither side exists
    if manifest is None:
        return findings
    if profiles is None:
        return findings

    # Build set of class IDs referenced by any profile
    referenced_ids: set[str] = set()

    for profile_id, profile in profiles.items():
        tutor_refs = profile.get("tutor_refs")
        if not tutor_refs:
            continue

        for class_id, constraint in tutor_refs.items():
            referenced_ids.add(class_id)

            if class_id not in manifest:
                findings.append({
                    "severity": "warn",
                    "message": (
                        f"Profile '{profile_id}' references Tutor class "
                        f"'{class_id}' {constraint} which does not exist in "
                        f"MANIFEST.json"
                    ),
                })
                continue

            class_entry = manifest[class_id]
            actual_version = class_entry.get("version", "0.0")

            if _version_satisfies(actual_version, constraint):
                findings.append({
                    "severity": "ok",
                    "message": (
                        f"Profile '{profile_id}' ref {class_id} {constraint} "
                        f"satisfied (manifest has v{actual_version})"
                    ),
                })
            else:
                findings.append({
                    "severity": "warn",
                    "message": (
                        f"Profile '{profile_id}' requires {class_id} "
                        f"{constraint} but MANIFEST.json has v{actual_version}"
                    ),
                })

    # Orphaned classes: in manifest but not referenced by any profile
    orphaned = set(manifest.keys()) - referenced_ids
    for class_id in sorted(orphaned):
        findings.append({
            "severity": "info",
            "message": (
                f"Class '{class_id}' (v{manifest[class_id].get('version', '?')}) "
                f"not referenced by any profile"
            ),
        })

    return findings
