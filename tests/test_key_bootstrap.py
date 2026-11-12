"""Key bootstrap source 3: only an UNTRACKED secrets/house-api-keys.json inside the
current repo loads. Tracked copies (any case), files outside the repo, and git
errors all fail closed."""
import json
import os
import subprocess

import pytest

from everybody_lies import providers

VAR = "DEEPSEEK_API_KEY"


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _write_keys(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({VAR: "from-file"}), encoding="utf-8")


@pytest.fixture
def clean_env(monkeypatch):
    for v in providers._KNOWN_VARS:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.delenv("EVERYBODY_LIES_API_KEYS", raising=False)
    monkeypatch.delenv("EVERYBODY_LIES_SECRETS_FILE", raising=False)
    yield
    os.environ.pop(VAR, None)


@pytest.fixture
def repo(tmp_path, clean_env, monkeypatch):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    monkeypatch.chdir(r)
    return r


def test_untracked_keys_file_is_loaded(repo):
    _write_keys(repo / "secrets" / "house-api-keys.json")
    providers._bootstrap_keys()
    assert os.environ.get(VAR) == "from-file"


def test_untracked_keys_file_found_from_subdirectory(repo, monkeypatch):
    _write_keys(repo / "secrets" / "house-api-keys.json")
    (repo / "pkg" / "sub").mkdir(parents=True)
    monkeypatch.chdir(repo / "pkg" / "sub")
    providers._bootstrap_keys()
    assert os.environ.get(VAR) == "from-file"


def test_tracked_keys_file_is_ignored(repo):
    _write_keys(repo / "secrets" / "house-api-keys.json")
    _git(repo, "add", "-f", "secrets/house-api-keys.json")
    providers._bootstrap_keys()
    assert os.environ.get(VAR) is None


def test_tracked_case_variant_is_ignored(repo):
    _write_keys(repo / "Secrets" / "House-Api-Keys.json")
    _git(repo, "add", "-f", "Secrets/House-Api-Keys.json")
    providers._bootstrap_keys()
    assert os.environ.get(VAR) is None


def test_keys_file_above_repo_top_is_ignored(tmp_path, clean_env, monkeypatch):
    _write_keys(tmp_path / "secrets" / "house-api-keys.json")
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    monkeypatch.chdir(r)
    providers._bootstrap_keys()
    assert os.environ.get(VAR) is None


def test_outside_any_repo_nothing_loads(tmp_path, clean_env, monkeypatch):
    _write_keys(tmp_path / "secrets" / "house-api-keys.json")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    monkeypatch.chdir(tmp_path)
    providers._bootstrap_keys()
    assert os.environ.get(VAR) is None


def test_missing_git_fails_closed(repo, monkeypatch):
    _write_keys(repo / "secrets" / "house-api-keys.json")
    monkeypatch.setattr("shutil.which", lambda _name: None)
    providers._bootstrap_keys()
    assert os.environ.get(VAR) is None


def test_openrouter_only_has_a_fallback(clean_env, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    fallbacks = providers.available_fallback_models()
    assert fallbacks and not any("deepseek" in m for m in fallbacks)


@pytest.mark.parametrize("model", ["deepseek/deepseek-v4-flash", "deepseek-v4-flash", "deepseek/deepseek-flash"])
def test_deepseek_ids_never_route_to_openrouter(clean_env, monkeypatch, model):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    with pytest.raises(RuntimeError, match="DeepSeek"):
        providers.call_llm(model, "s", "u")


def test_tracked_file_ignored_with_inherited_git_dir(repo, monkeypatch):
    _write_keys(repo / "secrets" / "house-api-keys.json")
    _git(repo, "add", "-f", "secrets/house-api-keys.json")
    monkeypatch.setenv("GIT_DIR", str(repo / ".git"))
    providers._bootstrap_keys()
    assert os.environ.get(VAR) is None


def test_tracked_file_ignored_in_linked_worktree_hook_env(repo, monkeypatch):
    _write_keys(repo / "secrets" / "house-api-keys.json")
    _git(repo, "add", "-f", "secrets/house-api-keys.json")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "keys")
    wt = repo.parent / "wt"
    _git(repo, "worktree", "add", "-q", str(wt))
    gitdir = subprocess.run(["git", "-C", str(wt), "rev-parse", "--absolute-git-dir"],
                            capture_output=True, text=True, check=True).stdout.strip()
    monkeypatch.chdir(wt)
    monkeypatch.setenv("GIT_DIR", gitdir)                      # what git exports to hooks
    monkeypatch.setenv("GIT_INDEX_FILE", os.path.join(gitdir, "index"))
    providers._bootstrap_keys()
    assert os.environ.get(VAR) is None
