"""Glob matching used by specialist routing (chart.json) and patients.json.

Up to 0.3.1, any pattern with ** followed by a wildcard ("**/*.py") never
matched, because the text after "**/" was searched as a literal string.
"""
import json
from pathlib import Path

from everybody_lies.scanner import _match_file_pattern as m

MATCH = [
    ("a.py", "**/*.py"),
    ("src/a.py", "**/*.py"),
    ("src/deep/er/a.py", "**/*.py"),
    ("vendor/k.pem", "**/*.pem"),
    ("app/.env.local", "**/.env*"),
    ("src/a.tsx", "**/*.{ts,tsx}"),
    ("src/test_a.py", "**/test_*.py"),
    ("docs/x/y.md", "docs/**"),
    ("docs", "docs/**"),
    ("a/docs/b.md", "**/docs/**"),
    ("docs/b.md", "**/docs/**"),
    ("secrets/token.txt", "secrets/**"),
    ("x/jm-pack/r.md", "**/jm-*/**"),
    ("src/a.ts", "*.ts"),          # no **: plain fnmatch, * crosses folders
    ("a/b/c.txt", "**"),
    ("a/b/c.txt", "**/*"),
]

NO_MATCH = [
    ("src/a.pyc", "**/*.py"),
    ("src/a.py.bak", "**/*.py"),
    ("a/mydocs/b.md", "**/docs/**"),
    ("docsx/y.md", "docs/**"),
    ("src/a.js", "**/*.{ts,tsx}"),
    ("x/jm/r.md", "**/jm-*/**"),
]


def test_double_star_patterns_match():
    misses = [(p, pat) for p, pat in MATCH if not m(p, pat)]
    assert not misses, misses


def test_double_star_patterns_reject():
    hits = [(p, pat) for p, pat in NO_MATCH if m(p, pat)]
    assert not hits, hits


def test_windows_separators():
    assert m("src\\deep\\a.py", "**/*.py")


def test_every_chart_pattern_matches_something():
    chart = json.loads(
        (Path(__file__).resolve().parents[1] / "everybody_lies" / "chart.json").read_text(encoding="utf-8")
    )
    patterns = set()

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str) and "**" in o and len(o) < 60:
            patterns.add(o)

    walk(chart)
    assert patterns, "no ** patterns found in chart.json"
    dead = []
    for pat in patterns:
        sample = pat.replace("**/", "src/").replace("/**", "/x").replace("**", "x")
        sample = sample.replace("*", "x").replace("?", "x")
        if "{" in sample:
            sample = sample[: sample.index("{")] + sample[sample.index("{") + 1:].split(",")[0].split("}")[0]
        if not m(sample, pat):
            dead.append((pat, sample))
    assert not dead, dead


if __name__ == "__main__":
    import sys

    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except AssertionError as exc:
                failures += 1
                print("FAIL", name, exc)
    sys.exit(1 if failures else 0)
