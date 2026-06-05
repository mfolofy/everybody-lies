"""House — Code Review Gatekeeper.

Dispatches a multi-specialist code review against a git diff.
Routes changed files to domain specialists, collects findings,
and issues a final verdict. ITIL-compliant throughout.

This module is the core review pipeline. The CLI lives in cli.py.
"""

import fnmatch
import json
import os
import re
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _count_running_opencode_subagents() -> int:
    """Return the number of running opencode processes that are NOT ancestors of
    the current process (i.e. stale subagents, not the caller's own session).

    Uses psutil when available for reliable cross-platform results; falls back
    to a subprocess-based approach on Windows and POSIX.

    The caller's own opencode session (the one that invoked House via pre-commit)
    is an ancestor of this process — we exclude the entire ancestor chain so we
    never block a legitimate commit triggered from inside opencode.
    """
    import os

    # Build the set of ancestor PIDs so we never flag the calling session.
    ancestor_pids: set[int] = set()
    try:
        pid = os.getpid()
        while pid:
            ancestor_pids.add(pid)
            # Read parent PID from /proc (Linux/macOS) or via psutil
            try:
                import psutil  # type: ignore
                parent = psutil.Process(pid).parent()
                pid = parent.pid if parent else 0
            except Exception:
                # Fallback: stop ancestor walk — we'll at least exclude self
                break
    except Exception:
        ancestor_pids.add(os.getpid())

    try:
        import psutil  # type: ignore
        count = 0
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                if "opencode" in proc.info["name"].lower():
                    if proc.info["pid"] not in ancestor_pids:
                        count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                pass
        return count
    except ImportError:
        pass

    # psutil unavailable — use platform subprocess fallback
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq opencode.exe", "/NH", "/FO", "CSV"],
                capture_output=True, text=True, timeout=5,
            )
            lines = [l for l in result.stdout.strip().splitlines() if "opencode" in l.lower()]
        else:
            result = subprocess.run(
                ["pgrep", "-x", "opencode"],
                capture_output=True, text=True, timeout=5,
            )
            lines = result.stdout.strip().splitlines()

        # Exclude ancestors
        pids = set()
        for line in lines:
            try:
                pid_str = line.strip().strip('"').split(",")[1].strip('"') if sys.platform == "win32" else line.strip()
                pid = int(pid_str)
                if pid not in ancestor_pids:
                    pids.add(pid)
            except (ValueError, IndexError):
                pass
        return len(pids)
    except Exception:
        return 0  # can't detect — don't block


def _check_no_running_subagents() -> None:
    """Cuddy pre-flight: block the commit if stale opencode subagents are running.

    Stale subagents hold RAM, may have uncommitted changes in flight, and can
    race with this commit. Cuddy refuses to sign off while the house is on fire.

    Skipped when HOUSE_BYPASS is set.
    """
    if os.environ.get("HOUSE_BYPASS"):
        return
    count = _count_running_opencode_subagents()
    if count > 0:
        print(f"\n{'=' * 70}", file=sys.stderr)
        print(f"  [CUDDY — PRE-FLIGHT BLOCKED]", file=sys.stderr)
        print(f"  Dr. Lisa Cuddy, Dean of Medicine", file=sys.stderr)
        print(f"{'=' * 70}", file=sys.stderr)
        print(f"", file=sys.stderr)
        print(f"  {count} running opencode subagent(s) detected.", file=sys.stderr)
        print(f"", file=sys.stderr)
        print(f"  Committing while subagents are running is like performing surgery", file=sys.stderr)
        print(f"  during a fire drill. Those agents may have uncommitted changes,", file=sys.stderr)
        print(f"  in-flight file edits, or unfinished builds that will conflict.", file=sys.stderr)
        print(f"", file=sys.stderr)
        print(f"  Wait for all subagents to finish, then commit.", file=sys.stderr)
        print(f"  Or set HOUSE_BYPASS=1 if you know what you're doing.", file=sys.stderr)
        print(f"", file=sys.stderr)
        print(f"{'=' * 70}", file=sys.stderr)
        sys.exit(1)

# ── Pre-push patient file — scope enforcement ────────────────────────────────
#
# Design decisions (pre-ruled-out alternatives):
#
# 1. Not server-side: we do not control CI on external remotes (shiftctl, etc.).
#    Server-side is ideal long-term; client-side is the only option available now.
#
# 2. Not shell-only: this fleet runs Windows + macOS + Linux. Shell glob matching
#    (**) is not portable. Python is already required (Cuddy pre-flight runs Python).
#
# 3. New functions not scan_diff reuse: scan_diff operates on staged diffs (index).
#    Pre-push operates on git objects (rev-list). Different data source. We reuse
#    _match_file_pattern from scanner.py for glob matching.
#
# 4. New patients.json not chart.json merger: chart.json is package-internal config
#    (specialists, models, tiers). patients.json is repo-level push policy — different
#    owner, different change cadence. Separation is intentional.

_PATIENTS_FILENAME = os.path.join(".house", "patients.json")
_NULL_SHA = "0" * 40  # SHA-1 null object; named constant to avoid magic strings


def _load_patients_config() -> dict:
    """Load .house/patients.json relative to repo root. Returns block-all default on error."""
    _default_policy: dict = {
        "allowed_paths": [],
        "blocked_paths": ["**"],
        "force_push": "deny",
        "block_tags": True,
        "block_deletes": True,
        "bypass_protected": False,
    }
    _fallback = {"remotes": {}, "default": _default_policy}
    try:
        # Resolve relative to repo root so this works regardless of cwd
        repo_root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        config_path = os.path.join(repo_root, _PATIENTS_FILENAME)
        with open(config_path, encoding="utf-8") as f:
            data = json.load(f)
        # Validate top-level shape
        if not isinstance(data.get("remotes"), dict):
            raise ValueError("patients.json missing 'remotes' dict")
        if "default" not in data:
            data["default"] = _default_policy
        return data
    except FileNotFoundError:
        return _fallback
    except (json.JSONDecodeError, ValueError, subprocess.CalledProcessError, OSError) as exc:
        print(f"[HOUSE] WARNING: patients.json load failed ({exc}) — using block-all default",
              file=sys.stderr)
        return _fallback


def _git_rev_list_objects(old_sha: str, new_sha: str) -> list[str]:
    """Return file paths introduced in old_sha..new_sha via git rev-list --objects.

    Uses old_sha (remote tip) as the base so only new objects are listed —
    handles force pushes correctly (does not re-scan historical objects).
    On new branches (old_sha == NULL_SHA), lists all objects in new_sha.
    """
    if old_sha == _NULL_SHA or not old_sha:
        cmd = ["git", "rev-list", "--objects", new_sha]
    else:
        cmd = ["git", "rev-list", "--objects", f"{old_sha}..{new_sha}"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"git rev-list failed: {result.stderr.strip()}")
    paths = []
    for line in result.stdout.splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2 and parts[1].strip():
            paths.append(parts[1].strip())
    return paths


def _check_paths_against_scope(files: list[str], remote_config: dict) -> list[str]:
    """Return list of violation strings for files that violate remote_config scope.

    blocked_paths always wins over allowed_paths.
    If allowed_paths is empty ([]), no path restriction applies (allow all).
    If allowed_paths is non-empty, files must match at least one pattern.
    """
    from .scanner import _match_file_pattern  # reuse existing glob matcher

    allowed = remote_config.get("allowed_paths", [])
    blocked = remote_config.get("blocked_paths", [])
    violations = []
    for f in files:
        # blocked wins unconditionally
        if any(_match_file_pattern(f, pat) for pat in blocked):
            violations.append(f"BLOCKED: {f}")
            continue
        # allowed=[]: no restriction. allowed non-empty: must match.
        if allowed and not any(_match_file_pattern(f, pat) for pat in allowed):
            violations.append(f"OUT-OF-SCOPE: {f}")
    return violations


def run_pre_push_check(remote_name: str, refs: list[dict]) -> dict:
    """Pre-push scope enforcement. Called by the pre-push git hook.

    refs: list of dicts with keys:
        local_ref  — refs/heads/branch or refs/tags/tag
        local_sha  — SHA of local commit being pushed (new_sha)
        remote_ref — refs/heads/branch on the remote
        remote_sha — SHA of current remote tip (old_sha)

    Returns dict with keys: verdict (APPROVED|REJECTED|BYPASSED),
    reason (str|None), violations (list|None).

    bypass_protected=True on a remote means HOUSE_BYPASS=1 does NOT skip it.
    """
    patients = _load_patients_config()
    remote_config = patients["remotes"].get(remote_name, patients["default"])
    bypass_active = (os.environ.get("HOUSE_BYPASS") == "1"
                     and not remote_config.get("bypass_protected", False))
    if bypass_active:
        return {"verdict": "BYPASSED", "reason": f"HOUSE_BYPASS on {remote_name}",
                "violations": None}

    files: list[str] = []
    for ref in refs:
        new_sha = ref.get("local_sha", "")    # local commit = what we're pushing
        old_sha = ref.get("remote_sha", _NULL_SHA)  # remote tip = where we're pushing from
        remote_ref = ref.get("remote_ref", "")

        if new_sha == _NULL_SHA or not new_sha:  # branch delete
            if remote_config.get("block_deletes", False):
                return {"verdict": "REJECTED",
                        "reason": f"branch delete blocked on '{remote_name}'",
                        "violations": None}
            continue

        if remote_ref.startswith("refs/tags/"):
            if remote_config.get("block_tags", False):
                return {"verdict": "REJECTED",
                        "reason": f"tag push blocked on '{remote_name}'",
                        "violations": None}
            continue

        force_push = (old_sha != _NULL_SHA and old_sha
                      and subprocess.run(
                          ["git", "merge-base", "--is-ancestor", old_sha, new_sha],
                          capture_output=True).returncode != 0)
        if force_push:
            policy = remote_config.get("force_push", "deny")
            if policy == "deny":
                return {"verdict": "REJECTED",
                        "reason": f"force push denied on '{remote_name}'",
                        "violations": None}
            if policy == "warn":
                print(f"[HOUSE] WARNING: force push to '{remote_name}' — proceed with caution",
                      file=sys.stderr)

        try:
            objects = _git_rev_list_objects(old_sha, new_sha)
            files.extend(objects)
        except Exception as exc:
            return {"verdict": "REJECTED",
                    "reason": f"git rev-list failed: {exc}",
                    "violations": None}

    try:
        violations = _check_paths_against_scope(files, remote_config)
    except Exception as exc:
        return {"verdict": "REJECTED",
                "reason": f"scope check failed: {exc}",
                "violations": None}

    if violations:
        return {"verdict": "REJECTED", "reason": "out-of-scope files detected",
                "violations": violations}
    return {"verdict": "APPROVED", "reason": None, "violations": None}


# ─────────────────────────────────────────────────────────────────────────────

from .config import (
    get_config_dir,
    get_chart_path,
    get_reviews_dir,
    get_stats_path,
    get_dynamic_fellows_path,
    get_appeals_log_path,
    get_commit_log_path,
    get_archive_dir,
    ensure_config_dir,
)
from .providers import (
    PROVIDERS,
    call_llm,
    resolve_specialist_model,
    auto_detect_model,
    detect_available_providers,
)
from .scanner import scan_diff, format_scan_result, is_trivial_diff
from .learning import (
    load_suppression_rules,
    is_suppressed,
    format_suppression_suggestions,
    detect_recurring_problems,
    format_problem_alerts,
    auto_create_problem_records,
)


# ── Dynamic Fellow System ─────────────────────────────────────────────────────

