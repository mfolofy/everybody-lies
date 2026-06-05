import os, pytest
from unittest.mock import patch
from pathlib import Path


def test_no_files_returns_empty(tmp_path):
    """No spec files present → returns empty string."""
    with patch("subprocess.check_output", return_value=str(tmp_path).encode()):
        from everybody_lies.gatekeeper import _find_locked_decisions_from_repo
        assert _find_locked_decisions_from_repo() == ""


def test_charter_locked_decisions(tmp_path):
    """CHARTER.md with ## Locked Decisions → section extracted, other sections not."""
    charter = tmp_path / "CHARTER.md"
    charter.write_text(
        "# Project\n\n"
        "## Locked Decisions\n\n"
        "- React stack: MIT only\n"
        "- No passwords Phase 1-B\n\n"
        "## Other section\n\n"
        "ignored"
    )
    with patch("subprocess.check_output", return_value=str(tmp_path).encode()):
        from everybody_lies import gatekeeper
        import importlib; importlib.reload(gatekeeper)
        result = gatekeeper._find_locked_decisions_from_repo()
        assert "React stack" in result
        assert "[From CHARTER.md]" in result
        assert "Other section" not in result


def test_phase_prd(tmp_path):
    """PHASE1B_PRD.md with ## Locked Decisions → extracted."""
    prd = tmp_path / "PHASE1B_PRD.md"
    prd.write_text("# Phase 1B\n\n## Locked Decisions\n\n- Use React 18\n- Name-only auth\n")
    with patch("subprocess.check_output", return_value=str(tmp_path).encode()):
        from everybody_lies import gatekeeper
        import importlib; importlib.reload(gatekeeper)
        result = gatekeeper._find_locked_decisions_from_repo()
        assert "Use React 18" in result
        assert "[From PHASE1B_PRD.md]" in result


def test_multiple_files(tmp_path):
    """Both CHARTER.md and PHASE1B_PRD.md → both sections included."""
    (tmp_path / "CHARTER.md").write_text("## Locked Decisions\n\n- Charter item\n")
    (tmp_path / "PHASE1B_PRD.md").write_text("## Locked Decisions\n\n- Phase item\n")
    with patch("subprocess.check_output", return_value=str(tmp_path).encode()):
        from everybody_lies import gatekeeper
        import importlib; importlib.reload(gatekeeper)
        result = gatekeeper._find_locked_decisions_from_repo()
        assert "Charter item" in result
        assert "Phase item" in result


def test_caps_variant(tmp_path):
    """## LOCKED DECISIONS → matched (case-insensitive)."""
    f = tmp_path / "CHARTER.md"
    f.write_text("## LOCKED DECISIONS\n\n- item1\n")
    with patch("subprocess.check_output", return_value=str(tmp_path).encode()):
        from everybody_lies import gatekeeper
        import importlib; importlib.reload(gatekeeper)
        result = gatekeeper._find_locked_decisions_from_repo()
        assert "item1" in result


def test_case_insensitive_header(tmp_path):
    """## Locked decisions (lowercase) → matched (case-insensitive)."""
    f = tmp_path / "CHARTER.md"
    f.write_text("## Locked decisions\n\n- item1\n")
    with patch("subprocess.check_output", return_value=str(tmp_path).encode()):
        from everybody_lies import gatekeeper
        import importlib; importlib.reload(gatekeeper)
        result = gatekeeper._find_locked_decisions_from_repo()
        assert "item1" in result


def test_cap_at_5_files(tmp_path):
    """7 spec files → only 5 processed (keeps Cuddy prompt bounded)."""
    for i in range(7):
        f = tmp_path / f"PHASE{i}_PRD.md"
        f.write_text(f"## Locked Decisions\n\n- item{i}\n")
    with patch("subprocess.check_output", return_value=str(tmp_path).encode()):
        from everybody_lies import gatekeeper
        import importlib; importlib.reload(gatekeeper)
        result = gatekeeper._find_locked_decisions_from_repo()
        # At most 5 files processed, each has one "item" reference
        count = result.count("item")
        assert count <= 5


def test_next_heading_stops_extraction(tmp_path):
    """Section extraction stops at next ## heading, doesn't bleed into following section."""
    f = tmp_path / "CHARTER.md"
    f.write_text(
        "## Locked Decisions\n\n"
        "- React stack: MIT only\n\n"
        "## Deployment\n\n"
        "- Use Vercel\n"
    )
    with patch("subprocess.check_output", return_value=str(tmp_path).encode()):
        from everybody_lies import gatekeeper
        import importlib; importlib.reload(gatekeeper)
        result = gatekeeper._find_locked_decisions_from_repo()
        assert "React stack" in result
        assert "Vercel" not in result


def test_git_unavailable_returns_empty():
    """git rev-parse fails → returns empty string."""
    with patch("subprocess.check_output", side_effect=Exception("no git")):
        from everybody_lies.gatekeeper import _find_locked_decisions_from_repo
        assert _find_locked_decisions_from_repo() == ""
