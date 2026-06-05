import os, pytest
from unittest.mock import patch
from pathlib import Path


def test_no_files_returns_empty(tmp_path):
    with patch("subprocess.check_output", return_value=str(tmp_path).encode()):
        from everybody_lies.gatekeeper import _find_locked_decisions_from_repo
        assert _find_locked_decisions_from_repo() == ""


def test_charter_locked_decisions(tmp_path):
    charter = tmp_path / "CHARTER.md"
    charter.write_text("# Project\n\n## Locked Decisions\n\n- React stack: MIT only\n- No passwords Phase 1-B\n\n## Other section\n\nignored")
    with patch("subprocess.check_output", return_value=str(tmp_path).encode()):
        from everybody_lies import gatekeeper
        import importlib; importlib.reload(gatekeeper)
        result = gatekeeper._find_locked_decisions_from_repo()
        assert "React stack" in result
        assert "Other section" not in result


def test_case_insensitive_header(tmp_path):
    f = tmp_path / "CHARTER.md"
    f.write_text("## LOCKED DECISIONS\n\n- item1\n")
    with patch("subprocess.check_output", return_value=str(tmp_path).encode()):
        from everybody_lies import gatekeeper
        import importlib; importlib.reload(gatekeeper)
        result = gatekeeper._find_locked_decisions_from_repo()
        assert "item1" in result


def test_caps_at_5_files(tmp_path):
    for i in range(7):
        f = tmp_path / f"PHASE{i}_PRD.md"
        f.write_text(f"## Locked Decisions\n\n- item{i}\n")
    with patch("subprocess.check_output", return_value=str(tmp_path).encode()):
        from everybody_lies import gatekeeper
        import importlib; importlib.reload(gatekeeper)
        result = gatekeeper._find_locked_decisions_from_repo()
        # At most 5 files processed
        count = result.count("item")
        assert count <= 5


def test_git_unavailable_returns_empty():
    with patch("subprocess.check_output", side_effect=Exception("no git")):
        from everybody_lies.gatekeeper import _find_locked_decisions_from_repo
        assert _find_locked_decisions_from_repo() == ""