# Domain keywords → suggested fellow. House auto-hires when code touches
# domains that no existing fellow covers.
DOMAIN_HINTS = {
    "trading": {
        "keywords": ["trading_core", "gs-rev", "portfolio", "kelly", "position_size",
                     "stop_loss", "take_profit", "order_book", "exchange", "binance",
                     "kalshi", "polymarket", "alpaca", "market_data", "candle"],
        "domain": "Crypto & Algorithmic Trading",
        "expertise": "crypto markets, exchange APIs, order execution, risk management, Kelly criterion, technical indicators, market microstructure",
    },
    "quant": {
        "keywords": ["backtest", "sharpe_ratio", "alpha", "volatility", "var", "cvar",
                     "monte_carlo", "regression", "time_series", "statistical", "pandas_ta",
                     "numpy", "scipy", "correlation", "covariance"],
        "domain": "Quantitative Finance",
        "expertise": "statistical modeling, backtesting methodology, financial mathematics, risk metrics, time-series analysis, portfolio theory",
    },
    "blockchain": {
        "keywords": ["solidity", "web3", "ethereum", "contract", "nft", "defi",
                     "metamask", "wallet", "transaction", "gas", "blockchain", "token"],
        "domain": "Blockchain & Smart Contracts",
        "expertise": "smart contract security, gas optimization, DeFi protocols, token standards (ERC-20/721/1155), wallet integration, transaction lifecycle",
    },
    "ml_ai": {
        "keywords": ["train", "inference", "model", "neural", "embedding", "vector",
                     "llm", "transformer", "fine_tune", "rag", "tokenizer", "pytorch",
                     "tensorflow", "mlx", "qdrant", "pinecone", "langchain"],
        "domain": "Machine Learning & AI",
        "expertise": "model architecture, training pipelines, inference optimization, RAG systems, embeddings, GPU memory management, LLM deployment",
    },
    "devops_infra": {
        "keywords": ["docker", "kubernetes", "k8s", "terraform", "ansible", "helm",
                     "ci_cd", "github_actions", "jenkins", "argo", "prometheus",
                     "grafana", "alert", "pagerduty", "slo", "sla"],
        "domain": "DevOps & Infrastructure",
        "expertise": "container orchestration, IaC, CI/CD pipelines, observability, SRE practices, incident response, capacity planning",
    },
    "database": {
        "keywords": ["migration", "schema", "index", "query", "postgres", "mysql",
                     "mongo", "redis", "sql", "nosql", "replication", "shard",
                     "backup", "restore", "acid", "transaction"],
        "domain": "Database Engineering",
        "expertise": "schema design, query optimization, indexing strategy, replication, backup/restore, ACID compliance, migration safety",
    },
}

# Track dynamically hired fellows (persisted to disk for cross-session continuity)
_dynamic_fellows: dict[str, dict] = {}


def _load_dynamic_fellows() -> dict[str, dict]:
    """Load persisted dynamic fellows from disk."""
    path = get_dynamic_fellows_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_dynamic_fellows() -> None:
    """Persist dynamic fellows to disk for cross-session continuity."""
    ensure_config_dir()
    path = get_dynamic_fellows_path()
    path.write_text(json.dumps(_dynamic_fellows, indent=2), encoding="utf-8")


def _detect_uncovered_domains(files: list[str], existing_specialists: list[dict]) -> list[dict]:
    """Analyze file paths for domains not covered by existing specialists."""
    covered_domains = set()
    for spec in existing_specialists:
        for d in spec.get("domains", []):
            covered_domains.add(d)

    detected = []
    for domain_key, hint in DOMAIN_HINTS.items():
        if hint["domain"].lower() in covered_domains:
            continue
        matched = any(
            any(kw in f.lower() for kw in hint["keywords"])
            for f in files
        )
        if matched:
            detected.append({
                "key": domain_key,
                "domain": hint["domain"],
                "expertise": hint["expertise"],
                "trigger_files": [f for f in files if any(kw in f.lower() for kw in hint["keywords"])],
            })
    return detected


def _hire_fellow(domain_info: dict, tier: str, board: dict) -> dict:
    """Create a new specialist fellow for an uncovered domain."""
    domain = domain_info["domain"]
    expertise = domain_info["expertise"]
    key = domain_info["key"]
    trigger_files = domain_info.get("trigger_files", [])

    patterns = set()
    for f in trigger_files:
        parts = f.split("/")
        if len(parts) > 1:
            patterns.add(f"{parts[0]}/**")
        else:
            patterns.add(f"**/{f}")

    review_prompt = textwrap.dedent(f"""\
        You are a {domain} specialist, dynamically hired by House to review code
        touching domains no existing fellow covers.

        Your expertise: {expertise}

        Review the provided code diff for domain-specific issues:

        1. DOMAIN CORRECTNESS:
           - Does the implementation follow {domain} best practices?
           - Are there domain-specific pitfalls or anti-patterns?
           - Are the assumptions correct for this domain?

        2. DOMAIN SAFETY:
           - What are the domain-specific failure modes?
           - Are edge cases handled correctly for {domain}?
           - What domain-specific security concerns exist?

        3. DOMAIN PERFORMANCE:
           - Are there domain-specific performance considerations?
           - Is the approach optimal for {domain} workloads?

        For each finding, provide:
        1. Severity (P1/P2/P3/P4)
        2. Exact file and line number
        3. What's wrong (domain-specific)
        4. How to fix it
        5. Impact if not fixed

        You were hired because no existing fellow covers {domain}.
        Prove your worth.""")

    fellow_id = f"dynamic-{key}"
    if fellow_id in _dynamic_fellows:
        return _dynamic_fellows[fellow_id]

    fellow = {
        "id": fellow_id,
        "name": f"{domain} Specialist",
        "title": f"{domain} SME",
        "emoji": "🔧",
        "domains": [domain.lower()],
        "model_overrides": {"preferred": "deepseek-v4-flash", "standard": "deepseek-v4-flash", "budget": None},
        "file_patterns": sorted(patterns),
        "review_prompt": review_prompt,
        "dynamic": True,
        "hired_for": trigger_files,
        "review_count": 0,
        "unique_findings": 0,
    }

    _dynamic_fellows[fellow_id] = fellow
    return fellow


def _maybe_fire_fellow(fellow_id: str) -> bool:
    """Fire a dynamic fellow if they consistently produce no unique findings."""
    fellow = _dynamic_fellows.get(fellow_id)
    if not fellow:
        return False
    review_count = fellow.get("review_count", 0)
    unique_findings = fellow.get("unique_findings", 0)
    if review_count >= 5 and unique_findings == 0:
        del _dynamic_fellows[fellow_id]
        return True
    return False


def _get_all_specialists(board: dict) -> list[dict]:
    """Get all specialists: static from board + dynamically hired fellows."""
    return list(board.get("specialists", [])) + list(_dynamic_fellows.values())


# ── Helpers ────────────────────────────────────────────────────────────────────


def _safe(text: str) -> str:
    """Strip non-ASCII characters for safe terminal output."""
    return text.encode("ascii", errors="replace").decode("ascii")


def _load_json(path: Path) -> dict:
    """Load a JSON file. Exit with message if missing or malformed."""
    if not path.exists():
        print(f"ERROR: {path} not found.", file=sys.stderr)
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _get_git_diff(staged: bool = False, diff_arg: str = "") -> str:
    """Get git diff. Priority: diff_arg > staged > unstaged."""
    if diff_arg:
        return diff_arg
    try:
        if staged:
            result = subprocess.run(
                ["git", "diff", "--cached"],
                capture_output=True, cwd=Path.cwd(), timeout=10,
            )
        else:
            result = subprocess.run(
                ["git", "diff"],
                capture_output=True, cwd=Path.cwd(), timeout=10,
            )
        if result.returncode == 0:
            return result.stdout.decode("utf-8", errors="replace").strip()
        return ""
    except Exception:
        return ""


def _get_changed_files(diff_text: str) -> list[str]:
    """Extract changed file paths from a unified diff."""
    files = set()
    for line in diff_text.split("\n"):
        if line.startswith("diff --git"):
            parts = line.split(" ")
            if len(parts) >= 4:
                files.add(parts[3][2:])  # strip b/
        elif line.startswith("--- a/") or line.startswith("+++ b/"):
            f = line[6:]
            if f != "/dev/null":
                files.add(f)
    return sorted(files)


def _route_to_specialists(files: list[str], board: dict) -> dict[str, list[str]]:
    """Route files to specialists based on domain routing rules."""
    routing_rules = board.get("domain_routing", {}).get("routing_rules", [])
    default_specialists = board.get("domain_routing", {}).get("default_specialists", [])

    specialist_files: dict[str, set[str]] = {}
    for spec in board.get("specialists", []):
        specialist_files[spec["id"]] = set()

    for f in files:
        routed = False
        for rule in routing_rules:
            if fnmatch.fnmatch(f, rule["pattern"]):
                for spec_id in rule["specialists"]:
                    if spec_id in specialist_files:
                        specialist_files[spec_id].add(f)
                routed = True
        if not routed:
            for spec_id in default_specialists:
                if spec_id in specialist_files:
                    specialist_files[spec_id].add(f)

    return {k: sorted(v) for k, v in specialist_files.items() if v}


def _filter_diff_for_files(diff_text: str, files: list[str]) -> str:
    """Extract only the hunks relevant to the given files from a unified diff."""
    if not files or not diff_text:
        return diff_text

    lines = diff_text.split("\n")
    filtered: list[str] = []
    current_file = ""
    include_current = False

    for line in lines:
        if line.startswith("diff --git"):
            parts = line.split(" ")
            if len(parts) >= 4:
                current_file = parts[3][2:]
                include_current = current_file in files
        elif line.startswith("--- a/") or line.startswith("+++ b/"):
            f = line[6:]
            if f != "/dev/null":
                current_file = f
                include_current = current_file in files

        if include_current:
            filtered.append(line)
        elif line.startswith("diff --git"):
            filtered.append(line)

    return "\n".join(filtered)


def _call_specialist(spec: dict, model: str, diff_text: str,
                     max_tokens: int) -> tuple[str, str, str]:
    """Call a single specialist. Returns (specialist_id, model_used, response_text)."""
    system = textwrap.dedent(f"""\
        You are {spec['name']}, {spec['title']} on the House code review board.

        {spec['review_prompt']}

        IMPORTANT: Structure your response as:

        ## Findings
        For each finding:
        - **Severity:** P1/P2/P3/P4
        - **File:** path:line
        - **Issue:** what's wrong
        - **Fix:** how to fix it
        - **Impact:** what happens if we don't fix this

        ## Summary
        - Total findings: N
        - P1 (blocking): N
        - P2 (high): N
        - P3 (medium): N
        - P4 (low): N
        - **Verdict:** PASS or FAIL

        Be specific. Cite exact file paths and line numbers. No hand-waving.
        If the code is clean, say so and PASS. Do not invent problems.""")

    response = call_llm(model, system, diff_text, max_tokens=max_tokens, temperature=0.4)
    return spec["id"], model, response


