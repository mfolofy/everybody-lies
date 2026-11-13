"""Pre-push scope check must see paths, not only new objects.

A blocked path whose content already exists in the repo (an empty file, a
copy, a rename) adds no new blob, so `git rev-list --objects` does not list
it. _git_changed_paths covers that case.
"""
import subprocess

import pytest

from everybody_lies.gatekeeper import (
    _NULL_SHA,
    _check_paths_against_scope,
    _git_changed_paths,
    _git_rev_list_objects,
)

POLICY = {"allowed_paths": [], "blocked_paths": ["*.docx", "secret/*"]}


def _git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@t.t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "empty.txt").write_text("")
    (tmp_path / "notes.md").write_text("shared content")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "base")
    base = _git(tmp_path, "rev-parse", "HEAD")
    monkeypatch.chdir(tmp_path)
    return {"path": tmp_path, "base": base}


def _commit(repo, msg):
    _git(repo["path"], "add", "-A")
    _git(repo["path"], "commit", "-m", msg)
    return _git(repo["path"], "rev-parse", "HEAD")


def test_empty_blocked_file_is_seen(repo):
    (repo["path"] / "report.docx").write_text("")
    tip = _commit(repo, "empty docx")
    # the empty blob already exists, so the object walk misses the path
    assert "report.docx" not in _git_rev_list_objects(repo["base"], tip)
    assert "report.docx" in _git_changed_paths(repo["base"], tip)
    assert _check_paths_against_scope(_git_changed_paths(repo["base"], tip), POLICY)


def test_copy_and_rename_into_blocked_path_are_seen(repo):
    (repo["path"] / "secret").mkdir()
    (repo["path"] / "secret" / "copy.md").write_text("shared content")
    _git(repo["path"], "mv", "empty.txt", "moved.docx")
    tip = _commit(repo, "copy and rename")
    paths = _git_changed_paths(repo["base"], tip)
    assert "secret/copy.md" in paths
    assert "moved.docx" in paths


def test_deletions_are_not_listed(repo):
    (repo["path"] / "notes.md").unlink()
    tip = _commit(repo, "delete")
    assert "notes.md" not in _git_changed_paths(repo["base"], tip)


def test_new_branch_uses_merge_base(repo):
    _git(repo["path"], "checkout", "-b", "feature")
    (repo["path"] / "x.docx").write_text("")
    tip = _commit(repo, "feature")
    paths = _git_changed_paths(_NULL_SHA, tip)
    assert paths == ["x.docx"]
