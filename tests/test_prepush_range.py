"""Pre-push commit/object range resolution.

Covers the new-branch (zero-sha) case: pushing a brand-new branch must review
only the commits unique to that branch (merge-base(main, tip)..tip), NOT the
full history of main — otherwise pre-existing out-of-scope objects already in
main get re-flagged as if they were new work.
"""
import subprocess
from pathlib import Path

import pytest

from everybody_lies.gatekeeper import _git_rev_list_objects, _NULL_SHA


def _git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A repo with main carrying a historical out-of-scope file, plus a new
    branch adding one new in-scope file."""
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@t.t")
    _git(tmp_path, "config", "user.name", "t")
    # main history: a pre-existing out-of-scope object (e.g. a vendored pem)
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "cacert.pem").write_text("OLD")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "historical vendored pem")
    main_tip = _git(tmp_path, "rev-parse", "HEAD")
    # new branch off main adds only one new file
    _git(tmp_path, "checkout", "-b", "feature")
    (tmp_path / "feature.txt").write_text("new work")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "feature work")
    feat_tip = _git(tmp_path, "rev-parse", "HEAD")
    monkeypatch.chdir(tmp_path)
    return {"path": tmp_path, "main_tip": main_tip, "feat_tip": feat_tip}


def test_new_branch_reviews_only_unique_objects(repo):
    # remote_sha == NULL_SHA (brand-new branch on origin)
    objs = _git_rev_list_objects(_NULL_SHA, repo["feat_tip"])
    assert "feature.txt" in objs
    # historical pem already in main must NOT be re-flagged
    assert "vendor/cacert.pem" not in objs


def test_existing_branch_uses_remote_tip(repo):
    # non-zero remote sha: classic old..new range, behavior unchanged
    objs = _git_rev_list_objects(repo["main_tip"], repo["feat_tip"])
    assert "feature.txt" in objs
    assert "vendor/cacert.pem" not in objs


def test_new_branch_no_mergebase_reviews_tip_only(tmp_path, monkeypatch):
    # An orphan branch with no merge-base against main: must review only the
    # tip commit, not nothing-bounded full history.
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@t.t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "a.txt").write_text("a")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "main root")
    _git(tmp_path, "checkout", "--orphan", "orphan")
    _git(tmp_path, "rm", "-rf", ".")
    (tmp_path / "b.txt").write_text("b")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "orphan root")
    orphan_tip = _git(tmp_path, "rev-parse", "HEAD")
    monkeypatch.chdir(tmp_path)
    objs = _git_rev_list_objects(_NULL_SHA, orphan_tip)
    assert "b.txt" in objs