def _call_cuddy(cuddy_spec: dict, model: str, diff_text: str,
                 max_tokens: int, spec_content: str = "") -> tuple[str, str, str]:
    """Run Cuddy's pre-review differential diagnosis.
    Returns (specialist_id, model_used, response_text).
    """
    system = textwrap.dedent(f"""\
        You are {cuddy_spec['name']}, {cuddy_spec['title']}. You are House's boss.

        {cuddy_spec['review_prompt']}""")

    # If specs are available, add them as ground truth
    if spec_content:
        system += textwrap.dedent(f"""\

            CRITICAL — SPECIFICATIONS PROVIDED:
            The following specifications/requirements were detected in the repository.
            Use them as GROUND TRUTH for your differential diagnosis.
            Check whether the code change satisfies every requirement in the spec.
            If the spec says X and the code does Y without justification → P1.
            If the code changes something the spec doesn't mention → rule out whether it's necessary.

            {spec_content}

            END SPECIFICATIONS""")

    system += textwrap.dedent("""

        IMPORTANT: Structure your response as:

        ## Differential Diagnosis
        For each simpler alternative you considered:
        - **Alternative:** what's the simpler approach?
        - **Ruled out?:** YES (with evidence) / NO (developer didn't address this)
        - **If not ruled out:** specific file:line where the current approach lives, and why the alternative is better

        ## Spec Compliance (if specs provided)
        - **Requirement:** what the spec requires
        - **Satisfied?:** YES / NO / PARTIAL — with evidence from the diff
        - **If not satisfied:** what's missing and where

        ## Summary
        - Total alternatives considered: N
        - Ruled out (justified): N
        - NOT ruled out (must address): N
        - **Verdict:** PASS (all alternatives ruled out, spec satisfied) or FAIL (simpler approach exists, not justified, or spec not met)

        Be specific. If you propose a simpler alternative, describe it concretely.
        Cite exact file paths and line numbers for the code under scrutiny.
        This is a differential diagnosis — rule out everything simpler FIRST.""")

    response = call_llm(model, system, diff_text, max_tokens=max_tokens, temperature=0.4)
    return cuddy_spec["id"], model, response


def _call_house_synthesis(house_config: dict, specialist_findings: list[dict],
                           cuddy_finding: dict | None,
                           scan_result,  # ScanResult from scanner.py
                           problem_alerts: str,  # Cross-review problem detection
                           suppression_suggestions: str,  # Dismissal learning
                           model: str, change_title: str,
                           max_tokens: int) -> str:
    """House synthesizes all specialist findings into a final verdict.

    scan_result: Deterministic pre-scan findings (runs BEFORE Cuddy). Zero-cost, high-confidence.
    cuddy_finding: Cuddy's pre-review differential diagnosis (runs second).
    """
    # Scan findings FIRST — deterministic, zero-hallucination, high-signal
    findings_text = ""
    if scan_result and scan_result.total > 0:
        findings_text += (
            f"## DETERMINISTIC PRE-SCAN — Pattern-Based Findings\n"
            f"These were caught by pattern matching BEFORE any AI review. "
            f"They are high-confidence, zero-hallucination findings.\n\n"
            f"Findings: {scan_result.total} total "
            f"(P1={scan_result.p1_count}, P2={scan_result.p2_count}, "
            f"P3={scan_result.p3_count}, P4={scan_result.p4_count})\n"
        )
        for f in scan_result.findings:
            findings_text += (f"- [{f.severity}] **{f.rule}**: {f.file}:{f.line}"
                              f" — {f.message}\n  Fix: {f.fix}\n")
        findings_text += "\n---\n\n"

    # Cuddy's findings SECOND — if the approach is wrong, code quality is irrelevant
    if cuddy_finding:
        findings_text += (
            f"## CUDDY — DIFFERENTIAL DIAGNOSIS (Pre-Review)\n"
            f"Cuddy reviewed this code FIRST. Her job was to rule out every simpler alternative "
            f"before the specialists even looked at it. If she found un-ruled-out alternatives, "
            f"the approach itself is in question and code-quality findings are secondary.\n\n"
            f"### Cuddy's Findings ({cuddy_finding['model']})\n"
            f"{cuddy_finding['response'][:3000]}\n"
            f"---\n"
            f"END CUDDY DIFFERENTIAL DIAGNOSIS\n"
            f"---\n\n"
        )

    for sf in specialist_findings:
        findings_text += f"\n### {sf['specialist_name']} ({sf['model']})\n{sf['response'][:3000]}\n"
        findings_text += "\n---\n"

    system = textwrap.dedent(f"""\
        You are {house_config['name']}, {house_config['role']}. You lead a review board of insufferable specialists. Cuddy, your boss, has already performed a differential diagnosis. Synthesize ALL findings — Cuddy's FIRST — into a final verdict.

        {house_config['review_prompt']}

        CRITICAL: Cuddy runs BEFORE you. She is your boss. Her differential diagnosis checks whether simpler alternatives were ruled out. If she found un-ruled-out simpler approaches, those are BLOCKING regardless of what the specialists say. The code could be flawless and still be the wrong approach.

        When weighing findings:
        - Cuddy's findings trump everything. Wrong approach = automatic rejection, even if the code is perfect.
        - If Cuddy says PASS (all alternatives ruled out), then the specialists' code-quality findings determine the verdict normally.
        - A simpler alternative that wasn't ruled out IS a P2. A simpler alternative that is objectively better IS a P1.

        If Cuddy's findings are present, address them FIRST in your synthesis. The specialists' findings come SECOND.

        IMPORTANT: Structure your response as:

        ## House's Final Verdict: APPROVED or REJECTED

        ## Cuddy's Differential — Ruling
        (Address Cuddy's findings here. Did she find un-ruled-out alternatives? Are they blocking?)
        - Cuddy: PASS (all alternatives ruled out) or FAIL (simpler approach exists, not justified)

        ## Findings Summary
        """ + ("- Cuddy: N simpler alternatives found (P1: N, P2: N) -- PASS/FAIL\n" if cuddy_finding else "") + """\
        - Foreman: N findings (P1: N, P2: N, P3: N, P4: N) -- PASS/FAIL
        - Cameron: N findings (P1: N, P2: N, P3: N, P4: N) -- PASS/FAIL
        - Chase: N findings (P1: N, P2: N, P3: N, P4: N) -- PASS/FAIL
        - Taub: N findings (P1: N, P2: N, P3: N, P4: N) -- PASS/FAIL
        - Thirteen: N findings (P1: N, P2: N, P3: N, P4: N) -- PASS/FAIL

        ## Blocking Issues (P1/P2)
        List every P1 and P2 finding here with exact file:line, issue, and fix.
        Cuddy's un-ruled-out alternatives go FIRST if any exist.

        ## Recommendations (P3/P4)
        List P3/P4 items -- these should be fixed but don't block commit.

        ## Conflicts Between Reviewers
        Did any specialists disagree? Resolve the conflict.
        If Cuddy says PASS but a specialist found approach-level issues, reconcile.

        ## ITIL Assessment
        - Risk score: (1-5)
        - Rollback plan: (describe)
        - Deploy window: (immediate / scheduled / maintenance window)

        ## House's Signature
        If APPROVED: "I, House, authorize this change. Do not make me regret it."
        If REJECTED: "REJECTED. Fix the above and come back. I'll be waiting."

        Be brutal. Be specific. No sugar-coating. This is your reputation.""")

    # Append cross-review intelligence
    if problem_alerts:
        findings_text += f"\n---\n\n{problem_alerts}\n\n---\n\n"
    if suppression_suggestions:
        findings_text += f"\n---\n\n{suppression_suggestions}\n\n---\n\n"

    user = f"Change: {change_title}\n\nReview findings:\n{findings_text}"
    return call_llm(model, system, user, max_tokens=max_tokens, temperature=0.5)


def _calculate_risk_score(files: list[str], diff_text: str) -> float:
    """Auto-calculate risk score based on files changed and diff size."""
    lines_changed = len([l for l in diff_text.split("\n") if l.startswith("+") or l.startswith("-")])
    n_files = len(files)

    lines_score = 1 if lines_changed < 50 else (3 if lines_changed < 200 else 5)
    files_score = 1 if n_files <= 2 else (3 if n_files <= 5 else 5)

    high_risk_patterns = [
        "**/auth*", "**/login*", "**/password*", "**/token*", "**/session*",
        "**/billing*", "**/payment*", "**/checkout*", "**/trading*",
        "**/secrets*", "**/credentials*", "**/api_key*",
        "**/migration*", "**/*.sql",
    ]
    domain_risk = 1
    for f in files:
        for pattern in high_risk_patterns:
            if fnmatch.fnmatch(f, pattern):
                domain_risk = max(domain_risk, 5)
                break
        if "auth" in f.lower() or "token" in f.lower() or "security" in f.lower():
            domain_risk = max(domain_risk, 5)

    score = (lines_score * 0.20) + (files_score * 0.15) + (domain_risk * 0.65)
    return round(score, 1)


def _recommend_tier(risk_score: float) -> str:
    """Recommend review tier based on risk score."""
    if risk_score < 2.0:
        return "fast"
    elif risk_score < 3.6:
        return "standard"
    else:
        return "adversarial"


def _build_output_paths(title: str) -> tuple[Path, Path]:
    """Build output file paths for markdown and JSON reports."""
    reviews_dir = get_reviews_dir()
    reviews_dir.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    slug = title.lower().replace(" ", "-").replace("/", "-")
    slug = re.sub(r'[<>:"|?*\\]', '', slug)
    slug = re.sub(r'-+', '-', slug)
    slug = slug.strip("-.")[:60]
    if not slug:
        slug = "untitled-review"

    md_path = reviews_dir / f"house-{date_str}-{slug}.md"
    json_path = reviews_dir / f"house-{date_str}-{slug}.json"

    counter = 1
    while md_path.exists():
        md_path = reviews_dir / f"house-{date_str}-{slug}-r{counter}.md"
        json_path = reviews_dir / f"house-{date_str}-{slug}-r{counter}.json"
        counter += 1

    return md_path, json_path


def _archive_old_rounds(current_md: Path, current_json: Path,
                        title: str, date_str: str) -> tuple[int, int]:
    """Archive previous rounds of the same review instead of deleting them.

    Prior rounds are moved to docs/reviews/archive/ so the full review
    history is preserved for debugging (e.g. Cuddy contradiction loops).

    Returns (archived_count, total_rounds_including_current).
    """
    reviews_dir = get_reviews_dir()
    archive_dir = get_archive_dir()
    slug = title.lower().replace(" ", "-").replace("/", "-")
    slug = re.sub(r'[<>:"|?*\\]', '', slug)
    slug = re.sub(r'-+', '-', slug)
    slug = slug.strip("-.")[:60]
    if not slug:
        return 0, 1

    prefix = f"house-{date_str}-{slug}"
    prior_rounds = (
        list(reviews_dir.glob(f"{prefix}.md")) +
        list(reviews_dir.glob(f"{prefix}.json")) +
        list(reviews_dir.glob(f"{prefix}-r*.md")) +
        list(reviews_dir.glob(f"{prefix}-r*.json"))
    )
    archived = 0
    round_numbers = set()
    for f in sorted(set(prior_rounds)):
        if f == current_md or f == current_json:
            continue
        try:
            dest = archive_dir / f.name
            f.rename(dest)
            archived += 1
            # Extract round number from filename (-r1, -r2, etc.)
            m = re.search(r'-r(\d+)\.(md|json)$', f.name)
            round_numbers.add(int(m.group(1)) if m else 0)
        except OSError:
            pass

    total_rounds = len(round_numbers) + 1  # prior rounds + current
    return archived, total_rounds


# Keep old name as alias for the fast-track path that still uses it
def _cleanup_old_rounds(current_md: Path, current_json: Path,
                        title: str, date_str: str) -> int:
    archived, _ = _archive_old_rounds(current_md, current_json, title, date_str)
    return archived


def run_cleanup(days: int = 30, dry_run: bool = False) -> dict:
    """Prune review artifacts older than N days.

    Deletes both .md and .json review files. The audit trail
    remains in git history for committed reviews.

    Returns a dict with cleanup statistics.
    """
    reviews_dir = get_reviews_dir()
    if not reviews_dir.exists():
        return {"deleted": 0, "freed_bytes": 0, "dry_run": dry_run}

    cutoff = datetime.now(timezone.utc).timestamp() - (days * 86400)
    deleted = 0
    freed = 0

    for pattern in ("house-*.md", "house-*.json"):
        for f in reviews_dir.glob(pattern):
            if f.stat().st_mtime < cutoff:
                size = f.stat().st_size
                if not dry_run:
                    try:
                        f.unlink()
                    except OSError:
                        continue
                deleted += 1
                freed += size

    if not dry_run and deleted > 0:
        print(f"\n  [CLEANUP] Pruned {deleted} review artifact(s) older than {days} days "
              f"({freed / 1024:.0f} KB freed)")
        # Also prune empty stats entries older than cutoff
        _prune_stats(cutoff)

    return {"deleted": deleted, "freed_bytes": freed, "dry_run": dry_run}


