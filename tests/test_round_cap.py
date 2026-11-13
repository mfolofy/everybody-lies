"""Optional round cap: round 2 re-checks fixes, the cap gives STUCK. All calls mocked."""
import json

import pytest

import everybody_lies.gatekeeper as g
from everybody_lies.config import apply_local_chart, deep_merge, get_limit
from conftest import APPROVE, DIFF, REJECT


def _review(monkeypatch, responses, **kw):
    """Run run_review with every model call mocked; returns (result, prompts)."""
    prompts = []

    def fake_llm(model, system, user, **_kw):
        prompts.append(user)
        if "House's boss" in system:  # Cuddy
            return "## Summary\n- **Verdict:** PASS"
        if "gatekeeper" in system.lower() and "Final Verdict" in system:  # House
            return responses["house"]
        return responses["spec"]

    monkeypatch.setattr(g, "call_llm", fake_llm)
    result = g.run_review(diff_text=DIFF, files=["app/mod.py"], title="my change", tier="fast",
                          tier_explicit=True, **kw)
    return result, prompts


def test_get_limit_parsing(monkeypatch):
    monkeypatch.delenv("X_LIM", raising=False)
    assert get_limit({}, "max_rounds", "X_LIM") is None
    assert get_limit({"limits": {"max_rounds": None}}, "max_rounds", "X_LIM") is None
    assert get_limit({"limits": {"max_rounds": 2}}, "max_rounds", "X_LIM") == 2
    monkeypatch.setenv("X_LIM", "5")
    assert get_limit({"limits": {"max_rounds": 2}}, "max_rounds", "X_LIM") == 5
    monkeypatch.setenv("X_LIM", "0")
    assert get_limit({"limits": {"max_rounds": 2}}, "max_rounds", "X_LIM") is None
    monkeypatch.setenv("X_LIM", "two")
    with pytest.raises(ValueError):
        get_limit({}, "max_rounds", "X_LIM")


def test_default_is_off_in_packaged_chart():
    chart = json.load(open(g.get_chart_path(), encoding="utf-8"))
    assert chart["limits"]["max_rounds"] is None
    assert chart["limits"]["daily_call_cap"] is None


def test_default_behaviour_unchanged_without_cap(house_home, monkeypatch):
    for _ in range(4):
        result, prompts = _review(monkeypatch, {"spec": REJECT, "house": "## House's Final Verdict: REJECTED"})
        assert result["verdict"] == "REJECTED"           # never STUCK without a cap
        assert not any("REVIEW ROUND" in p for p in prompts)


def test_round2_is_scoped_and_cap_gives_stuck(house_home, monkeypatch, capsys):
    monkeypatch.setenv("EVERYBODY_LIES_MAX_ROUNDS", "2")
    rejected = {"spec": REJECT, "house": "## House's Final Verdict: REJECTED"}

    r1, p1 = _review(monkeypatch, rejected)
    assert r1["verdict"] == "REJECTED" and r1["round"] == 1
    assert not any("REVIEW ROUND" in p for p in p1)

    r2, p2 = _review(monkeypatch, rejected)
    assert r2["verdict"] == "STUCK" and r2["round"] == 2
    assert any("fix the thing" in f for f in r2["round_findings"])
    assert any("REVIEW ROUND 2 OF 2" in p and "fix the thing" in p and "FINAL round" in p for p in p2)
    assert any("only if it is P1" in p for p in p2)
    assert "needs a person" in capsys.readouterr().out

    r3, p3 = _review(monkeypatch, rejected)              # past the cap: no model call at all
    assert r3["verdict"] == "STUCK" and p3 == []


def test_round2_can_still_approve(house_home, monkeypatch):
    monkeypatch.setenv("EVERYBODY_LIES_MAX_ROUNDS", "2")
    _review(monkeypatch, {"spec": REJECT, "house": "## House's Final Verdict: REJECTED"})
    r2, _ = _review(monkeypatch, {"spec": APPROVE, "house": "## House's Final Verdict: APPROVED"})
    assert r2["verdict"] == "APPROVED"
    # An approval starts a new sequence: the next change with this title is round 1 again.
    r3, p3 = _review(monkeypatch, {"spec": REJECT, "house": "## House's Final Verdict: REJECTED"})
    assert r3["round"] == 1 and r3["verdict"] == "REJECTED"


def test_override_env_lifts_the_cap(house_home, monkeypatch):
    monkeypatch.setenv("EVERYBODY_LIES_MAX_ROUNDS", "1")
    rejected = {"spec": REJECT, "house": "## House's Final Verdict: REJECTED"}
    assert _review(monkeypatch, rejected)[0]["verdict"] == "STUCK"   # round 1 of 1 failing
    monkeypatch.setenv("EVERYBODY_LIES_MAX_ROUNDS", "0")
    assert _review(monkeypatch, rejected)[0]["verdict"] == "REJECTED"


def test_cap_from_local_chart(house_home, monkeypatch):
    home, work = house_home
    (work / ".house").mkdir()
    (work / ".house" / "chart.local.json").write_text(json.dumps({"limits": {"max_rounds": 1}}), encoding="utf-8")
    result, _ = _review(monkeypatch, {"spec": REJECT, "house": "## House's Final Verdict: REJECTED"})
    assert result["verdict"] == "STUCK"


def test_archive_never_overwrites_so_rounds_keep_counting(house_home, monkeypatch):
    rejected = {"spec": REJECT, "house": "## House's Final Verdict: REJECTED"}
    for _ in range(5):
        _review(monkeypatch, rejected)
    date = g.datetime.now(g.timezone.utc).strftime("%Y-%m-%d")
    assert len(g._prior_rounds("my change", date)) == 5


def test_bad_limit_value_blocks(house_home, monkeypatch):
    monkeypatch.setenv("EVERYBODY_LIES_MAX_ROUNDS", "two")
    with pytest.raises(SystemExit) as exc:
        _review(monkeypatch, {"spec": APPROVE, "house": "APPROVED"})
    assert exc.value.code == 1


# -- repo-level chart override ------------------------------------------------

def test_deep_merge_dicts_and_id_lists():
    base = {"a": {"x": 1, "y": 2}, "s": [{"id": "foreman", "m": {"p": 1, "q": 2}}, {"id": "chase", "m": 1}]}
    over = {"a": {"y": 3}, "s": [{"id": "foreman", "m": {"p": 9}}, {"id": "new", "m": 0}]}
    merged = deep_merge(base, over)
    assert merged["a"] == {"x": 1, "y": 3}
    assert merged["s"][0] == {"id": "foreman", "m": {"p": 9, "q": 2}}
    assert [i["id"] for i in merged["s"]] == ["foreman", "chase", "new"]
    assert base["a"]["y"] == 2  # inputs untouched


def test_local_chart_missing_is_noop_and_malformed_raises(house_home):
    home, work = house_home
    chart = {"limits": {"max_rounds": None}}
    assert apply_local_chart(chart) == chart
    (work / ".house").mkdir()
    (work / ".house" / "chart.local.json").write_text("{nope", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        apply_local_chart(chart)
