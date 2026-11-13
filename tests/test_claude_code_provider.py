"""Claude Code provider: runs `claude -p` locally. Every test mocks subprocess."""
import json
import subprocess

import pytest

import everybody_lies.providers as providers
from everybody_lies.providers import (
    MODEL_ROUTING, PROVIDERS, auto_detect_model, call_llm, configured_provider,
    detect_available_providers, provider_available,
)

KEY_VARS = ("DEEPSEEK_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY")


@pytest.fixture
def no_keys(monkeypatch):
    for var in KEY_VARS:
        monkeypatch.delenv(var, raising=False)


def test_registered_and_routed():
    assert PROVIDERS["claude-code"]["cli"] == "claude"
    for model in ("claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5", "claude-fable-5-2"):
        assert MODEL_ROUTING[model] == ["claude-code"]


def test_call_uses_stdin_model_flag_and_plain_text(house_home, no_keys, fake_claude):
    out = call_llm("claude-opus-5-5", "SYSTEM RULES", "USER DIFF")
    assert out == "claude says hi"
    call = fake_claude[0]
    assert call["argv"][0].endswith("claude.exe")
    assert call["argv"][1:] == ["-p", "--model", "claude-opus-5-5", "--output-format", "text",
                                "--tools", "", "--strict-mcp-config", "--no-session-persistence"]
    assert "SYSTEM RULES" in call["input"] and "USER DIFF" in call["input"]
    assert "USER DIFF" not in " ".join(call["argv"])  # prompt never on the command line
    assert call["timeout"] > 0
    assert call["cwd"] != ""  # empty temp dir, not the repo


def test_model_name_passed_through_as_given(house_home, no_keys, fake_claude):
    call_llm("claude-fable-5-2", "s", "u")
    assert "claude-fable-5-2" in fake_claude[0]["argv"]


def test_missing_cli_gives_clear_error(house_home, no_keys, allow_claude_fn, monkeypatch):
    monkeypatch.setattr(providers.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError) as exc:
        call_llm("claude-sonnet-5-5", "s", "u")
    assert "not on PATH" in str(exc.value)


def test_timeout_and_nonzero_exit_are_errors(house_home, no_keys, fake_claude, monkeypatch):
    def timeout(argv, **kw):
        raise subprocess.TimeoutExpired(argv, kw["timeout"])
    monkeypatch.setattr(providers.subprocess, "run", timeout)
    with pytest.raises(RuntimeError, match="timed out"):
        call_llm("claude-sonnet-5-5", "s", "u")

    monkeypatch.setattr(providers.subprocess, "run",
                        lambda argv, **kw: subprocess.CompletedProcess(argv, 1, stdout="", stderr="not logged in"))
    with pytest.raises(RuntimeError, match="not logged in"):
        call_llm("claude-sonnet-5-5", "s", "u")


def test_timeout_env_override(house_home, no_keys, fake_claude, monkeypatch):
    monkeypatch.setenv("EVERYBODY_LIES_CLAUDE_TIMEOUT", "12")
    call_llm("claude-sonnet-5-5", "s", "u")
    assert fake_claude[0]["timeout"] == 12.0


def test_auto_detect_only_without_api_keys(no_keys, fake_claude, monkeypatch):
    assert detect_available_providers() == ["claude-code"]
    assert auto_detect_model() == "claude-sonnet-5-5"
    # Existing users with a key: behaviour unchanged, the CLI is not added.
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    assert detect_available_providers() == ["deepseek"]
    assert auto_detect_model() == "deepseek-flash"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert auto_detect_model() == "claude-sonnet-4-6"


def test_auto_detect_none_when_cli_absent(no_keys, monkeypatch):
    monkeypatch.setattr(providers.shutil, "which", lambda name: None)
    assert detect_available_providers() == []
    assert auto_detect_model() is None
    assert provider_available("claude-code") is False


def test_config_selects_provider_and_routes_every_model(house_home, no_keys, fake_claude, monkeypatch):
    home, work = house_home
    (work / ".house").mkdir()
    (work / ".house" / "chart.local.json").write_text(
        json.dumps({"model_config": {"provider": "claude-code"}}), encoding="utf-8")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")  # a key is set, config still wins
    assert configured_provider() == "claude-code"
    call_llm("claude-haiku-4-5", "s", "u")  # an API-routed id now goes through the CLI
    assert fake_claude[0]["argv"][3] == "claude-haiku-4-5"


def test_env_selects_provider_and_bad_value_is_rejected(house_home, monkeypatch):
    monkeypatch.setenv("EVERYBODY_LIES_PROVIDER", "claude-code")
    assert configured_provider() == "claude-code"
    monkeypatch.setenv("EVERYBODY_LIES_PROVIDER", "auto")
    assert configured_provider() is None
    monkeypatch.setenv("EVERYBODY_LIES_PROVIDER", "claude_code")
    with pytest.raises(ValueError, match="unknown provider"):
        configured_provider()


def test_default_routing_unchanged_for_api_models(house_home, no_keys, fake_claude):
    # No provider forced, no key: an API model must NOT fall into the CLI.
    with pytest.raises(RuntimeError, match="All providers failed"):
        call_llm("claude-sonnet-4-6", "s", "u")
    assert fake_claude == []