def _prune_stats(cutoff_timestamp: float) -> None:
    """Remove stats entries older than cutoff."""
    stats_path = get_stats_path()
    if not stats_path.exists():
        return
    try:
        stats = json.loads(stats_path.read_text(encoding="utf-8"))
        reviews = stats.get("reviews", [])
        kept = []
        pruned = 0
        for r in reviews:
            ts = r.get("timestamp", "")
            if ts:
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if dt.timestamp() < cutoff_timestamp:
                        pruned += 1
                        continue
                except (ValueError, OSError):
                    pass
            kept.append(r)
        if pruned > 0:
            stats["reviews"] = kept
            stats_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    except Exception:
        pass


def _write_commit_log_entry(review_data: dict, verdict: str, bypassed: bool,
                            commit_sha: str = "", bypass_reason: str = "") -> None:
    """Append one line to house-commits.jsonl.

    Called on APPROVED from the review pipeline. The commit SHA is unknown at
    review time (commit hasn't happened yet), so it's left blank and filled in
    by the post-commit hook via --stamp-commit.
    """
    log_path = get_commit_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "commit": commit_sha,        # filled by post-commit hook
        "rfc_id": review_data.get("rfc_id", ""),
        "verdict": verdict,
        "rounds": review_data.get("total_rounds", 1),
        "tier": review_data.get("review_tier", ""),
        "files": review_data.get("affected_files", []),
        "timestamp": review_data.get("timestamp", ""),
        "bypassed": bypassed,
        "bypass_reason": bypass_reason or None,
    }
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _stamp_commit_sha(rfc_id: str, sha: str) -> bool:
    """Back-fill the commit SHA into the most recent house-commits.jsonl entry for an RFC.

    Called by the post-commit hook once git has assigned a SHA.
    Returns True if the entry was found and updated.
    """
    log_path = get_commit_log_path()
    if not log_path.exists():
        return False
    lines = log_path.read_text(encoding="utf-8").splitlines()
    updated = False
    new_lines = []
    for line in reversed(lines):
        if not updated:
            try:
                entry = json.loads(line)
                if entry.get("rfc_id") == rfc_id and not entry.get("commit"):
                    entry["commit"] = sha
                    line = json.dumps(entry)
                    updated = True
            except Exception:
                pass
        new_lines.append(line)
    if updated:
        log_path.write_text("\n".join(reversed(new_lines)) + "\n", encoding="utf-8")
    return updated


def _write_bypass_log_entry(commit_sha: str, bypass_reason: str = "") -> None:
    """Write a bypass entry to house-commits.jsonl when --no-verify is used."""
    log_path = get_commit_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "commit": commit_sha,
        "rfc_id": None,
        "verdict": "BYPASSED",
        "rounds": 0,
        "tier": None,
        "files": [],
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bypassed": True,
        "bypass_reason": bypass_reason or None,
    }
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _update_stats(review_data: dict) -> None:
    """Update review statistics."""
    stats_path = get_stats_path()
    stats_path.parent.mkdir(parents=True, exist_ok=True)

    stats = {}
    if stats_path.exists():
        try:
            stats = _load_json(stats_path)
        except Exception:
            stats = {}
    stats.setdefault("reviews", []).append({
        "timestamp": review_data.get("timestamp", ""),
        "rfc_id": review_data.get("rfc_id", ""),
        "verdict": review_data.get("verdict", ""),
        "tier": review_data.get("review_tier", ""),
        "risk_score": review_data.get("risk_score", 0),
        "files_changed": len(review_data.get("affected_files", [])),
    })
    stats["reviews"] = stats["reviews"][-100:]
    stats_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")


def _print_dry_run_prompts(diff_text: str, files: list[str], specialists: list[dict],
                           routing: dict[str, list[str]],
                           board: dict, house_config: dict) -> None:
    """Print specialist prompts for external execution (Thor/OpenCode)."""
    print("=" * 80)
    print("HOUSE GATEKEEPER -- DRY RUN (Prompts for External Execution)")
    print("=" * 80)

    # Cuddy goes FIRST
    cuddy_spec = next((s for s in board.get("specialists", []) if s.get("pre_review") and s["id"] == "cuddy"), None)
    if cuddy_spec and diff_text.strip():
        print(f"\n{'-' * 80}")
        print(f"PRE-REVIEW -- DIFFERENTIAL DIAGNOSIS: {cuddy_spec['name']} -- {cuddy_spec['title']}")
        print(f"FILES: ALL ({len(files)} files) -- Cuddy reviews everything to rule out simpler alternatives")
        print(f"{'-' * 80}")
        print(f"\nSYSTEM PROMPT:\n{cuddy_spec['review_prompt'][:500]}...")
        safe_diff = _safe(diff_text[:2000])
        print(f"\nUSER INPUT (full diff):\n{safe_diff}")
        if len(diff_text) > 2000:
            print(f"\n... ({len(diff_text) - 2000} more chars)")
        print(f"\n{'-' * 80}")
        print(f"Send Cuddy's differential diagnosis to House along with specialist findings.")
        print(f"Cuddy's findings trump all. Wrong approach = automatic rejection.\n")

    for spec in board["specialists"]:
        if spec.get("pre_review"):
            continue  # Cuddy already shown above
        spec_files = routing.get(spec["id"], [])
        if not spec_files:
            continue
        spec_diff = _filter_diff_for_files(diff_text, spec_files)
        if not spec_diff.strip():
            continue

        print(f"\n{'-' * 80}")
        print(f"SPECIALIST: {spec['name']} -- {spec['title']}")
        print(f"FILES: {', '.join(spec_files[:10])}")
        if len(spec_files) > 10:
            print(f"  ... and {len(spec_files) - 10} more files")
        print(f"{'-' * 80}")
        print(f"\nSYSTEM PROMPT:\n{spec['review_prompt'][:500]}...")
        safe_diff = _safe(spec_diff[:2000])
        print(f"\nUSER INPUT (diff):\n{safe_diff}")
        if len(spec_diff) > 2000:
            print(f"\n... ({len(spec_diff) - 2000} more chars)")

    print(f"\n{'-' * 80}")
    print(f"HOUSE SYNTHESIS -- {house_config['name']}")
    print(f"{'-' * 80}")
    print(f"\nSend all specialist responses to House for final verdict.")
    safe_prompt = _safe(house_config['review_prompt'][:300])
    print(f"House prompt: {safe_prompt}...")


# ── Main Pipeline ─────────────────────────────────────────────────────────────


