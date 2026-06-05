"""CLI entry point for everybody-lies.

Usage:
    everybody-lies --tier fast                    # Review unstaged changes, fast tier
    everybody-lies diagnose --staged               # Same thing, House MD themed
    everybody-lies --staged --tier standard       # Review staged changes
    everybody-lies --diff "$(git diff)"           # Review a specific diff
    everybody-lies --tier standard --dry-run      # Generate prompts only
    everybody-lies --onboard                      # Configure API keys and models
    everybody-lies --ci github-actions            # CI mode: GitHub Actions annotations
    everybody-lies --spec                         # Auto-detect and use SPEC.md for Cuddy
    everybody-lies --pre-push --remote origin     # Pre-push scope check (called by git hook)

    # With HOUSE_GATE context (agents set env vars before committing):
    HOUSE_GATE='{"subagents_running":false,"locked_decisions":"React per PRD §5","tier_floor":"standard"}' everybody-lies --staged
"""

import argparse
import sys
import textwrap

from .gatekeeper import (
    run_review, run_onboarding, run_appeal, run_cleanup,
    run_pre_push_check,
    _stamp_commit_sha, _write_bypass_log_entry,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="everybody-lies",
        description="Code review tools ask nicely. House doesn't. Five specialists. One verdict. Fix it.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              %(prog)s --tier fast                                          # Review unstaged changes, fast tier
              %(prog)s diagnose --staged --tier fast                        # Same thing, House MD themed
              %(prog)s --staged --tier standard                             # Review staged changes
              %(prog)s --diff "$(git diff main...HEAD)" --tier adversarial   # Review branch diff
              %(prog)s --files "src/auth.py,frontend/Login.tsx" --tier fast  # Review specific files
              %(prog)s --tier standard --dry-run                            # Generate prompts only
              %(prog)s --tier standard --title "Fix auth race" --type normal # Named review
              %(prog)s --onboard                                            # Configure API keys and models
              %(prog)s --ci github-actions                                  # CI mode: GitHub annotations
              %(prog)s --ci sarif --output results.sarif                    # CI mode: SARIF output
              %(prog)s --spec                                               # Use SPEC.md for Cuddy's differential
        """),
    )
    # "diagnose" positional — a pure aesthetic alias. House doesn't "review" code, he diagnoses it.
    parser.add_argument("command", nargs="?", default="review",
                        choices=["diagnose", "review"],
                        help=argparse.SUPPRESS)
    parser.add_argument("--tier", choices=["fast", "standard", "adversarial"],
                        default="standard", help="Review tier (default: standard)")
    parser.add_argument("--diff", default="", help="Git diff text to review")
    parser.add_argument("--files", default="", help="Comma-separated file paths")
    parser.add_argument("--staged", action="store_true", help="Review staged changes only")
    parser.add_argument("--title", default="", help="Change title for the review report")
    parser.add_argument("--type", dest="change_type", default="normal",
                        choices=["standard", "normal", "emergency", "major"],
                        help="ITIL change type (default: normal)")
    parser.add_argument("--dry-run", action="store_true", help="Generate prompts only, no LLM calls")
    parser.add_argument("--max-tokens", type=int, default=4096,
                        help="Max tokens per specialist response (default: 4096)")
    parser.add_argument("--output", default="", help="Output file path (auto-generated if omitted)")
    parser.add_argument("--onboard", action="store_true", help="Run interactive onboarding wizard to configure models")
    parser.add_argument("--ci", default="", choices=["github-actions", "gitlab", "sarif", ""],
                        help="CI mode: output annotations for CI/CD pipelines")
    parser.add_argument("--spec", action="store_true", default=False,
                        help="Auto-detect and use SPEC.md/*.feature files for Cuddy's differential diagnosis")
    parser.add_argument("--spec-file", default="", help="Path to specific spec file for Cuddy")
    parser.add_argument("--appeal", default="", help="Appeal a REJECTED review to Wilson. Provide written justification.")
    parser.add_argument("--rfc", default="", dest="rfc_id", help="RFC ID to appeal (auto-detects latest REJECTED if omitted)")
    parser.add_argument("--cleanup", action="store_true", help="Prune review artifacts older than --cleanup-days (default 30)")
    parser.add_argument("--cleanup-days", type=int, default=30, help="Age threshold in days for --cleanup (default: 30)")
    parser.add_argument("--cleanup-dry-run", action="store_true", help="Show what --cleanup would delete without deleting")
    # Hook integration — called by post-commit and post-commit-bypass hooks
    parser.add_argument("--stamp-commit", default="", metavar="SHA",
                        help="Back-fill commit SHA into the latest House log entry for --rfc")
    parser.add_argument("--log-bypass", default="", metavar="SHA",
                        help="Write a BYPASSED entry to house-commits.jsonl for this commit SHA")
    parser.add_argument("--bypass-reason", default="", help="Reason for bypass (used with --log-bypass)")
    # Pre-push scope check — called by .git/hooks/pre-push
    parser.add_argument("--pre-push", action="store_true",
                        help="Pre-push scope check mode. Reads git refspecs from stdin.")
    parser.add_argument("--remote", default="",
                        help="Remote name for --pre-push (git passes this as $1 in the hook)")

    args = parser.parse_args()

    # ── Pre-push scope check ─────────────────────────────────────────
    if args.pre_push:
        if not args.remote:
            print("ERROR: --pre-push requires --remote <name>", file=sys.stderr)
            sys.exit(1)
        refs = []
        for line in sys.stdin:
            parts = line.strip().split()
            if len(parts) == 4:
                # git pre-push stdin format: local_ref local_sha remote_ref remote_sha
                # local_sha = what we're pushing (new), remote_sha = current tip (old)
                refs.append({
                    "local_ref":  parts[0],
                    "local_sha":  parts[1],  # new commit — what's being pushed
                    "remote_ref": parts[2],
                    "remote_sha": parts[3],  # old commit — current remote tip
                })
            elif parts:  # non-empty but malformed
                print(f"[HOUSE] WARNING: skipping malformed refspec line: {line.rstrip()!r}",
                      file=sys.stderr)
        result = run_pre_push_check(args.remote, refs)
        verdict = result.get("verdict", "REJECTED")
        if verdict == "REJECTED":
            reason = result.get("reason", "scope violation")
            print(f"\n{'=' * 70}", file=sys.stderr)
            print(f"  [HOUSE — PRE-PUSH BLOCKED]", file=sys.stderr)
            print(f"  Remote: {args.remote}  Reason: {reason}", file=sys.stderr)
            violations = result.get("violations") or []
            for v in violations[:20]:  # cap output on large repos
                print(f"  ✗ {v}", file=sys.stderr)
            if len(violations) > 20:
                print(f"  ... and {len(violations) - 20} more", file=sys.stderr)
            print(f"  Set HOUSE_BYPASS=1 to override (logged). Fix .house/patients.json to allow.",
                  file=sys.stderr)
            print(f"{'=' * 70}", file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

    # ── Hook integration paths ────────────────────────────────────────
    if args.stamp_commit:
        ok = _stamp_commit_sha(rfc_id=args.rfc_id, sha=args.stamp_commit)
        if ok:
            print(f"[HOUSE-LOG] Stamped commit {args.stamp_commit[:8]} → {args.rfc_id}")
        else:
            print(f"[HOUSE-LOG] No pending log entry found for {args.rfc_id}", file=sys.stderr)
        sys.exit(0 if ok else 1)

    if args.log_bypass:
        _write_bypass_log_entry(commit_sha=args.log_bypass, bypass_reason=args.bypass_reason)
        print(f"[HOUSE-LOG] Bypass recorded: commit {args.log_bypass[:8]}")
        sys.exit(0)

    if args.onboard:
        run_onboarding()
        sys.exit(0)

    # ── Cleanup path ──────────────────────────────────────────────────
    if args.cleanup:
        result = run_cleanup(days=args.cleanup_days, dry_run=args.cleanup_dry_run)
        if args.cleanup_dry_run:
            print(f"Would delete {result['deleted']} review artifact(s) "
                  f"({result['freed_bytes'] / 1024:.0f} KB)")
        sys.exit(0)

    # ── Appeal path ───────────────────────────────────────────────────
    if args.appeal:
        result = run_appeal(
            rfc_id=args.rfc_id,
            justification=args.appeal,
        )
        verdict = result.get("appeal_verdict", "DENIED")
        if verdict in ("GRANTED", "PARTIAL"):
            sys.exit(0)
        else:
            sys.exit(1)

    files = None
    if args.files:
        files = [f.strip() for f in args.files.split(",") if f.strip()]

    result = run_review(
        diff_text=args.diff,
        files=files,
        tier=args.tier,
        title=args.title,
        change_type=args.change_type,
        staged=args.staged,
        dry_run=args.dry_run,
        max_tokens=args.max_tokens,
        ci_mode=args.ci if args.ci else None,
        spec_mode=args.spec,
        spec_file=args.spec_file if args.spec_file else None,
    )

    # CI output on stdout for pipeline consumption
    if args.ci and isinstance(result, dict):
        from .scanner import emit_ci_output
        emit_ci_output(result, args.ci, args.output if args.output else None)

    # Exit code: non-zero if REJECTED (so pre-commit hooks can block)
    if not isinstance(result, dict):
        print("ERROR: run_review returned unexpected type", file=sys.stderr)
        sys.exit(1)
    verdict = result.get("verdict", "")
    if verdict == "REJECTED":
        sys.exit(1)
    elif verdict == "APPROVED" or verdict == "dry_run":
        sys.exit(0)
    else:
        print(f"WARNING: Unknown verdict '{verdict}' — failing safe.", file=sys.stderr)
        sys.exit(1)
