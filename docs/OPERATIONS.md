# everybody-lies — Operations Runbook

> **Version:** 0.3.1 | **Last updated:** 2026-11-12  
> **Purpose:** Full operational guide for installing, configuring, and operating House across multiple machines.

---

## 1. Installation

### Prerequisites

- Python 3.10 or later
- git (for diff operations and hooks)
- At least one LLM provider API key (see [Configuration](#2-configuration))

### pip install

```bash
pip install everybody-lies
# or from GitHub Releases:
pip install https://github.com/mfolofy/everybody-lies/releases/download/v0.3.1/everybody_lies-0.3.1-py3-none-any.whl
# or from source:
pip install -e /path/to/everybody-lies
```

### Install hooks

**Pre-commit hook** (quality review gate):

```bash
cat > .git/hooks/pre-commit << 'EOF'
#!/bin/bash
everybody-lies --staged --tier fast
EOF
chmod +x .git/hooks/pre-commit
```

**Pre-push hook** (scope enforcement gate):

```bash
cp docs/hooks/pre-push .git/hooks/pre-push
chmod +x .git/hooks/pre-push
```

Both hooks are standalone shell scripts. They work on Linux, macOS, and Windows (via Git Bash).

### Verify installation

```bash
everybody-lies --version
pip show everybody-lies

# Test deterministic scan only (zero AI cost)
everybody-lies --staged --tier fast --dry-run
```

---

## 2. Configuration

### Provider API keys

House auto-detects API keys from environment variables. Set at least one:

```bash
# Claude Code users — already set
export ANTHROPIC_API_KEY="sk-ant-..."

# Cheapest ($0.27/1M input)
export DEEPSEEK_API_KEY="sk-..."

# Free tier available
export GEMINI_API_KEY="..."

# Universal fallback (any model)
export OPENROUTER_API_KEY="sk-or-..."
```

**Key bootstrap** for hooks/CI where env vars aren't available:

```bash
export EVERYBODY_LIES_API_KEYS='{"DEEPSEEK_API_KEY":"sk-...","GEMINI_API_KEY":"..."}'

# Or via secrets file:
export EVERYBODY_LIES_SECRETS_FILE=~/.my-keys.json
```

### chart.json

Default chart is bundled with the package at `everybody_lies/chart.json`. Override it:

```bash
# Copy and customize
cp "$(python -c 'import everybody_lies.config; print(everybody_lies.config.get_chart_path())')" ~/.everybody-lies/chart.json
# Or set a path
export EVERYBODY_LIES_CHART=/path/to/custom/chart.json
```

Key sections in `chart.json`:

| Section | Purpose |
|---------|---------|
| `model_config` | Tier-to-model mapping, preferred/budget model selection |
| `gatekeeper` | House's verdict synthesis rules |
| `appeal_judge` | Wilson's appeal configuration (different provider required) |
| `specialists` | Five domain specialists with prompts, file patterns, model overrides |
| `domain_routing` | File pattern → specialist routing rules |
| `tier_floors` | File patterns and risk score floors (see Section 5) |
| `dynamic_fellows` | Auto-hire/fire settings for uncovered domains |

### Repo-level override: `.house/chart.local.json`

Optional. Place it in the repo root (next to `.house/patients.json`); House deep-merges it over the chart above on every run, so you only write what differs. Objects merge key by key, lists of objects with an `id` (such as `specialists`) merge by id, anything else is replaced. A file that is not valid JSON blocks the run (exit 1) rather than being ignored. Keep it out of git with `.git/info/exclude` if it holds your private model choices. Treat it like a hook: do not run House in a repo you do not trust if it carries one.

```json
{
  "model_config": {
    "provider": "claude-code",
    "tier_defaults": { "preferred": "claude-sonnet-5-5", "budget": "claude-haiku-5-5" },
    "house_model":   { "preferred": "claude-opus-5-5", "standard": "claude-opus-5-5", "budget": "claude-opus-5-5" }
  },
  "specialists": [ { "id": "cuddy", "model_overrides": { "preferred": "claude-opus-5-5", "standard": "claude-opus-5-5", "budget": "claude-opus-5-5" } } ],
  "appeal_judge": { "model": "claude-fable-5-2", "fallback_models": [] },
  "limits": { "max_rounds": 2, "daily_call_cap": 60 }
}
```

### Claude Code provider (`claude -p`, no API key)

| Key / variable | Default | Meaning |
|---|---|---|
| `model_config.provider` / `EVERYBODY_LIES_PROVIDER` | unset | `"claude-code"` sends every model call through the local `claude` CLI. Unset or `"auto"` = normal routing. Any other value blocks with an error. |
| `EVERYBODY_LIES_CLAUDE_TIMEOUT` | `240` | Seconds allowed for one `claude -p` call. |

Auto-detection: when `claude` is on PATH **and** no API key variable is set, House uses it with `claude-sonnet-5-5`. Users with keys are unaffected. The call is `claude -p --model <id> --output-format text` with the prompt on stdin, run in an empty temp directory. Model ids are passed through unchanged. With `provider` set but `claude` missing from PATH, House exits 1 with a message. There is no cross-provider failover in this mode. Wilson (appeals) uses the CLI too when his configured model routes to it.

### Round cap (`limits.max_rounds`, default unset)

Rounds are counted per change (same title, same UTC day) across `reviews/` and `reviews/archive/`; an APPROVED review starts a new count. With `max_rounds: 2`:

1. Round 1 runs as usual.
2. Round 2 is told the previous round's findings and may only report whether each is FIXED or STILL PRESENT, plus new P1 findings (no new P2/P3/P4).
3. If round 2 still fails the verdict is **STUCK**: exit 1, listed as `OPEN:` lines, no appeal (a person decides). A third attempt returns STUCK straight away, with no model calls.

To continue anyway, fix by hand and re-run with `EVERYBODY_LIES_MAX_ROUNDS=0` (or a higher number), or use a bypass (section 4).

### Daily call cap (`limits.daily_call_cap`, default unset)

Counts model calls per UTC day in `~/.everybody-lies/stats.json` (`usage`, last 14 days kept; only counted while a cap is set). The call after the cap is not made: the run ends with verdict **BLOCKED** (exit 1) and the message says how to override (`EVERYBODY_LIES_DAILY_CALL_CAP=<higher number>`, `0` = no cap, or edit `limits.daily_call_cap`). It cannot turn into the "providers unreachable, approved degraded" path. A request for an appeal after the cap is hit is denied the same way. Tokens are not capped because House does not estimate them.

### patients.json (pre-push scope enforcement)

Create `.house/patients.json` in your repo root. Template at `docs/patients.example.json`. Full schema reference in [Section 6](#6-patient-file-reference).

### Configuration directory

All config lives in `~/.everybody-lies/`:

```
~/.everybody-lies/
├── chart.json             # Override chart (optional)
├── reviews/               # RFC report archive
│   ├── archive/           # Prior review rounds (preserved)
│   ├── appeals.jsonl      # Appeal audit log
│   └── house-commits.jsonl # Commit audit log
├── stats.json             # Review statistics
└── dynamic_fellows.json   # Persisted dynamic specialists
```

Override base directory:

```bash
export EVERYBODY_LIES_HOME=/custom/path
```

---

## 3. Daily Usage

### Committing with context

When an AI agent commits, declare its environment via `HOUSE_GATE`:

```bash
# Agent committing clean — skip subagent process scan
HOUSE_GATE='{"subagents_running":false}' git commit -m "fix: typo"

# Agent committing with locked design decisions
HOUSE_GATE='{"subagents_running":false,"locked_decisions":"React per PRD §5. TypeScript strict. REST API only.","tier_floor":"standard"}' git commit -m "feat: add user profile page"
```

**Without `HOUSE_GATE`:** The pre-commit hook falls back to a process scan (psutil, tasklist, pgrep). If opencode subagents are found, Cuddy blocks the commit.

### What each gate does

| Gate | When it runs | What it checks | Blocked by |
|------|-------------|----------------|------------|
| **Cuddy Pre-Flight** | Pre-commit, before any review | Running opencode subagents | `HOUSE_GATE.subagents_running: true`, or process scan finds subagents |
| **PRD Auto-Injection** | Pre-commit, before Cuddy review | Extracts locked decisions from `CHARTER.md`/`PHASE*_PRD.md`/`*_SPEC.md` | Nothing — always runs |
| **Deterministic Pre-Scan** | Pre-commit, before AI calls | Hardcoded secrets, debug=True, unresolved TODOs | Nothing — always runs (zero cost) |
| **Cuddy Differential** | Pre-commit, after pre-scan | Simpler alternatives not ruled out | `HOUSE_BYPASS=1` |
| **Specialist Review** | Pre-commit, after Cuddy | Domain-specific code quality | `HOUSE_BYPASS=1` |
| **Pre-Push Scope** | Pre-push hook | Files must match per-remote allowed_paths | `HOUSE_BYPASS=1` (unless bypass_protected) |

### Reading verdicts

Verdict appears in terminal output:

```
======================================================================
  [APPROVED] VERDICT: APPROVED
  House signs off. Commit and deploy.
======================================================================
```

```
======================================================================
  [REJECTED] VERDICT: REJECTED
  BLOCKER: Cuddy: P1 — simpler alternative exists, approach is wrong
  BLOCKER: Dr. Eric Foreman: P2 — N+1 query in user_list route
  Fix the issues above and resubmit. P1 findings are not appealable.
  P2 findings: everybody-lies --appeal "your justification"
======================================================================
```

Full reports saved to `~/.everybody-lies/reviews/house-YYYY-MM-DD-<slug>.md` and `.json`.

### Exit codes

| Exit code | Meaning |
|-----------|---------|
| **0** | APPROVED — proceed with commit/push |
| **1** | REJECTED — fix findings or appeal. Also STUCK (round cap reached, needs a person) and BLOCKED (daily call cap reached) |
| **2** | ERROR — configuration/network issue |

---

## 4. Bypass Procedures

### Quick reference

| Situation | Command | Effect |
|-----------|---------|--------|
| Skip pre-commit review | `HOUSE_BYPASS=1 git commit -m "..."` | All House gates skipped for this commit |
| Skip pre-push scope check | `HOUSE_BYPASS=1 git push` | Scope check skipped (unless bypass_protected) |
| Skip pre-commit only (non-`--no-verify`) | Set HOUSE_BYPASS, normal commit | Review skipped, House logs bypass |
| Git `--no-verify` | `git commit --no-verify -m "..."` | Pre-commit hook not invoked at all. House can't log it. |

### HOUSE_BYPASS

```bash
HOUSE_BYPASS=1 git commit -m "hotfix: emergency cuddy subagent fix"
```

**What gets skipped:**
- Cuddy subagent pre-flight check
- Deterministic pre-scan
- Cuddy differential diagnosis
- All specialist reviews
- House verdict synthesis

**What does NOT get skipped:**
- Pre-push scope enforcement on `bypass_protected: true` remotes — HOUSE_BYPASS has no effect
- Pre-push scope enforcement on `bypass_protected: false` remotes — HOUSE_BYPASS does skip

**What gets logged:** Every bypass is recorded in `~/.everybody-lies/reviews/house-commits.jsonl` with `"verdict": "BYPASSED"`, timestamp, and (optionally) a bypass reason.

### bypass_protected

When `bypass_protected: true` is set on a remote in `.house/patients.json`:

```json
"my-critical-repo": {
  "bypass_protected": true,
  ...
}
```

`HOUSE_BYPASS=1` has **no effect** on pushes to that remote. The only way to push is:
1. Fix the files so they comply with the scope policy, OR
2. Update `patients.json` to allow the files and commit that change first

### When to use each bypass

| Scenario | Recommended method |
|----------|-------------------|
| Production hotfix — known safe, need immediate deploy | `HOUSE_BYPASS=1` |
| Config change only (no code) — review would be noise | `HOUSE_BYPASS=1` |
| House false positive (known bug) — bypass while waiting for fix | `HOUSE_BYPASS=1` with reason |
| Pushing to bypass_protected remote — bypass not available | Fix the files |
| Interactive debugging commit — never intended for history | `git commit --no-verify` (not logged by House) |

### Audit trail

All bypass entries are permanently recorded in `house-commits.jsonl`:

```json
{"commit": null, "rfc_id": null, "verdict": "BYPASSED", "rounds": 0, "tier": null, "files": [], "timestamp": "2026-06-05T00:00:00Z", "bypassed": true, "bypass_reason": null}
```

There is no "silent bypass." Every HOUSE_BYPASS leaves a record.

---

## 5. Tier System

### Available tiers

| Tier | Behavior | Approx. cost |
|------|----------|-------------|
| `fast` | 1 budget model per specialist | ~$0.02 |
| `standard` | 1 preferred model per specialist | ~$0.15 |
| `adversarial` | 2 models cross-check per specialist | ~$0.50 |

### Auto-floor rules

Tier floors are calculated from two sources (highest wins):

**File pattern floors** (`chart.json` → `tier_floors.file_patterns`):

| Pattern | Min Tier |
|---------|----------|
| `**/migrations/**`, `**/migrate*.py`, `**/db/schema*`, `**/db/migrate*` | `standard` |
| `**/auth/**` | `standard` |
| `**/financial/**`, `**/proprietary/**` | `adversarial` |
| `**/.env*`, `**/secrets/**`, `**/*.pem`, `**/*.key` | `adversarial` |

**Risk score floors** (`chart.json` → `tier_floors.risk_score_floors`):

| Risk Score | Min Tier |
|------------|----------|
| ≥ 4.0 | `adversarial` |
| ≥ 2.5 | `standard` |

**Override via HOUSE_GATE:**

```bash
# Force adversarial regardless of file content
HOUSE_GATE='{"tier_floor":"adversarial"}' everybody-lies --staged --tier fast
```

Note: `tier_floor` in HOUSE_GATE sets a **minimum**. chart.json file patterns can still raise it further. You cannot lower the floor below what config requires.

### Console output when tier is upgraded

```
[HOUSE] Tier upgraded: fast -> standard (files: migrations/003_add_users.sql)
[HOUSE] Tier upgraded: standard -> adversarial (risk score: 4.2)
[HOUSE] Tier upgraded: fast -> adversarial (tier_floor from HOUSE_GATE)
```

### How tier maps to models

| Tier | Slot used |
|------|-----------|
| `adversarial` | `preferred` (chart.json → `model_config.tier_defaults.preferred`) |
| `standard` | `preferred` |
| `fast` | `budget` (chart.json → `model_config.tier_defaults.budget`) |

In adversarial tier, each specialist is called **twice** with different models. The two responses are cross-checked for consensus.

Specialists can override the model per-tier via `model_overrides` in chart.json.

---

## 6. Patient File Reference

### File location

`.house/patients.json` in the repo root. Read by the pre-push hook.

### Full schema

```json
{
  "remotes": {
    "<remote-name>": {
      "allowed_paths": ["glob1/**", "glob2/**"],
      "blocked_paths": ["glob1/**", "glob2/**"],
      "force_push": "deny" | "warn" | "allow",
      "block_tags": true | false,
      "block_deletes": true | false,
      "bypass_protected": true | false
    }
  },
  "default": {
    "allowed_paths": [],
    "blocked_paths": ["**"],
    "force_push": "deny",
    "block_tags": true,
    "block_deletes": true,
    "bypass_protected": false
  }
}
```

### Field reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `allowed_paths` | `list[str]` | `[]` | Glob patterns for files allowed to be pushed. Empty list = no restriction (all paths allowed). Non-empty = files must match at least one pattern. |
| `blocked_paths` | `list[str]` | `["**"]` | Glob patterns for files blocked from being pushed. **Always wins** over `allowed_paths`. |
| `force_push` | `"deny"` \| `"warn"` \| `"allow"` | `"deny"` | `"deny"` = block force pushes. `"warn"` = allow with warning. `"allow"` = no restriction. |
| `block_tags` | `bool` | `true` | Block `git push --tags` and individual tag pushes. |
| `block_deletes` | `bool` | `true` | Block `git push origin :branch` (branch deletion). |
| `bypass_protected` | `bool` | `false` | When `true`, `HOUSE_BYPASS=1` does **not** skip the scope check for this remote. |

### Precedence rules

1. **`blocked_paths` always wins.** If a file matches any `blocked_paths` pattern, it is rejected — even if it also matches `allowed_paths`.
2. **Unknown remotes block everything.** If a remote name is not in `remotes`, the `default` policy applies. Default: `blocked_paths: ["**"]` and `allowed_paths: []` — everything is blocked.
3. **Empty `allowed_paths` = no restriction.** Only `blocked_paths` applies.
4. **Non-empty `allowed_paths` = must match.** Files must match at least one `allowed_paths` pattern AND not match any `blocked_paths` pattern.
5. **`bypass_protected: true` overrides `HOUSE_BYPASS`.** No amount of bypassing skips this check.

### Example: monorepo external-repo push

```json
{
  "remotes": {
    "origin": {
      "allowed_paths": ["**"],
      "blocked_paths": ["secrets/**", "*.pem", ".env*"],
      "force_push": "warn",
      "block_tags": false,
      "block_deletes": false,
      "bypass_protected": false
    },
    "internal-repo": {
      "allowed_paths": ["internal-repo/**"],
      "blocked_paths": ["secrets/**", "*.pem"],
      "force_push": "deny",
      "block_tags": true,
      "block_deletes": true,
      "bypass_protected": true
    }
  },
  "default": {
    "allowed_paths": [],
    "blocked_paths": ["**"],
    "force_push": "deny",
    "block_tags": true,
    "block_deletes": true,
    "bypass_protected": false
  }
}
```

With this config:
- `origin` → anything goes (except secrets)
- `internal-repo` → only `internal-repo/` files allowed, secrets blocked, HOUSE_BYPASS can't help
- Any other remote → blocked entirely

---

## 7. Troubleshooting

### Hook not running

**Symptom:** Commits go through without House review.

**Check:**
```bash
ls -la .git/hooks/pre-commit
ls -la .git/hooks/pre-push
```
Hooks must be executable files, not directories or symlinks to nothing.

**Fix:**
```bash
chmod +x .git/hooks/pre-commit
chmod +x .git/hooks/pre-push
```

### "everybody-lies: command not found"

**Symptom:** Pre-commit hook fails with command not found.

**Check:**
```bash
which everybody-lies
pip show everybody-lies
```

**Fix:** Re-install: `pip install everybody-lies`. Ensure pip's bin directory is in PATH.

### config file not found

**Symptom:** `ERROR: chart.json not found`

**Check:**
```bash
python -c "import everybody_lies.config; print(everybody_lies.config.get_chart_path())"
```

**Fix:** The bundled chart.json should be installed with the package. If missing, reinstall: `pip install --force-reinstall everybody-lies`.

### "[HOUSE] WARNING: python not found — pre-push scope check skipped"

**Symptom:** Pre-push hook skips silently. No scope enforcement.

**Cause:** The pre-push hook uses `command -v python3 || command -v python`. On some systems, `python` is not available in the hook's PATH.

**Fix:**
```bash
# Ensure python is in PATH
which python3

# Or edit the hook to use a full path:
PYTHON="/usr/bin/python3"
```

### "Pre-push blocked: out-of-scope files detected"

**Symptom:** Pre-push hook rejects your push.

**Check what files are being pushed:**
```bash
git rev-list --objects <old-sha>..<new-sha>
```

**Check your patients.json:**
```bash
cat .house/patients.json
```

**Fix options:**
1. Only commit files within the allowed scope
2. Update `patients.json` to add allowed paths for legitimate files
3. Bypass: `HOUSE_BYPASS=1 git push` (if bypass_protected is false)

### "Everyone says 'just run it again' — Cuddy keeps rejecting the same code"

**Symptom:** Cuddy rejects on round 1, then round 2, then round 3... each round with different findings on the same diff.

This is **BUG-001** (see `BUGS.md`). Cuddy has no memory of prior rounds.

**Workaround:** Appeal to Wilson. Wilson has global context and resolves contradictions. Two appeals on most diffs return PARTIAL GRANT.

```bash
everybody-lies --appeal "Finding already addressed in prior review round RFC-2026-06-01-..."
```

### "Wilson can't run — no distinct provider"

**Symptom:** Appeals fail with message about Wilson needing a different provider.

**Cause:** Wilson uses direct provider APIs only (DeepSeek, then Anthropic). OpenRouter and Gemini are not used for appeals.

**Fix:** Set at least one of:
```bash
export DEEPSEEK_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
```

---

## 8. Multi-Machine Installation

### Single-node installation

```bash
pip install everybody-lies
cp docs/hooks/pre-commit /path/to/repo/.git/hooks/pre-commit && chmod +x /path/to/repo/.git/hooks/pre-commit
cp docs/hooks/post-commit /path/to/repo/.git/hooks/post-commit && chmod +x /path/to/repo/.git/hooks/post-commit
cp docs/hooks/pre-push /path/to/repo/.git/hooks/pre-push && chmod +x /path/to/repo/.git/hooks/pre-push
```

### Git submodule method (for many repos)

If everybody-lies is tracked as a git submodule in your repos:

```bash
git submodule update --init --remote
pip install -e ./everybody-lies  # editable install for development
```

### Bulk update across machines

```bash
# On each node:
cd /path/to/everybody-lies
git pull --rebase origin main
pip install -e . --force-reinstall

# Update hooks in repos that use House
for repo in /path/to/repo1 /path/to/repo2; do
    cp docs/hooks/pre-push "$repo/.git/hooks/pre-push"
    chmod +x "$repo/.git/hooks/pre-push"
done
```

### Verify consistency

```bash
# Check version is the same everywhere
everybody-lies --version

# Check chart.json is the same
python -c "import everybody_lies.config; print(everybody_lies.config.get_chart_path())"

# Run a dry-run test to verify providers are configured
everybody-lies --staged --tier fast --dry-run
```