def run_review(
    diff_text: str = "",
    files: Optional[list[str]] = None,
    tier: str = "standard",
    title: str = "",
    change_type: str = "normal",
    staged: bool = False,
    dry_run: bool = False,
    max_tokens: int = 4096,
    ci_mode: Optional[str] = None,
    spec_mode: bool = False,
    spec_file: Optional[str] = None,
) -> dict:
    """Run the full House gatekeeper review pipeline.

    Returns a dict with the complete review data (verdict, findings, RFC record).
    Exit code convention: 0 = APPROVED, 1 = REJECTED (set by caller).
    """
    global _dynamic_fellows
    _dynamic_fellows = _load_dynamic_fellows()

    # Ensure config directory exists
    ensure_config_dir()

    # ── Cuddy pre-flight: no stale subagents ─────────────────────────────
    _check_no_running_subagents()

    board = _load_json(get_chart_path())
    house_config = board["gatekeeper"]
    static_specialists = board.get("specialists", [])

    # ── Detect domain gaps + auto-hire dynamic fellows ─────────────────
    if files or diff_text:
        if not files:
            files = _get_changed_files(diff_text)
        if files:
            gaps = _detect_uncovered_domains(files, static_specialists)
            for gap in gaps:
                auto_hire_threshold = board.get("dynamic_fellows", {}).get("auto_hire_threshold", 3)
                if len(gap.get("trigger_files", [])) >= auto_hire_threshold:
                    fellow = _hire_fellow(gap, tier, board)
                    print(f"  [HIRED] {fellow['name']} for {gap['domain']} "
                          f"(triggered by {', '.join(gap['trigger_files'][:2])})")
                else:
                    print(f"  [GAP] {gap['domain']} detected but only "
                          f"{len(gap.get('trigger_files', []))} files — threshold {auto_hire_threshold}")

    specialists = _get_all_specialists(board)

    # ── Get diff ──────────────────────────────────────────────────────
    if not diff_text:
        diff_text = _get_git_diff(staged=staged)
    if not diff_text:
        print("ERROR: No diff found. Stage changes or use --diff.", file=sys.stderr)
        sys.exit(1)

    if not files:
        files = _get_changed_files(diff_text)
    if not files:
        print("ERROR: No changed files detected in diff.", file=sys.stderr)
        sys.exit(1)

    if not title:
        title = f"Review of {len(files)} file(s): {', '.join(files[:3])}"
        if len(files) > 3:
            title += f" +{len(files) - 3} more"

    # ── Triage ────────────────────────────────────────────────────────
    routing = _route_to_specialists(files, board)
    risk_score = _calculate_risk_score(files, diff_text)
    recommended_tier = _recommend_tier(risk_score)

    print(f"\n{'=' * 70}")
    print(f"  HOUSE GATEKEEPER -- Code Review")
    print(f"{'=' * 70}")
    print(f"  Change: {title}")
    print(f"  Files:  {len(files)}")
    print(f"  Risk:   {risk_score}/5.0 -> recommended tier: {recommended_tier}")
    print(f"  Tier:   {tier}")
    print(f"  Type:   {change_type}")
    if recommended_tier != tier:
        print(f"  [!] Tiers don't match -- Orchestrator chose {tier}, House recommends {recommended_tier}")
    print(f"{'=' * 70}\n")

    for spec_id, spec_files in routing.items():
        spec_name = next((s["name"] for s in specialists if s["id"] == spec_id), spec_id)
        print(f"  {spec_name}: {len(spec_files)} file(s) -- {', '.join(spec_files[:3])}{'...' if len(spec_files) > 3 else ''}")

    # Initialize tracking vars (used by scan, Cuddy, specialists)
    all_pass = True
    blocking_findings: list[str] = []

    # Show auto-detected configuration
    if not dry_run:
        available = detect_available_providers()
        auto_model = auto_detect_model()
        if available:
            provider_names = [PROVIDERS[p]["name"] for p in available]
            model_info = f" ({auto_model})" if auto_model else ""
            print(f"  [CONFIG] Auto-detected:{model_info} via {', '.join(provider_names)}")
            missing = [p for p in PROVIDERS if p not in available]
            if missing:
                optional_names = [f"{PROVIDERS[p]['env_key']}" for p in missing]
                print(f"  [CONFIG] Optional: set {' or '.join(optional_names)} for cheaper/faster routing")
        else:
            print(f"\n{'=' * 70}")
            print(f"  NO API KEYS DETECTED")
            print(f"  Set at least one of:")
            for p_key, p_info in PROVIDERS.items():
                print(f"    export {p_info['env_key']}=\"your-key\"   # {p_info['name']} ({p_info['cost_note']})")
            print(f"")
            print(f"  Claude Code users: your ANTHROPIC_API_KEY is already set in your env.")
            print(f"  If running as a Claude Code skill, subagents inherit your model automatically.")
            print(f"")
            print(f"  For testing without API keys: everybody-lies --dry-run")
            print(f"{'=' * 70}\n")

    # ── Deterministic Pre-Scan ───────────────────────────────────────
    # Zero-cost pattern matching BEFORE any AI review. Catches what AI
    # reviewers consistently miss (per arXiv 2603.25773, March 2026).
    # Load suppression rules (user-defined + auto-learned)
    suppression_rules = load_suppression_rules()

    scan_result = scan_diff(diff_text, files)
    original_scan_total = scan_result.total

    # Apply suppression rules to scan findings (learned from dismissals)
    if suppression_rules:
        scan_result.findings = [
            f for f in scan_result.findings
            if not is_suppressed(f.rule, f.file, suppression_rules)
        ]
    suppressed_scan_count = original_scan_total - scan_result.total

    trivial, trivial_reason = is_trivial_diff(diff_text, files)

    print(f"\n  [SCAN] Deterministic pre-scan: {scan_result.files_scanned} files, "
          f"{scan_result.lines_scanned} lines ({scan_result.duration_ms}ms)")
    if scan_result.total > 0:
        print(f"         {scan_result.total} findings: "
              f"P1={scan_result.p1_count} P2={scan_result.p2_count} "
              f"P3={scan_result.p3_count} P4={scan_result.p4_count}")
        if suppressed_scan_count > 0:
            print(f"         ({suppressed_scan_count} suppressed by rules)")
        for f in scan_result.findings[:5]:
            print(f"         [{f.severity}] {f.rule}: {f.file}:{f.line}")
        if scan_result.total > 5:
            print(f"         ... and {scan_result.total - 5} more")
    else:
        if suppressed_scan_count > 0:
            print(f"         Clean — {suppressed_scan_count} findings suppressed by rules")
        else:
            print(f"         Clean — no patterns matched")

    if trivial:
        print(f"  [TRIVIAL] This diff looks trivial: {trivial_reason}")
        if not scan_result.has_blockers:
            print(f"  [FAST-TRACK] Trivial diff, no scan blockers — APPROVED without AI review.")
            # Build a minimal approval record
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            md_path, json_path = _build_output_paths(title)
            review_data = {
                "rfc_id": md_path.stem.replace("house-", "RFC-"),
                "timestamp": timestamp,
                "change_type": change_type,
                "review_tier": tier,
                "risk_score": risk_score,
                "change_title": title,
                "affected_files": files,
                "verdict": "APPROVED",
                "fast_track": True,
                "fast_track_reason": trivial_reason,
                "deterministic_scan": scan_result.to_dict(),
                "signed_by": "House (Gatekeeper) — Fast-Track (no AI review needed)",
            }
            md_path.write_text(_build_fast_track_report(review_data, scan_result), encoding="utf-8")
            json_path.write_text(json.dumps(review_data, indent=2), encoding="utf-8")
            _cleanup_old_rounds(md_path, json_path, title,
                               datetime.now(timezone.utc).strftime("%Y-%m-%d"))
            print(f"  [REPORT] {md_path}")
            print(f"\n{'=' * 70}")
            print(f"  [APPROVED] VERDICT: APPROVED (Fast-Track)")
            print(f"  Reason: {trivial_reason}. Deterministic scan clean.")
            print(f"  Signed: House (Gatekeeper)")
            print(f"{'=' * 70}\n")
            return review_data
        else:
            print(f"  [SCAN] Trivial diff but has P1 scan findings — proceeding to AI review.")
            blocking_findings.append(f"Scanner: {scan_result.p1_count} P1 finding(s) in deterministic scan")

    # ── Dry run ───────────────────────────────────────────────────────
    if dry_run:
        _print_dry_run_prompts(diff_text, files, specialists, routing, board, house_config)
        return {"status": "dry_run", "verdict": "dry_run", "routing": routing}

    # ── Spec Detection ────────────────────────────────────────────────
    # Auto-detect spec files for Cuddy's differential diagnosis.
    # Per arXiv 2603.25773: specs catch what all AI reviewers miss.
    spec_content = ""
    if spec_mode and not spec_file:
        # Auto-detect: look for SPEC.md, *.feature, spec files in repo
        spec_candidates = list(Path.cwd().rglob("SPEC.md")) + \
                         list(Path.cwd().rglob("*SPEC*")) + \
                         list(Path.cwd().rglob("*.feature"))
        for candidate in spec_candidates[:3]:  # max 3 files
            try:
                content = candidate.read_text(encoding="utf-8")
                spec_content += f"\n### {candidate.name}\n{content[:3000]}\n"
            except Exception:
                pass
        if spec_content:
            print(f"  [SPEC] Detected spec files — Cuddy will use them as ground truth")
    elif spec_file:
        try:
            spec_content = Path(spec_file).read_text(encoding="utf-8")
            print(f"  [SPEC] Loaded {spec_file} — Cuddy will use it as ground truth")
        except Exception as exc:
            print(f"  [SPEC] Failed to load {spec_file}: {exc}")

    # ── Cuddy — Differential Diagnosis (PRE-REVIEW) ──────────────────
    # Cuddy runs FIRST, before any specialist. She reviews the FULL diff
    # (not domain-filtered) because her job is approach validation, not bug hunting.
    cuddy_spec = next((s for s in specialists if s.get("pre_review") and s["id"] == "cuddy"), None)
    cuddy_finding: dict | None = None

    if cuddy_spec and diff_text.strip():
        cuddy_model = resolve_specialist_model(cuddy_spec, tier, board)
        print(f"\n  [CUDDY — DIFFERENTIAL DIAGNOSIS] {cuddy_spec['name']} ({cuddy_spec['title']})")
        print(f"  Ruling out simpler alternatives before the specialists touch this...")
        print(f"  Model: {cuddy_model}")

        try:
            cuddy_id, cuddy_model_used, cuddy_response = _call_cuddy(
                cuddy_spec, cuddy_model, diff_text, max_tokens, spec_content,
            )
            print(f"    -> {len(cuddy_response)} chars received")
            cuddy_finding = {
                "specialist_id": cuddy_id,
                "specialist_name": cuddy_spec["name"],
                "model": cuddy_model_used,
                "response": cuddy_response,
                "files_reviewed": files,
                "pre_review": True,
            }
            # Check Cuddy's findings for blockers
            if "P1" in cuddy_response or "P1:" in cuddy_response:
                blocking_findings.append(f"Cuddy: P1 — simpler alternative exists, approach is wrong")
                all_pass = False
            elif "FAIL" in cuddy_response[:500] or "FAIL" in cuddy_response.upper()[:200]:
                all_pass = False
        except Exception as exc:
            print(f"    -> Cuddy unavailable: {exc}")
            cuddy_finding = {
                "specialist_id": cuddy_spec["id"],
                "specialist_name": cuddy_spec["name"],
                "model": "FAILED",
                "response": f"**ERROR:** Cuddy unavailable for differential diagnosis. {exc}",
                "verdict": "UNAVAILABLE",
                "pre_review": True,
            }

    # ── Specialist review ─────────────────────────────────────────────
    # Patterns that match actual P1 severity markers in specialist responses.
    # Excludes the summary line "P1 (blocking): 0" that appears in every response.
    _p1_patterns = [
        r"\*\*Severity:\*\*\s*P1",   # **Severity:** P1
        r"^-\s+\*\*P1\b",            # - **P1 ...
        r"Severity.*P1.*blocking",    # Severity: P1 (blocking)
        r"P1\s*[\(\-–]\s*block", # P1 (blocking) / P1 - blocking / P1 – blocking
    ]

    specialist_results: list[dict] = []

    # Exclude Cuddy from specialist loop — she already ran as pre-review
    active_specialists = [
        s for s in specialists
        if routing.get(s["id"]) and not s.get("pre_review")
    ]
    if not active_specialists:
        print("WARNING: No specialists matched. Defaulting to Thirteen only.")
        active_specialists = [s for s in specialists if s["id"] == "thirteen"]
        for s in active_specialists:
            routing[s["id"]] = files

    for spec in active_specialists:
        spec_files = routing.get(spec["id"], files)
        spec_diff = _filter_diff_for_files(diff_text, spec_files)

        if not spec_diff.strip():
            print(f"\n  [{spec['id'].upper()}] {spec['name']}: No relevant diff -- SKIPPED")
            specialist_results.append({
                "specialist_id": spec["id"],
                "specialist_name": spec["name"],
                "model": "n/a",
                "response": "No relevant code changes in this specialist's domain.",
                "verdict": "PASS",
            })
            continue

        model = resolve_specialist_model(spec, tier, board)
        print(f"\n  [{spec['id'].upper()}] {spec['name']} ({spec['title']}) -- reviewing {len(spec_files)} file(s) with {model}...")

        try:
            spec_id, model_used, response = _call_specialist(spec, model, spec_diff, max_tokens)
            print(f"    -> {len(response)} chars received")

            specialist_results.append({
                "specialist_id": spec_id,
                "specialist_name": spec["name"],
                "model": model_used,
                "response": response,
                "files_reviewed": spec_files,
            })

            # Check for actual P1 findings using patterns defined above the loop
            _has_p1 = any(re.search(p, response, re.MULTILINE | re.IGNORECASE)
                          for p in _p1_patterns)
            if _has_p1:
                blocking_findings.append(f"{spec['name']}: P1 found")
                all_pass = False
            elif "FAIL" in response[:500] or "VERDICT: FAIL" in response.upper()[:200]:
                all_pass = False

            if spec.get("dynamic"):
                fid = spec["id"]
                if fid in _dynamic_fellows:
                    _dynamic_fellows[fid]["review_count"] = _dynamic_fellows[fid].get("review_count", 0) + 1
                    findings_count = response.count("**Severity:**")
                    if findings_count > 0:
                        _dynamic_fellows[fid]["unique_findings"] = _dynamic_fellows[fid].get("unique_findings", 0) + findings_count

        except Exception as exc:
            print(f"    -> FAILED: {exc}")
            fallback = "deepseek-v4-flash"
            if fallback and fallback != model:
                print(f"    -> Trying fallback {fallback}...")
                try:
                    spec_id, model_used, response = _call_specialist(spec, fallback, spec_diff, max_tokens)
                    print(f"    -> {len(response)} chars received (via {fallback})")
                    specialist_results.append({
                        "specialist_id": spec_id,
                        "specialist_name": spec["name"],
                        "model": model_used,
                        "response": response,
                        "files_reviewed": spec_files,
                    })
                    # Apply same P1/FAIL check as primary path — do NOT skip with continue
                    _fb_p1 = any(re.search(p, response, re.MULTILINE | re.IGNORECASE)
                                 for p in _p1_patterns)
                    if _fb_p1:
                        blocking_findings.append(f"{spec['name']}: P1 found")
                        all_pass = False
                    elif "FAIL" in response[:500] or "VERDICT: FAIL" in response.upper()[:200]:
                        all_pass = False
                    continue
                except Exception as exc2:
                    print(f"    -> Fallback also failed: {exc2}")

            specialist_results.append({
                "specialist_id": spec["id"],
                "specialist_name": spec["name"],
                "model": "FAILED",
                "response": f"**ERROR:** Specialist unavailable. {exc}",
                "verdict": "UNAVAILABLE",
            })

    # ── Adversarial cross-check ───────────────────────────────────────
    if tier == "adversarial":
        secondary_model = "deepseek/deepseek-v4-flash"
        for spec in active_specialists:
            spec_files = routing.get(spec["id"], files)
            spec_diff = _filter_diff_for_files(diff_text, spec_files)
            if not spec_diff.strip():
                continue
            print(f"\n  [CROSS-CHECK] {spec['name']} -- adversarial cross-check with {secondary_model}...")
            try:
                _, model_used, response2 = _call_specialist(spec, secondary_model, spec_diff, max_tokens)
                print(f"    -> {len(response2)} chars received")
                specialist_results.append({
                    "specialist_id": spec["id"],
                    "specialist_name": f"{spec['name']} (cross-check)",
                    "model": model_used,
                    "response": response2,
                    "files_reviewed": spec_files,
                })
                if "P1" in response2:
                    all_pass = False
            except Exception as exc:
                print(f"    -> Cross-check failed: {exc}")

    # ── Cross-Review Problem Detection ────────────────────────────────
    # ITIL Problem Management: detect patterns across review history
    recurring_problems = detect_recurring_problems(min_occurrences=3, lookback_reviews=20)
    problem_alerts = format_problem_alerts(recurring_problems)
    suppression_suggestions = format_suppression_suggestions()

    if recurring_problems:
        print(f"\n  [PROBLEM MGMT] {len(recurring_problems)} recurring issue(s) detected across review history")
        for p in recurring_problems[:3]:
            print(f"         {p['rule']}: {p['review_count']} reviews, affects {len(p['files'])} file(s)")
        auto_create_problem_records(recurring_problems)

    suppression_suggestions_list = [
        r for r in (suppression_suggestions or "").split("\n") if r.startswith("- **")
    ]
    if suppression_suggestions_list:
        print(f"  [SUPPRESS] {len(suppression_suggestions_list)} rule(s) have been dismissed enough times to suppress")
        print(f"            Edit ~/.everybody-lies/suppress.toml to silence them")

    # ── House synthesis ───────────────────────────────────────────────
    house_model_config = board.get("model_config", {}).get("house_model", {})
    tier_to_slot = board.get("model_config", {}).get("tier_to_slot", {})
    slot = tier_to_slot.get(tier, "preferred")
    synthesis_model = house_model_config.get(slot) or resolve_specialist_model({}, tier, board)
    print(f"\n  [HOUSE] Synthesizing findings with {synthesis_model}...")

    try:
        synthesis = _call_house_synthesis(house_config, specialist_results, cuddy_finding, scan_result, problem_alerts, suppression_suggestions, synthesis_model, title, max_tokens)
        print(f"    -> {len(synthesis)} chars received")
    except Exception as exc:
        print(f"    -> House synthesis failed: {exc}")
        synthesis = f"**ERROR:** House synthesis unavailable. {exc}\n\nManual verdict required from Orchestrator."

    # ── Determine verdict ─────────────────────────────────────────────
    valid_responses = [r for r in specialist_results
                       if r.get("model") not in ("n/a", "FAILED", "UNAVAILABLE")]
    if not valid_responses:
        verdict = "REJECTED"
        failures = []
        for r in specialist_results:
            resp = r.get("response", "")
            if "ERROR" in resp or "FAILED" in resp or "unavailable" in resp.lower():
                failures.append(f"- {r['specialist_name']}: {resp[:200]}")
        fail_detail = "\n".join(failures) if failures else "Unknown — all specialists failed to respond."
        provider_names = ', '.join(PROVIDERS[p]['env_key'] for p in PROVIDERS)
        synthesis = (f"**REJECTED:** All {len(specialist_results)} specialists failed. "
                     f"House cannot review this change.\n\n"
                     f"Failures:\n{fail_detail}\n\n"
                     f"Check API keys ({provider_names}), "
                     f"network connectivity, and model availability, then resubmit.")
    elif all_pass and "APPROVED" in synthesis.upper()[:200]:
        verdict = "APPROVED"
    elif "REJECTED" in synthesis.upper()[:200]:
        verdict = "REJECTED"
    elif all_pass:
        verdict = "APPROVED"
    else:
        verdict = "REJECTED"

    # ── Build output ──────────────────────────────────────────────────
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    md_path, json_path = _build_output_paths(title)

    review_data = {
        "rfc_id": md_path.stem.replace("house-", "RFC-"),
        "timestamp": timestamp,
        "change_type": change_type,
        "review_tier": tier,
        "risk_score": risk_score,
        "change_title": title,
        "affected_files": files,
        "deterministic_scan": scan_result.to_dict(),
        "triviality": {"is_trivial": trivial, "reason": trivial_reason},
        "cuddy_differential_diagnosis": {
            "verdict": cuddy_finding.get("verdict", "UNAVAILABLE"),
            "model": cuddy_finding["model"],
            "response_length": len(cuddy_finding["response"]),
        } if cuddy_finding else None,
        "specialist_routing": dict(routing),
        "specialist_results": [
            {
                "specialist": r["specialist_name"],
                "model": r["model"],
                "response_length": len(r["response"]),
            }
            for r in specialist_results
        ],
        "verdict": verdict,
        "signed_by": "House (Gatekeeper)",
    }

    # ── Write reports ─────────────────────────────────────────────────
    md = _build_markdown_report(review_data, cuddy_finding, scan_result, specialist_results, synthesis, house_config, board)
    md_path.write_text(md, encoding="utf-8")
    print(f"\n  [REPORT] {md_path}")

    json_path.write_text(json.dumps(review_data, indent=2), encoding="utf-8")
    print(f"  [RECORD] {json_path}")

    # Archive previous rounds (preserves history for debugging contradiction loops)
    archived, total_rounds = _archive_old_rounds(md_path, json_path, title,
                                                  datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    if archived > 0:
        print(f"  [ARCHIVE] Archived {archived} prior round(s) -> reviews/archive/")
    if total_rounds > 1:
        print(f"  [ROUNDS]  This change took {total_rounds} review round(s)")

    # Stamp round count into review_data for the commit log
    review_data["total_rounds"] = total_rounds

    _update_stats(review_data)

    # ── Diagnostics: record performance event ─────────────────────────
    try:
        from .diagnostics import (
            record_commit_event, parse_findings_from_md,
            specialist_key as _skey, parse_attribution,
        )
        loop_detected = total_rounds >= 3 and verdict == "REJECTED"
        import subprocess as _sp
        _git_log = _sp.run(
            ["git", "log", "-1", "--format=%B"],
            capture_output=True, text=True,
        ).stdout
        submitter_key = "unknown/unknown"
        submitter_display = "Unknown"
        for _line in _git_log.splitlines():
            if _line.strip().lower().startswith("co-authored-by:"):
                _identity = parse_attribution(_line.split(":", 1)[-1].strip())
                submitter_key = _identity.get("key", submitter_key)
                submitter_display = _identity.get("name", submitter_display)
                break
        md_text = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
        _spec_findings = parse_findings_from_md(md_text)
        _spec_models = {
            sr.get("specialist", ""): sr.get("model", "unknown")
            for sr in specialist_results
        }
        record_commit_event(
            rfc_id=review_data.get("rfc_id", "unknown"),
            verdict=verdict,
            rounds=total_rounds,
            submitter_key=submitter_key,
            submitter_display=submitter_display,
            specialist_findings=_spec_findings,
            specialist_models=_spec_models,
            loop_detected=loop_detected,
            bypass_was_reviewer_fault=loop_detected,
        )
    except Exception:
        pass  # diagnostics are non-blocking

    # ── VERDICT ───────────────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    if verdict == "APPROVED":
        print(f"  [APPROVED] VERDICT: APPROVED")
        print(f"  Signed: House (Gatekeeper)")
        rfc_id = review_data.get('rfc_id', 'RFC-unknown')
        print(f"  House-RFC: {rfc_id}")
        print(f"  Include in commit message:")
        print(f"    Reviewed-by: House (Gatekeeper) <noreply@everybody-lies.dev>")
        print(f"    House-RFC: {rfc_id}")
        # Write commit log entry (commit SHA filled in by post-commit hook)
        _write_commit_log_entry(review_data, verdict="APPROVED", bypassed=False)
    else:
        print(f"  [REJECTED] VERDICT: REJECTED")
        if blocking_findings:
            for bf in blocking_findings:
                print(f"  BLOCKER: {bf}")
        has_p1 = any("P1" in bf for bf in blocking_findings)
        if has_p1:
            print(f"  P1 findings — not appealable. Fix them. Not even Wilson can help you.")
        else:
            print(f"  No P1 findings — may appeal to Wilson: everybody-lies --appeal \"justification\" --rfc {review_data.get('rfc_id', 'RFC-unknown')}")
        # ── Loop alert with Diagnostics tiebreak hint ─────────────────
        if total_rounds >= 3:
            print(f"\n  [DIAGNOSTICS] Loop detected ({total_rounds} rounds). Cuddy tiebreak available.")
            try:
                from .diagnostics import load_ledger, get_daily_score, score_to_label, today_str
                ledger = load_ledger()
                if ledger:
                    print(f"  Current daily grades:")
                    for k, v in sorted(ledger.items(), key=lambda x: x[0]):
                        if k.startswith("specialist/"):
                            score = get_daily_score(v)
                            print(f"    {v['display']:<35} {score:.0f}  {score_to_label(score)}")
                    print(f"  Lower-scored specialist loses the disputed finding.")
                    print(f"  Run: python -m everybody_lies.diagnostics  (morning report)")
            except Exception:
                pass
    print(f"{'=' * 70}\n")

    _save_dynamic_fellows()
    return review_data


# ── Appeal Pipeline ──────────────────────────────────────────────────────────


def _find_review_by_rfc(rfc_id: str) -> Path | None:
    """Find a review JSON file by RFC ID."""
    reviews_dir = get_reviews_dir()
    if not reviews_dir.exists():
        return None
    for json_file in sorted(reviews_dir.glob("house-*.json"), reverse=True):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            if data.get("rfc_id") == rfc_id:
                return json_file
        except Exception:
            continue
    return None


def _find_latest_rejected_review() -> Path | None:
    """Find the most recent REJECTED review JSON."""
    reviews_dir = get_reviews_dir()
    if not reviews_dir.exists():
        return None
    for json_file in sorted(reviews_dir.glob("house-*.json"), reverse=True):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            if data.get("verdict") == "REJECTED":
                return json_file
        except Exception:
            continue
    return None


def _get_appeal_model(board: dict) -> str | None:
    """Resolve the model for Wilson (appeal judge).

    MUST be a different PROVIDER than the review board uses.
    DeepSeek is excluded — it's the review board's provider.

    Resolution order:
    1. chart.json appeal_judge.model — if its provider is available and non-deepseek
    2. chart.json appeal_judge.fallback_models — same check
    3. Any available non-deepseek provider from detect_available_providers()
       using its best direct model (anthropic → claude-sonnet-4-6,
       gemini → gemini-2.5-flash, openrouter → google/gemini-2.5-flash)

    Returns None only if NO non-deepseek provider has a key.
    """
    from .providers import MODEL_ROUTING, PROVIDERS, detect_available_providers

    appeal_config = board.get("appeal_judge", {})
    primary = appeal_config.get("model", "gemini-2.5-flash")
    fallbacks = appeal_config.get("fallback_models",
        ["gemini-2.5-flash", "claude-sonnet-4-6", "anthropic/claude-sonnet-4-6",
         "google/gemini-2.5-flash", "openai/gpt-4o"])

    # Step 1+2: try chart-configured models
    for model in [primary] + fallbacks:
        route = MODEL_ROUTING.get(model, ["openrouter"])
        for provider_key in route:
            provider = PROVIDERS.get(provider_key)
            if provider and provider_key != "deepseek" and os.environ.get(provider["env_key"]):
                return model

    # Step 3: fall back to any available non-deepseek provider
    _PROVIDER_BEST_MODEL = {
        "anthropic": "claude-sonnet-4-6",
        "gemini":    "gemini-2.5-flash",
        "openrouter": "google/gemini-2.5-flash",
    }
    for provider_key in detect_available_providers():
        if provider_key != "deepseek" and provider_key in _PROVIDER_BEST_MODEL:
            return _PROVIDER_BEST_MODEL[provider_key]

    # No independent judge available — appeal cannot proceed
    return None


def _has_p1_findings(review_data: dict) -> bool:
    """Check if the review has any P1 (non-appealable) findings."""
    _p1_rx = re.compile(
        r"\*\*Severity:\*\*\s*P1|^-\s+\*\*P1\b|P1\s*[\(\-–]\s*block",
        re.MULTILINE | re.IGNORECASE,
    )

    # Check specialist results — response text is stored in the JSON
    for sr in review_data.get("specialist_results", []):
        response = sr.get("response", "") or ""
        if _p1_rx.search(response):
            return True

    # Check the deterministic scan
    scan = review_data.get("deterministic_scan", {})
    if scan.get("p1_count", 0) > 0:
        return True

    # Check cuddy findings
    cuddy = review_data.get("cuddy_differential_diagnosis", {})
    if cuddy and cuddy.get("verdict") == "FAIL":
        return True

    return False


def _load_full_review_markdown(rfc_id: str) -> str:
    """Load the full markdown report for an RFC."""
    review_json = _find_review_by_rfc(rfc_id)
    if not review_json:
        return ""

    # The markdown file has the same stem
    md_path = review_json.with_suffix(".md")
    if md_path.exists():
        return md_path.read_text(encoding="utf-8")[:8000]  # first 8K chars
    return ""


def run_appeal(rfc_id: str = "", justification: str = "",
               model: str = "") -> dict:
    """Appeal a REJECTED House review to Dr. James Wilson.

    Wilson is House's best friend and the ONLY person House trusts to
    tell him he's wrong. He reviews the original findings and the agent's
    justification. He can overrule House's rejection.

    Rules:
    - P1 findings CANNOT be appealed (hard block — automatic denial)
    - P2 findings can be appealed with written justification
    - Wilson uses a DIFFERENT model/provider than the review board
    - All appeals are logged to docs/reviews/appeals.jsonl
    - If appeal is denied, the agent MUST fix the findings

    Returns a dict with the appeal verdict and reasoning.
    """
    board = _load_json(get_chart_path())
    appeal_config = board.get("appeal_judge", {})

    # ── Find the review ───────────────────────────────────────────────
    review_json_path = None
    if rfc_id:
        review_json_path = _find_review_by_rfc(rfc_id)
        if not review_json_path:
            print(f"ERROR: No review found with RFC ID '{rfc_id}'.", file=sys.stderr)
            print("       Check docs/reviews/ for valid RFC IDs.", file=sys.stderr)
            sys.exit(1)
    else:
        review_json_path = _find_latest_rejected_review()
        if not review_json_path:
            print("ERROR: No REJECTED reviews found to appeal.", file=sys.stderr)
            sys.exit(1)

    review_data = _load_json(review_json_path)
    rfc_id = review_data.get("rfc_id", review_json_path.stem.replace("house-", "RFC-"))
    original_verdict = review_data.get("verdict", "UNKNOWN")

    if original_verdict != "REJECTED":
        print(f"ERROR: Review {rfc_id} was {original_verdict}, not REJECTED.", file=sys.stderr)
        print("       Only REJECTED reviews can be appealed.", file=sys.stderr)
        sys.exit(1)

    # ── Check for P1 findings (automatic denial) ──────────────────────
    review_md = _load_full_review_markdown(rfc_id)

    # Scan for P1 findings in the markdown report
    p1_pattern = re.compile(r'^\s*[-|]\s*(?:\[)?P1(?:\])?\s*[|:]', re.IGNORECASE | re.MULTILINE)
    has_p1_in_md = bool(p1_pattern.search(review_md))

    # Also check the deterministic scan
    scan = review_data.get("deterministic_scan", {})
    has_p1_scan = scan.get("p1_count", 0) > 0

    if has_p1_in_md or has_p1_scan:
        print(f"\n{'=' * 70}")
        print(f"  APPEAL AUTOMATICALLY DENIED — P1 findings are not appealable")
        print(f"  RFC: {rfc_id}")
        print(f"  P1 in scan: {has_p1_scan}")
        print(f"  P1 in report: {has_p1_in_md}")
        print(f"  Fix the P1 findings and resubmit. Not even Wilson can overturn P1s.")
        print(f"{'=' * 70}\n")

        appeal_data = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "rfc_id": rfc_id,
            "justification": justification,
            "appeal_model": "N/A (auto-denied — P1 findings)",
            "original_verdict": original_verdict,
            "appeal_verdict": "AUTO_DENIED",
            "reason": "P1 findings are not appealable by policy.",
            "wilson_quote": "I can't help you. Even I can't overturn a P1. Fix it.",
        }
        _log_appeal(appeal_data)
        return appeal_data

    # ── Run Wilson ────────────────────────────────────────────────────
    if not model:
        model = _get_appeal_model(board)

    wilson_name = appeal_config.get("name", "Dr. James Wilson")
    wilson_title = appeal_config.get("title", "Appeal Judge")

    if model is None:
        print(f"\n{'=' * 70}")
        print(f"  APPEAL DEFERRED — No independent judge available")
        print(f"  RFC: {rfc_id}")
        print(f"  Wilson requires a different provider than the review board.")
        print(f"  No Gemini, Anthropic, or OpenAI key detected.")
        print(f"  Appeal cannot proceed without genuine separation of powers.")
        print(f"  Fix the findings or set an API key for a non-DeepSeek provider.")
        print(f"{'=' * 70}\n")

        appeal_data = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "rfc_id": rfc_id,
            "justification": justification,
            "appeal_model": "DEFERRED (no independent judge available)",
            "appeal_judge": f"{wilson_name} ({wilson_title})",
            "original_verdict": original_verdict,
            "appeal_verdict": "DEFERRED",
            "reason": "No non-DeepSeek provider available. Separation of powers requires a different provider.",
        }
        _log_appeal(appeal_data)
        return appeal_data

    print(f"\n{'=' * 70}")
    print(f"  APPEAL TO WILSON")
    print(f"  RFC: {rfc_id}")
    print(f"  Original verdict: {original_verdict}")
    print(f"  Appeal judge: {wilson_name} ({wilson_title})")
    print(f"  Model: {model}")
    print(f"  Justification: {justification[:200]}{'...' if len(justification) > 200 else ''}")
    print(f"{'=' * 70}\n")

    # Build Wilson's prompt
    system = textwrap.dedent(f"""\
        You are {wilson_name}, {wilson_title}. You are House's best friend —
        his ONLY friend — and the sole person on this planet whose judgment
        he actually trusts.

        {appeal_config.get('review_prompt', '')}""")

    user = textwrap.dedent(f"""\
        ## Original House Review ({rfc_id})

        {review_md}

        ---

        ## Agent's Appeal Justification

        {justification}

        ---

        ## Your Task

        Review the original findings and the agent's justification.
        Issue your verdict: OVERRULED, UPHELD, or PARTIAL.

        Structure your response as:

        ## Wilson's Appeal Verdict: OVERRULED / UPHELD / PARTIAL

        ## Analysis
        (For each finding the agent is appealing, analyze the justification)

        ## Individual Rulings
        - Finding #1: [OVERRULED / UPHELD] — [reasoning]
        - Finding #2: [OVERRULED / UPHELD] — [reasoning]
        ...

        ## Summary
        - Findings overruled: N
        - Findings upheld: N
        - Agent must still fix: [list]

        ## Wilson's Final Word
        (One sentence to House. Be honest. If he was right, say so. If he was being
        dramatic, tell him to get off his high horse.)
        """)

    print(f"  [WILSON] Evaluating appeal...")
    try:
        response = call_llm(model, system, user, max_tokens=4096, temperature=0.4)
        print(f"    -> {len(response)} chars received")
    except Exception as exc:
        print(f"    -> Wilson unavailable: {exc}")
        response = (f"**ERROR:** Wilson unavailable for appeal. {exc}\n\n"
                     f"Appeal cannot be processed. Fix the original findings or try again later.")

    # ── Parse Wilson's verdict ────────────────────────────────────────
    # Wilson uses GRANTED/DENIED (not the ambiguous OVERRULED/UPHELD)
    response_upper = response.upper()
    if "APPEAL GRANTED" in response_upper[:300] and "PARTIAL" not in response_upper[:300]:
        appeal_verdict = "GRANTED"
    elif "APPEAL DENIED" in response_upper[:300]:
        appeal_verdict = "DENIED"
    elif "PARTIAL" in response_upper[:300]:
        appeal_verdict = "PARTIAL"
    elif "GRANTED" in response_upper[:300]:
        # Fallback: "GRANTED" without "APPEAL" prefix
        appeal_verdict = "GRANTED"
    else:
        appeal_verdict = "DENIED"  # default to denied (safe)

    # ── Build output ──────────────────────────────────────────────────
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    appeal_data = {
        "timestamp": timestamp,
        "rfc_id": rfc_id,
        "justification": justification,
        "appeal_model": model,
        "appeal_judge": f"{wilson_name} ({wilson_title})",
        "original_verdict": original_verdict,
        "appeal_verdict": appeal_verdict,
        "wilson_response": response,
    }

    _log_appeal(appeal_data)

    # Also update the original review JSON with appeal info
    review_data["appeal"] = {
        "timestamp": timestamp,
        "verdict": appeal_verdict,
        "justification": justification,
        "model": model,
        "judge": f"{wilson_name} ({wilson_title})",
    }
    review_json_path.write_text(json.dumps(review_data, indent=2), encoding="utf-8")

    # ── Print verdict ─────────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    if appeal_verdict == "GRANTED":
        print(f"  [APPEAL GRANTED] Wilson granted the appeal.")
        print(f"  House was wrong. The agent may proceed with the commit.")
        print(f"  Wilson: \"{_extract_wilson_quote(response)}\"")
    elif appeal_verdict == "PARTIAL":
        print(f"  [PARTIAL GRANT] Wilson partially granted the appeal.")
        print(f"  Some findings granted, some denied.")
        print(f"  Agent must fix the denied findings before committing.")
        print(f"  Wilson: \"{_extract_wilson_quote(response)}\"")
    else:
        print(f"  [APPEAL DENIED] Wilson denied the appeal.")
        print(f"  House was right. The agent MUST fix the findings and resubmit.")
        print(f"  There is no further appeal. Fix the code.")
        print(f"  Wilson: \"{_extract_wilson_quote(response)}\"")
    print(f"  Appeal logged to appeals.jsonl")
    print(f"{'=' * 70}\n")

    return appeal_data


