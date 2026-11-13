"""Shared fixtures. Everything here is local: no network, no real `claude`."""
import json
import subprocess

import pytest

import everybody_lies.providers as _providers

_REAL_CLAUDE_CALL = _providers._call_claude_code

# A benign, non-trivial diff (more than the fast-track threshold, no scanner hits).
DIFF = "diff --git a/app/mod.py b/app/mod.py\n--- a/app/mod.py\n+++ b/app/mod.py\n@@ -0,0 +1,40 @@\n" + "".join(
    f"+def helper_{i}(value):\n+    return value + {i}\n" for i in range(20)
)

REJECT = ('## Findings\n- **Severity:** P2\n- **Issue:** something to fix\n\n'
          '## Summary\n- **Verdict:** FAIL\n\n```verdict\n'
          '{"verdict": "REJECT", "max_severity": "P2", "blocking_findings": ["fix the thing"]}\n```')
APPROVE = ('## Findings\nNone.\n\n## Summary\n- **Verdict:** PASS\n\n```verdict\n'
           '{"verdict": "APPROVE", "max_severity": "NONE", "blocking_findings": []}\n```')


@pytest.fixture(autouse=True)
def _hermetic(request, tmp_path_factory, monkeypatch):
    """Keep the suite offline and independent of the checkout it runs in.

    - A repo's own .house/chart.local.json (e.g. a private provider choice) must not
      leak into tests, so the local-override lookup points at an empty folder.
    - The real `claude` call is blocked unless the test mocks subprocess
      (fake_claude) or opts in (allow_claude_fn); a test can never reach a model.
    """
    empty = tmp_path_factory.mktemp("no_local_chart")
    monkeypatch.setattr("everybody_lies.config.get_local_chart_path",
                        lambda: empty / ".house" / "chart.local.json")
    monkeypatch.delenv("EVERYBODY_LIES_PROVIDER", raising=False)
    if not {"fake_claude", "allow_claude_fn"} & set(request.fixturenames):
        def _blocked(*a, **k):
            raise AssertionError("test tried to run the real `claude` CLI")
        monkeypatch.setattr(_providers, "_call_claude_code", _blocked)


@pytest.fixture
def allow_claude_fn():
    """Use the real _call_claude_code (the test must mock shutil.which/subprocess itself)."""


@pytest.fixture
def house_home(tmp_path, monkeypatch):
    """Isolated config dir + cwd (not a git repo), no limits, no forced provider."""
    import everybody_lies.gatekeeper as g
    home = tmp_path / "home"
    work = tmp_path / "work"
    home.mkdir()
    work.mkdir()
    monkeypatch.setenv("EVERYBODY_LIES_HOME", str(home))
    monkeypatch.setenv("HOUSE_GATE", json.dumps({"subagents_running": False}))
    for var in ("EVERYBODY_LIES_MAX_ROUNDS", "EVERYBODY_LIES_DAILY_CALL_CAP",
                "EVERYBODY_LIES_PROVIDER", "EVERYBODY_LIES_CHART", "HOUSE_BYPASS"):
        monkeypatch.delenv(var, raising=False)
    g._HOUSE_GATE_CACHE = None
    monkeypatch.chdir(work)
    # Never let the config lookup find a real repo's .house/chart.local.json.
    monkeypatch.setattr("everybody_lies.config.get_local_chart_path",
                        lambda: work / ".house" / "chart.local.json")
    return home, work


@pytest.fixture
def fake_claude(monkeypatch):
    """Pretend `claude` is on PATH and record every subprocess call (never runs it)."""
    import everybody_lies.providers as p
    calls = []
    real_run = subprocess.run

    def fake_run(argv, **kwargs):
        if not str(argv[0]).lower().endswith("claude.exe"):
            return real_run(argv, **kwargs)  # git etc. still work
        calls.append({"argv": argv, **kwargs})
        return subprocess.CompletedProcess(argv, 0, stdout="claude says hi\n", stderr="")

    monkeypatch.setattr(p.shutil, "which", lambda name: "C:\\bin\\claude.exe" if name == "claude" else None)
    monkeypatch.setattr(p.subprocess, "run", fake_run)
    return calls