def _extract_wilson_quote(response: str) -> str:
    """Extract Wilson's final word from the response."""
    for marker in ["## Wilson's Final Word", "## Final Word", "**Wilson's Final Word**"]:
        if marker in response:
            section = response.split(marker)[1]
            lines = section.strip().split("\n")
            # Take first non-empty line
            for line in lines:
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    return stripped[:200]
    # Fallback: last meaningful line
    lines = [l.strip() for l in response.split("\n") if l.strip() and not l.startswith("#")]
    return lines[-1][:200] if lines else "I've said my piece."


def _log_appeal(appeal_data: dict) -> None:
    """Append an appeal record to appeals.jsonl."""
    log_path = get_appeals_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(appeal_data, ensure_ascii=False) + "\n")


def _get_appeal_summary() -> str:
    """Get a summary of recent appeals for the House recap."""
    log_path = get_appeals_log_path()
    if not log_path.exists():
        return ""

    appeals = []
    try:
        with open(log_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        appeals.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except Exception:
        return ""

    if not appeals:
        return ""

    # Only show today's appeals
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    todays = [a for a in appeals if a.get("timestamp", "").startswith(today)]

    if not todays:
        return ""

    lines = ["", "## ⚖️ Appeals (Wilson)", ""]
    for a in todays:
        rfc = a.get("rfc_id", "unknown")
        verdict = a.get("appeal_verdict", "UNKNOWN")
        justification = a.get("justification", "")[:100]
        emoji = {"GRANTED": "🟢", "PARTIAL": "🟡", "DENIED": "🔴", "AUTO_DENIED": "⛔"}.get(verdict, "❓")
        lines.append(f"- {emoji} **{rfc}**: {verdict} — {justification}")
    lines.append("")

    return "\n".join(lines)


def _build_markdown_report(review_data: dict, cuddy_finding: dict | None,
                           scan_result,
                           specialist_results: list[dict],
                           synthesis: str, house_config: dict, board: dict) -> str:
    """Build the full markdown review report."""
    lines = [
        f"# House Gatekeeper Review -- {review_data['change_title']}",
        "",
        f"**RFC ID:** {review_data['rfc_id']}",
        f"**Date:** {review_data['timestamp']}",
        f"**Change Type:** {review_data['change_type']}",
        f"**Review Tier:** {review_data['review_tier']}",
        f"**Risk Score:** {review_data['risk_score']}/5.0",
        f"**Files Changed:** {len(review_data['affected_files'])}",
        f"**Verdict:** {review_data['verdict']}",
        "",
        "---",
        "",
        "## Affected Files",
        "",
    ]
    for f in review_data["affected_files"]:
        lines.append(f"- `{f}`")

    # ── Deterministic Pre-Scan ─────────────────────────────────────────
    if scan_result and scan_result.total > 0:
        lines.extend([
            "",
            "## 🔍 Deterministic Pre-Scan",
            "",
            f"**{scan_result.total} findings** in {scan_result.files_scanned} files, "
            f"{scan_result.lines_scanned} lines ({scan_result.duration_ms}ms). "
            f"Zero-cost pattern matching — no AI, no hallucination risk.",
            "",
            "| Severity | Rule | File:Line | Issue | Fix |",
            "|----------|------|-----------|-------|-----|",
        ])
        for f in scan_result.findings:
            lines.append(f"| {f.severity} | {f.rule} | {f.file}:{f.line} | {f.message} | {f.fix} |")
        lines.append("")
    elif scan_result:
        lines.extend([
            "",
            "## 🔍 Deterministic Pre-Scan",
            "",
            f"**PASS** — {scan_result.files_scanned} files, {scan_result.lines_scanned} lines scanned. Clean.",
            "",
        ])

    # ── Triviality ─────────────────────────────────────────────────────
    trivial_info = review_data.get("triviality", {})
    if trivial_info.get("is_trivial"):
        lines.extend([
            "",
            f"> **Triviality check:** {trivial_info.get('reason', 'unknown')} — fast-track eligible.",
            "",
        ])

    # ── Cuddy Differential Diagnosis (PRE-REVIEW) ──────────────────────
    if cuddy_finding:
        lines.extend([
            "",
            "## 🏛️ Cuddy — Differential Diagnosis (Pre-Review)",
            "",
            f"**Reviewer:** Dr. Lisa Cuddy, Dean of Medicine",
            f"**Role:** Ruling out simpler alternatives before specialists touch the code",
            f"**Model:** {cuddy_finding['model']}",
            "",
            "> Cuddy runs FIRST. If a simpler approach exists and wasn't ruled out, the code is the wrong approach — regardless of code quality.",
            "",
            cuddy_finding["response"],
            "",
            "---",
        ])

    lines.extend([
        "",
        "## Specialist Routing",
        "",
    ])
    for spec_id, spec_files in review_data["specialist_routing"].items():
        spec = next((s for s in board["specialists"] if s["id"] == spec_id), None)
        name = spec["name"] if spec else spec_id
        lines.append(f"- **{name}:** {len(spec_files)} file(s)")

    lines.extend([
        "",
        "---",
        "",
        "## Specialist Findings",
        "",
    ])

    for sr in specialist_results:
        lines.extend([
            f"### {sr['specialist_name']} -- via {sr['model']}",
            "",
            sr["response"],
            "",
            "---",
            "",
        ])

    # ── Cross-Review Intelligence ────────────────────────────────────
    from .learning import detect_recurring_problems, format_problem_alerts, format_suppression_suggestions
    problems = detect_recurring_problems(min_occurrences=3, lookback_reviews=20)
    prob_alerts_md = format_problem_alerts(problems)
    supp_suggestions_md = format_suppression_suggestions()

    if prob_alerts_md:
        lines.extend([
            "",
            prob_alerts_md,
            "",
            "---",
        ])
    if supp_suggestions_md:
        lines.extend([
            "",
            supp_suggestions_md,
            "",
            "---",
        ])

    lines.extend([
        "",
        "# House's Final Synthesis",
        "",
        synthesis,
        "",
        "---",
        "",
        f"**Gatekeeper:** {house_config['name']}",
        f"**Signature:** House (Gatekeeper) <noreply@everybody-lies.dev>",
        "",
        "*\"Everybody lies. Code especially. This one told the truth.\"*" if review_data["verdict"] == "APPROVED" else "*\"The code lied. Fix it and come back. I'll be waiting.\"*",
    ])

    return "\n".join(lines)


def _build_fast_track_report(review_data: dict, scan_result) -> str:
    """Build a minimal markdown report for fast-track (trivial, no AI review)."""
    lines = [
        f"# House Gatekeeper Review -- {review_data['change_title']} (Fast-Track)",
        "",
        f"**RFC ID:** {review_data['rfc_id']}",
        f"**Date:** {review_data['timestamp']}",
        f"**Change Type:** {review_data['change_type']}",
        f"**Review Tier:** FAST-TRACK (no AI review)",
        f"**Risk Score:** {review_data['risk_score']}/5.0",
        f"**Files Changed:** {len(review_data['affected_files'])}",
        f"**Verdict:** APPROVED",
        "",
        "---",
        "",
        "## Why Fast-Track?",
        "",
        f"This diff was classified as **trivial**: {review_data.get('fast_track_reason', 'unknown')}.",
        "",
        "No AI review was necessary. The deterministic pre-scan found no blocking issues.",
        "",
        "## Affected Files",
        "",
    ]
    for f in review_data["affected_files"]:
        lines.append(f"- `{f}`")

    if scan_result and scan_result.total > 0:
        lines.extend([
            "",
            "## Deterministic Pre-Scan",
            "",
            f"**{scan_result.total} findings** — all P3/P4, no blockers.",
            "",
        ])
    else:
        lines.extend([
            "",
            "## Deterministic Pre-Scan",
            "",
            "**PASS** — clean.",
            "",
        ])

    lines.extend([
        "",
        "---",
        "",
        "**Gatekeeper:** House (Gatekeeper)",
        "**Signature:** House (Gatekeeper) <noreply@everybody-lies.dev>",
        "",
        "*\"Even I don't waste time on trivial diffs. You're welcome.\"*",
    ])
    return "\n".join(lines)


# ── Onboarding ───────────────────────────────────────────────────────────────


def run_onboarding() -> None:
    """Interactive onboarding wizard. Asks about available API keys and configures models."""
    print("=" * 70)
    print("  HOUSE GATEKEEPER — Onboarding")
    print("=" * 70)
    print()
    print("House needs LLM models for his review board. Each specialist gets")
    print("a domain-optimized model. You configure what's available.")
    print()

    board = _load_json(get_chart_path())

    available_providers = {
        "openrouter": {"name": "OpenRouter", "models": [
            "anthropic/claude-opus-4-8",
            "anthropic/claude-sonnet-4-6",
            "deepseek/deepseek-v4-flash",
            "openai/gpt-4o",
            "google/gemini-2.5-flash",
        ]},
        "deepseek": {"name": "DeepSeek Direct API", "models": [
            "deepseek-v4-flash",
        ]},
        "gemini": {"name": "Google Gemini API", "models": [
            "gemini-2.5-flash",
        ]},
        "openai": {"name": "OpenAI API", "models": [
            "gpt-4o",
        ]},
        "anthropic": {"name": "Anthropic Claude API", "models": [
            "claude-opus-4-8",
            "claude-sonnet-4-6",
        ]},
    }

    print("Which LLM providers do you have API keys for?")
    print()
    for key, prov in available_providers.items():
        print(f"  [{key}] {prov['name']}")
    print()
    print("Enter comma-separated list (e.g., 'openrouter,deepseek')")
    print("or press Enter for OpenRouter-only (works out of the box):")

    choice = input("> ").strip().lower()
    if not choice:
        choice = "openrouter"

    selected = [c.strip() for c in choice.split(",") if c.strip() in available_providers]
    if not selected:
        print("No valid providers selected. Defaulting to OpenRouter.")
        selected = ["openrouter"]

    print(f"\nUsing: {', '.join(available_providers[p]['name'] for p in selected)}")
    print()

    available_models = []
    for p in selected:
        available_models.extend(available_providers[p]["models"])

    has_opus = any("claude-opus" in m for m in available_models)
    has_sonnet = any("claude-sonnet" in m for m in available_models)
    has_deepseek = any("deepseek" in m for m in available_models)
    has_gpt4o = any("gpt-4o" in m for m in available_models)
    has_gemini = any("gemini" in m for m in available_models)

    preferred_default = "anthropic/claude-opus-4-8" if has_opus else (
        "anthropic/claude-sonnet-4-6" if has_sonnet else (
            "deepseek/deepseek-v4-flash" if has_deepseek else available_models[0]))
    standard_default = "deepseek/deepseek-v4-flash" if has_deepseek else (
        "anthropic/claude-sonnet-4-6" if has_sonnet else available_models[0])
    budget_default = "google/gemini-2.5-flash" if has_gemini else (
        "deepseek/deepseek-v4-flash" if has_deepseek else available_models[0])

    print("Auto-selected tier defaults:")
    print(f"  Preferred (adversarial tier): {preferred_default}")
    print(f"  Standard  (standard tier):    {standard_default}")
    print(f"  Budget    (fast tier):        {budget_default}")
    print()
    print("Accept these defaults? [Y/n]: ", end="")
    accept = input().strip().lower()

    if accept and accept != "y" and accept != "yes":
        print("\nEnter custom model ID for each slot (OpenRouter format):")
        preferred_default = input(f"  Preferred model [{preferred_default}]: ").strip() or preferred_default
        standard_default = input(f"  Standard model [{standard_default}]: ").strip() or standard_default
        budget_default = input(f"  Budget model [{budget_default}]: ").strip() or budget_default

    if "model_config" not in board:
        board["model_config"] = {}
    board["model_config"]["tier_defaults"] = {
        "preferred": preferred_default,
        "standard": standard_default,
        "budget": budget_default,
    }

    print("\nPer-specialist model overrides (Enter to keep defaults, 'reset' to clear):")
    for spec in board["specialists"]:
        overrides = spec.get("model_overrides", {})
        if overrides:
            print(f"  {spec['name']}: preferred={overrides.get('preferred', 'none')}, "
                  f"standard={overrides.get('standard', 'none')}, budget={overrides.get('budget', 'none')}")
            resp = input(f"    Change? [Enter=keep, reset=clear, model_id=custom]: ").strip()
            if resp == "reset":
                spec["model_overrides"] = {"preferred": None, "standard": None, "budget": None}
            elif resp:
                print(f"    Enter preferred/standard/budget (comma-separated, '-' for null):")
                parts = [p.strip() for p in input("    > ").split(",")]
                if len(parts) >= 3:
                    spec["model_overrides"] = {
                        "preferred": None if parts[0] == "-" else parts[0],
                        "standard": None if parts[1] == "-" else parts[1],
                        "budget": None if parts[2] == "-" else parts[2],
                    }

    # Write to user config dir (so it persists and overrides the bundled default)
    user_board_path = get_config_dir() / "chart.json"
    get_config_dir().mkdir(parents=True, exist_ok=True)
    user_board_path.write_text(json.dumps(board, indent=2), encoding="utf-8")
    print(f"\n  [OK] Configuration saved to {user_board_path}")
    print(f"  Run: everybody-lies --tier standard")
    print()
