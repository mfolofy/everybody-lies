# everybody-lies 💊

> *"To paraphrase Occam: the simplest explanation is your AI wrote shit code."*

**Code review tools ask nicely. House doesn't. Five specialists. One verdict. Fix it.**

**Three gates. Zero escapes.** Pre-commit quality review. Cuddy pre-flight subagent check. Pre-push scope enforcement.

<p align="center">
  <img src="demo.gif" alt="everybody-lies demo" width="720">
</p>

---

## Why This Exists — What It Feels Like When AI Gets It Wrong

You wake at 2 a.m. because a deploy just failed in production. The logs show every query on a critical table is doing a full scan. The migration that dropped the indexes compiled, all 22 tests passed, and the agent moved on. You realize the data layer is now live and broken.

Or you open GitHub and see your entire monorepo in a clean public repo you never created. Secrets/, agents/, every credential and infrastructure map are sitting there because the push only checked code style, not what files were leaving the machine.

Or two agents were running in parallel, one halfway through a refactor, the other mid-build loop. A commit landed with partial state from the unfinished session. It looked clean. It wasn't.

House exists because tests only prove the code runs what the author thought to test. They miss JWT secrets loadable from committed YAML. They miss a table recreate that silently destroys performance. They miss the moment an agent decides to push the whole repo somewhere it shouldn't.

The pre-commit review stops the logic, security, and approach errors that pass every local check. Cuddy's pre-flight blocks the commit when other agents still have uncommitted work in flight. The pre-push patient file catches the files that should never leave before the push happens. HOUSE_GATE lets the agent say "I'm clean, here's my context" instead of forcing House to guess.

You want it running before every commit, not after, because finding the damage at 2 a.m. is too late.

---

## What is this?

A differential diagnosis for your codebase. Cuddy rules out simpler alternatives first. Then five domain specialists review every commit through their own lens. House issues the final verdict. Unanimous consent required. P1 findings are absolute. P2 findings can be appealed to Wilson. No apologies. No "looks good to me."

Three built-in enforcement gates keep your repo clean: pre-commit quality review, Cuddy pre-flight (blocks commits while subagents are running), and pre-push scope enforcement (prevents pushing monorepo files to external remotes). Agents declare their context via `HOUSE_GATE`. Tier floors auto-upgrade review intensity for high-risk files.

Your AI wrote it. It's wrong. House proves exactly why.

```
$ everybody-lies --staged --tier fast
$ everybody-lies diagnose --staged           # Same thing, House MD themed
```

## The Pipeline

```
HOUSE_GATE context (agent-declared)
       ↓
Cuddy Pre-Flight (subagent check + PRD auto-injection)
       ↓
Deterministic Pre-Scan (pattern matching, zero-cost)
       ↓
Cuddy — Differential Diagnosis (with auto-injected locked decisions)
       ↓
Specialists (tier floor enforced)
       ↓
House Verdict
```

**HOUSE_GATE** — Agents declare their environment before committing: are subagents running? What locked decisions apply? Minimum tier floor? This context feeds into every downstream check.

**Cuddy Pre-Flight** — Before any review, Cuddy checks for running opencode subagents (stale processes holding RAM, may have uncommitted changes). Also auto-discovers `CHARTER.md`, `PHASE*_PRD.md`, and `*_SPEC.md` in the repo root, extracts "Locked Decisions" sections, and injects them into Cuddy's differential diagnosis as ground truth — eliminating false positives from re-litigating approved design decisions.

**Tier Floor** — File patterns (`**/migrations/**` → standard, `**/trading_core/**` → adversarial) and risk score (≥ 4.0 → adversarial) auto-upgrade the review tier. No more accidentally running `--tier fast` on a database migration.

## The Review Board

| Reviewer | Role | Vibe |
|----------|------|------|
| **Dr. Lisa Cuddy** 🏛️ | Differential Diagnosis — runs FIRST | House's boss. Rules out simpler alternatives before anyone touches the code. If you didn't justify your approach, you're not getting past her. |
| **Dr. Eric Foreman** 🧠 | Backend, Infrastructure, Architecture | Skeptical. Experienced. Will find your N+1 query. |
| **Dr. Allison Cameron** 🎨 | Frontend, UX, Design, Accessibility | Cares about humans. Finds your missing loading state. |
| **Dr. Robert Chase** 🔒 | Security, DevOps, CI/CD, Automation | Finds your hardcoded credentials. Defaults to P1. |
| **Dr. Chris Taub** 🔌 | API Contracts, Data Schemas, Integration | Obsessed with consistency. Hates `200 OK` with error body. |
| **Dr. Remy "Thirteen" Hadley** 🧪 | Edge Cases, Performance, QA | Finds the bug that only reproduces at 3am under peak load. |
| **Dr. James Wilson** 🩻 | Appeal Judge | House's only friend. The one person who can tell House he's wrong — but he defaults to upholding House. P2-only appeals. P1s are sacred. Uses a **different provider** than the review board — genuine separation of powers. |

Cuddy runs FIRST. She is the gate before the gate. If a simpler approach exists and you didn't rule it out, the code is the wrong approach — regardless of code quality. Then every specialist must PASS for House to approve. One rejection = change rejected.

**P1 findings are absolute.** Not even Wilson can overturn them. Fix the code.
**P2 findings can be appealed** — but you have to convince Wilson, not House. See [Appeals](#appeals).

## Why six reviewers?

Most code review tools use one AI with a generic prompt. That's like diagnosing a patient by asking "what hurts?" and stopping there. House runs a differential — Cuddy rules out simpler alternatives, then five domain experts, five perspectives, one verdict.

- **One reviewer** doesn't ask "is this even necessary?"
- **One reviewer** misses domain-specific issues
- **One reviewer** doesn't catch security if it's not looking for security
- **One reviewer** says "LGTM" because it doesn't know what it doesn't know

Cuddy + five specialists who hate your code > one model who barely read it.

## Integration — Multi-Agent Workflows

House is designed to run anywhere in your development workflow — as a CLI, a pre-commit hook, a CI step, or a Claude Code skill. Each reviewer is an independent AI call with its own context. They don't talk to each other. They report to House.

**Chain of command:**

```
You (Human)
    └── Your AI coding agent — writes the code
            ├── HOUSE (GATEKEEPER) ← YOU ARE HERE
            │     ├── Dr. Cuddy — Differential diagnosis (approach validation)
            │     ├── Dr. Foreman — Backend / Infrastructure / Architecture
            │     ├── Dr. Cameron — Frontend / UX / Design
            │     ├── Dr. Chase — Automation / DevOps / Security
            │     ├── Dr. Taub — Data / API / Integration
            │     ├── Dr. Thirteen — QA / Edge Cases / Performance
            │     └── Dr. Wilson — Appeal Judge (P2 rejections only)
            └── Deploy — only AFTER House approval
```

**Ways to invoke House:**

```bash
# Standalone CLI — any terminal, any machine
everybody-lies --staged --tier standard
everybody-lies diagnose --staged             # House doesn't "review" — he diagnoses

# Pre-commit hook — blocks commits without House's signature
# .git/hooks/pre-commit
everybody-lies --staged --tier fast

# CI/CD pipeline — GitHub Actions, GitLab CI, anything
everybody-lies --diff "$(git diff origin/main...HEAD)" --ci github-actions

# Claude Code skill — /house from your coding agent
/house --tier adversarial

# With an AI coding agent loop — generate → review → fix → re-review
your-agent writes code → everybody-lies reviews it → agent fixes findings → re-review
```

Each call is stateless. House reads the diff, dispatches the review board, issues a verdict. Your agent, your CI pipeline, or your pre-commit hook decides what to do with it. House just tells you what's wrong.

**Auto-detection works across environments.** Your laptop might have `ANTHROPIC_API_KEY` (Claude Code). Your CI runner might have `DEEPSEEK_API_KEY` (cheaper). Your teammate might use `OPENROUTER_API_KEY`. House detects whatever is available and uses the best model for each reviewer. Same tool. Different keys. Same verdict.

## Tiers

| Tier | What happens | Approx. cost |
|------|-------------|-------------|
| `fast` | 1 model per specialist. Routine changes. | ~$0.02 |
| `standard` | 1 model per specialist. Normal PRs. | ~$0.15 |
| `adversarial` | 2 models cross-check per specialist. Critical changes. | ~$0.50 |

House will tell you if you picked the wrong tier. He won't be nice about it.

## HOUSE_GATE — Agent-Declared Context

HOUSE_GATE is an environment variable that lets AI coding agents declare their context before committing. Instead of the pre-commit hook guessing whether it's safe to commit, you tell it.

**Schema:**

```json
{
  "subagents_running": false,
  "locked_decisions": "React per PRD §5 — no jQuery. Use TypeScript strict mode.",
  "tier_floor": "standard"
}
```

**Three keys:**

| Key | Type | Behavior |
|-----|------|----------|
| `subagents_running` | `bool` | `true` → Cuddy blocks commit immediately. `false` → skip process scan (agent says it's clean). **Not set** → fall back to process scan. |
| `locked_decisions` | `str` | Injected into Cuddy's differential diagnosis as ground truth. Prevents her from re-litigating approved design decisions. Auto-detected from `CHARTER.md` / `PHASE*_PRD.md` if not provided. |
| `tier_floor` | `str` (`fast`/`standard`/`adversarial`) | Minimum review tier. If chart.json requires a higher tier via file patterns, the higher tier wins. Cannot *lower* the floor. |

**HOUSE_GATE is cached** after first parse — call it freely without re-reading `os.environ`.

**Interaction with HOUSE_BYPASS:** `HOUSE_BYPASS=1` still skips everything. But `bypass_protected: true` on a remote (pre-push) blocks even HOUSE_BYPASS.

**Usage from an agent:**

```bash
# Agent declares: no subagents running, React is locked, standard tier floor
HOUSE_GATE='{"subagents_running":false,"locked_decisions":"React per PRD §5","tier_floor":"standard"}' git commit -m "feat: add dashboard component"
```

## Tier Floors — Automatic Tier Upgrades

House won't let you run `--tier fast` on a database migration. Some files are too dangerous for budget-tier review. Tier floors auto-upgrade the review intensity based on file patterns and risk score.

**File pattern floors** (configured in `chart.json` → `tier_floors.file_patterns`):

| Pattern | Min Tier | Rationale |
|---------|----------|-----------|
| `**/migrations/**`, `**/migrate*.py` | `standard` | Schema changes need careful review |
| `**/auth/**` | `standard` | Auth bugs are security bugs |
| `**/trading_core/**`, `**/gs-rev-*/**` | `adversarial` | Financial code = adversarial by default |
| `**/.env*`, `**/secrets/**`, `**/*.pem`, `**/*.key` | `adversarial` | Secrets touching = adversarial |

**Risk score floors** (configured in `chart.json` → `tier_floors.risk_score_floors`):

| Risk Score | Min Tier |
|------------|----------|
| ≥ 4.0 | `adversarial` |
| ≥ 2.5 | `standard` |

**Override via HOUSE_GATE:** Setting `tier_floor` in HOUSE_GATE forces a minimum — but chart.json file patterns can still *raise* it further. You cannot lower the floor below what the config requires.

```bash
# Force adversarial even on a 2-line change
HOUSE_GATE='{"tier_floor":"adversarial"}' everybody-lies --staged --tier fast
# Prints: [HOUSE] Tier upgraded: fast -> adversarial (tier_floor from HOUSE_GATE)
```

**Console output:**

```
[HOUSE] Tier upgraded: fast -> standard (files: migrations/003_add_users.sql)
[HOUSE] Tier upgraded: standard -> adversarial (risk score: 4.2)
```

## Example — Real Execution

Here's a real `everybody-lies --tier fast` run against a commit that removed `job-tracker/` from `.gitignore` and started tracking a binary SQLite database:

```
$ everybody-lies --staged --tier fast

======================================================================
  HOUSE GATEKEEPER -- Code Review
======================================================================
  Change: Review of 2 file(s): .gitignore, job-tracker/backend/data/jobs.db
  Files:  2
  Risk:   1.0/5.0 -> recommended tier: fast
  Tier:   fast
  Type:   normal
======================================================================

  [CONFIG] Auto-detected: deepseek-v4-flash via DeepSeek Direct, Gemini Direct

  [SCAN] Deterministic pre-scan: 2 files, 8 lines (1.75ms)
         3 findings: P1=2 P2=0 P3=1 P4=0
         [P1] debug-true-production: .env:3
         [P1] hardcoded-api-key: config.py:12
         [P3] todo-fixme-unresolved: database.py:47

  [CUDDY — DIFFERENTIAL DIAGNOSIS] Dr. Lisa Cuddy (Dean of Medicine)
  Ruling out simpler alternatives before the specialists touch this...
  Model: deepseek-v4-flash
    -> 3444 chars received

  [THIRTEEN] Dr. Remy Hadley (Thirteen) — reviewing 2 file(s)
  Model: deepseek-v4-flash
    -> 2708 chars received

  [HOUSE] Synthesizing findings with deepseek-v4-flash...
    -> 3468 chars received

  [REPORT] ~/.everybody-lies/reviews/house-2026-05-30-cuddy-live-test.md
  [RECORD] ~/.everybody-lies/reviews/house-2026-05-30-cuddy-live-test.json

======================================================================
  [REJECTED] VERDICT: REJECTED
  BLOCKER: Cuddy: P1 — simpler alternative exists, approach is wrong
  BLOCKER: Dr. Remy Hadley (Thirteen): P2 — binary database in version control
  Fix the issues above and resubmit. P1 findings are not appealable.
  P2 findings: everybody-lies --appeal "your justification"
======================================================================
```

**What happened:**

1. **Deterministic scan** (1.75ms, free) caught `DEBUG=True` and a hardcoded API key before any AI was invoked
2. **Cuddy** reviewed the full diff and found three un-ruled-out simpler alternatives — the developer committed a binary `.db` file instead of generating it at build time. No justification. Approach rejected.
3. **Thirteen** backed her up — P2 finding on binary database bloat, merge conflicts, potential data leaks
4. **House** synthesized both, resolved the conflict (Cuddy and Thirteen agree — reject), issued REJECTED with Cuddy's approach-level P1 listed first

The deterministic scan caught the security issues in 1.75ms. Cuddy caught the approach failure. The specialist caught the operational risk. House delivered the verdict.

**Report excerpt — Cuddy's differential diagnosis:**

> ### Alternative 1: Track only the job-tracker source code, ignore the database file
> - **Ruled out?** NO. The developer removed `job-tracker/` from `.gitignore`, which will now track everything inside that directory—including `jobs.db`, a binary SQLite database file. There is zero justification for why a binary database should be version-controlled. Standard practice: keep `job-tracker/` in `.gitignore` entirely, or add `job-tracker/data/` or `*.db` to `.gitignore`.
> - **Better approach:** Add `job-tracker/backend/data/*.db` to `.gitignore` and track only the code. If the database is meant to be a seed, generate it during setup instead of committing a binary blob.
>
> **Verdict: FAIL P1.** The core change is poorly justified and introduces a binary artifact into version control. The simpler approach is to either ignore the database or keep the entire directory ignored.

**Report excerpt — House's synthesis:**

> Cuddy's job is to rule out simpler alternatives before you clowns start prettifying code. She found three simpler, un-ruled-out alternatives — all pointing to the same moronic decision: tracking a binary SQLite database file because you removed `job-tracker/` from `.gitignore` without any justification.
>
> No conflict between Cuddy and Thirteen. Both say reject.
>
> **REJECTED.** Fix the approach first. Come back when you've thought about it for more than 30 seconds. I'll be in my office, doing actual work.

## Quickstart

```bash
pip install everybody-lies
# or, from GitHub Releases:
pip install https://github.com/mfolofy/everybody-lies/releases/download/v0.2.0/everybody_lies-0.2.0-py3-none-any.whl
```

**If you're a Claude Code user:** Your `ANTHROPIC_API_KEY` is already in your environment. The tool auto-detects it. Zero configuration.

```bash
everybody-lies --staged --tier fast
```

**Everyone else:** Set at least one API key. The tool auto-detects whatever you have.

```bash
# Any one of these works. More = cheaper routing.
export ANTHROPIC_API_KEY="sk-ant-..."     # Claude Code users: already set
export DEEPSEEK_API_KEY="sk-..."          # Cheapest ($0.27/1M)
export GEMINI_API_KEY="..."               # Free tier available
export OPENROUTER_API_KEY="sk-or-..."     # Universal fallback
```

These are just the pre-configured providers. Any OpenAI-compatible endpoint works — Ollama, Azure, LiteLLM, your own server. See [Provider Support](#provider-support) for custom endpoints.

The tool detects whichever keys you've set and picks the best available model. Set one. Set all. It figures it out.

**No API keys?** Run with `--onboard` and House will walk you through setup. Or test with `--dry-run` to see what would happen without spending a cent.

```bash
everybody-lies --onboard    # Interactive setup wizard
everybody-lies --dry-run    # See the prompts without calling any LLMs
```

Then review away:

```bash
# Review staged changes
everybody-lies --staged --tier standard
everybody-lies diagnose --staged             # House doesn't "review" — he diagnoses

# Review everything
everybody-lies --tier fast

# Review a branch diff
everybody-lies --diff "$(git diff main...HEAD)" --tier adversarial

# Critical change? Full adversarial cross-examination
everybody-lies --staged --tier adversarial

# Just want to see the prompts? Dry run
everybody-lies --staged --tier standard --dry-run
```

## Pre-Commit Hook

```bash
# In your repo's .git/hooks/pre-commit:
#!/bin/bash
everybody-lies --staged --tier fast
```

Now nobody commits without House's signature. Including you. Especially you.

### What the pre-commit hook runs

The pre-commit hook runs a multi-stage pipeline:

1. **Cuddy Pre-Flight** — checks for running opencode subagents (process scan). Blocks the commit if any are found. Skipped if `HOUSE_BYPASS=1` or `HOUSE_GATE={"subagents_running":false}`.
2. **PRD Auto-Injection** — scans repo root for `CHARTER.md`, `PHASE*_PRD.md`, `*_SPEC.md`, extracts "Locked Decisions" sections, and feeds them into Cuddy as undisputed ground truth.
3. **Deterministic Pre-Scan** — pattern-based scan (1.75ms, zero AI cost) catches hardcoded credentials, debug-enabled, unresolved TODOs before any LLM is invoked.
4. **Cuddy Differential Diagnosis** — rules out simpler alternatives before specialists touch the code. Locked decisions from PRD injection prevent false positives.
5. **Specialists** — domain experts review through their respective lenses. Tier floor enforced.
6. **House Verdict** — synthesizes all findings, issues APPROVED or REJECTED.

### Using HOUSE_GATE with the pre-commit hook

When your AI agent commits, declare its context:

```bash
# Agent committing while subagents are running → BLOCKED
HOUSE_GATE='{"subagents_running":true}' git commit -m "fix: typo"

# Agent committing clean — skip process scan
HOUSE_GATE='{"subagents_running":false,"locked_decisions":"React per PRD §5","tier_floor":"standard"}' git commit -m "feat: add dashboard"
```

### Bypassing the pre-commit hook

```bash
HOUSE_BYPASS=1 git commit -m "hotfix: emergency deploy"
```

House logs every bypass to `~/.everybody-lies/reviews/house-commits.jsonl`. There's an audit trail.

## Pre-Push Scope Enforcement (Patient File)

The pre-push hook prevents pushing the wrong files to the wrong remote. It's the fix for the P0 class of incident where an agent pushes an entire monorepo into a clean external repo.

### How it works

Create `.house/patients.json` in your repo root:

```json
{
  "remotes": {
    "origin": {
      "allowed_paths": ["**"],
      "blocked_paths": ["secrets/**", "*.pem", ".env*", "*.key"],
      "force_push": "warn",
      "block_tags": false,
      "block_deletes": false,
      "bypass_protected": false
    },
    "external-repo": {
      "allowed_paths": ["external-repo/**"],
      "blocked_paths": ["secrets/**", "*.pem", ".env*"],
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

Install the hook:

```bash
cp docs/hooks/pre-push .git/hooks/pre-push
chmod +x .git/hooks/pre-push
```

### Rules

- **`blocked_paths` always wins** over `allowed_paths`
- **Unknown remotes block everything** — add an explicit entry to allow
- **`bypass_protected: true`** means `HOUSE_BYPASS=1` does **not** skip the check for that remote — the only way past is fixing the files
- **`force_push: "deny"`** blocks force pushes; `"warn"` allows with a warning
- **`block_tags: true`** blocks `git push --tags` and individual tag pushes
- **`block_deletes: true`** blocks `git push origin :branch`

### Schema reference

See `docs/patients.example.json` for a full annotated example.

## ITIL Compliance

Every review is an ITIL **Request for Change (RFC)**. Every finding is classified:

| Severity | Meaning | Action |
|----------|---------|--------|
| **P1** | Security vuln, data loss, production outage risk | Automatic rejection. No override. |
| **P2** | User-facing bug, performance regression | Rejected. Orchestrator may submit written justification. |
| **P3** | Code quality, technical debt | Should fix. Can defer with ticket. |
| **P4** | Style nit, docs gap | Nice to fix. Optional. |

All review reports are archived to `~/.everybody-lies/reviews/`. Permanent audit trail. House forgets nothing.

## Provider Support

House is **provider-agnostic.** Any model, any API, any endpoint. The tool ships with sensible defaults for common providers, but you are not tied to them. Point House at whatever serves your models.

**Built-in provider configurations** (zero setup — just set the env var):

| Provider | Example models | Auth |
|----------|---------------|------|
| **Anthropic Direct** | claude-sonnet-4-6, claude-opus-4-8, claude-haiku-4-5 | `ANTHROPIC_API_KEY` |
| **DeepSeek Direct** | deepseek-v4-flash, deepseek-v4-pro | `DEEPSEEK_API_KEY` |
| **Gemini Direct** | gemini-2.5-flash, gemini-2.5-pro, gemini-3.5-flash | `GEMINI_API_KEY` |
| **OpenRouter** | Everything (Claude, GPT-4, Gemini, DeepSeek, …) | `OPENROUTER_API_KEY` |

These are just the pre-configured ones. House tries direct APIs first (faster, cheaper), falls back to OpenRouter automatically (any model under the sun).

**Any OpenAI-compatible endpoint works.** Local Ollama. Azure. LiteLLM proxy. Your own model server. A cloud GPU you SSH into. House doesn't care who serves the model — he only cares what the model finds.

```bash
# Ollama running locally
export EVERYBODY_LIES_CUSTOM_BASE_URL="http://localhost:11434/v1"
export EVERYBODY_LIES_CUSTOM_API_KEY="ollama"

# Azure OpenAI deployment
export EVERYBODY_LIES_CUSTOM_BASE_URL="https://your-resource.openai.azure.com/openai/deployments/gpt-4o"
export EVERYBODY_LIES_CUSTOM_API_KEY="your-azure-key"

# LiteLLM proxy aggregating multiple providers
export EVERYBODY_LIES_CUSTOM_BASE_URL="http://localhost:4000/v1"
export EVERYBODY_LIES_CUSTOM_API_KEY="sk-litellm-..."
```

The provider registry lives in `everybody_lies/providers.py`. It's ~50 lines of configuration. Add yours. Submit a PR if it's broadly useful.

**Auto-detection** means you can set multiple keys and House picks the best model available. Claude Code users get Anthropic direct by default. CI pipelines might use DeepSeek for cost. Teammates might use OpenRouter. Same tool. Different keys. Same verdict.

If all providers fail, House tells you exactly why — and it's probably your fault.

## Configuration

House stores everything in `~/.everybody-lies/`:

```
~/.everybody-lies/
├── chart.json             # Your specialist config (from --onboard)
├── reviews/               # Review reports (RFC archive)
│   ├── house-2026-05-30-fix-auth-race.md
│   └── house-2026-05-30-fix-auth-race.json
├── stats.json             # Review statistics
└── dynamic_fellows.json   # Auto-hired domain specialists
```

Override the config directory:

```bash
export EVERYBODY_LIES_HOME=/path/to/config
```

## Dynamic Specialists

House auto-hires specialists for domains the static board doesn't cover. If your code touches trading, ML, blockchain, or databases — and no existing fellow covers that domain — House creates a specialist on the fly. If they produce nothing useful across 5 reviews, House fires them. It's a meritocracy. Unlike your last job.

## Appeals

House rejected your change. You think he's wrong. You can appeal — but only to Wilson, and only for P2 findings.

```bash
# Appeal a rejection with written justification
everybody-lies --appeal "The finding is inapplicable because X — the endpoint has no external clients and the schema change is intentional"

# Appeal a specific RFC by ID
everybody-lies --appeal "justification" --rfc RFC-2026-06-01-pre-commit-review-routes.py
```

**Wilson's rules:**
- **P1 findings are sacred.** Auto-denied. Not even Wilson can overturn a credential leak or SQL injection. Fix it.
- **P2 findings** can be appealed with written justification. Wilson evaluates the argument, not the code.
- Wilson uses a **different model and provider** than the review board — genuine separation of powers. He can't be House reviewing his own decision.
- Valid justifications: the finding is factually wrong, the fix is deferred with a named ticket and deadline, the behavior matches project conventions
- Invalid justifications: "I disagree," "it works," deadline pressure without a plan, vague promises

**Wilson's verdict options:**
- `APPEAL GRANTED` — House was wrong. Proceed without fixing.
- `APPEAL DENIED` — House was right. Fix it.
- `PARTIAL GRANT` — Some findings granted, some denied. Fix the denied ones.

All appeals are logged to `~/.everybody-lies/reviews/appeals.jsonl`. Permanent audit trail.

**Wilson requires an independent provider.** He won't use the same model family as the review board. If you only have DeepSeek configured, Wilson can't run (that's the review board's model — no separation of powers). Set `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, or `OPENROUTER_API_KEY` to unlock appeals.

## Key Bootstrap

House detects API keys from environment variables. If you're running House inside a CI pipeline, a git hook, or a multi-agent workflow where keys aren't in the environment, you have two options:

**Option 1 — JSON blob via env var** (hooks, wrappers, CI):
```bash
export EVERYBODY_LIES_API_KEYS='{"DEEPSEEK_API_KEY":"sk-...","GEMINI_API_KEY":"..."}'
everybody-lies --staged --tier fast
```

**Option 2 — Secrets file** (standalone CLI use):
```bash
# Create a flat JSON file with your keys
cat > ~/.my-keys.json << 'EOF'
{
  "DEEPSEEK_API_KEY": "sk-...",
  "GEMINI_API_KEY": "...",
  "ANTHROPIC_API_KEY": "sk-ant-...",
  "OPENROUTER_API_KEY": "sk-or-..."
}
EOF

# Point House at it
export EVERYBODY_LIES_SECRETS_FILE=~/.my-keys.json
everybody-lies --appeal "justification"
```

Both sources are loaded at import time and never overwrite keys already in the environment.

## Cleanup

Review artifacts accumulate. Clean them up:

```bash
# Remove review artifacts older than 30 days (default)
everybody-lies --cleanup

# Custom age threshold
everybody-lies --cleanup --cleanup-days 7

# Preview what would be deleted
everybody-lies --cleanup --cleanup-dry-run
```

## Operations / How-To

### Installing both hooks

```bash
# From your repo root — install pre-commit hook
cat > .git/hooks/pre-commit << 'EOF'
#!/bin/bash
everybody-lies --staged --tier fast
EOF
chmod +x .git/hooks/pre-commit

# Install pre-push hook (scope enforcement)
cp docs/hooks/pre-push .git/hooks/pre-push
chmod +x .git/hooks/pre-push
```

### Configuring patients.json for a new remote

1. Copy `docs/patients.example.json` to `.house/patients.json`
2. Add your remote under `remotes`:
   ```json
   "my-package-repo": {
     "allowed_paths": ["my-package/**"],
     "blocked_paths": ["secrets/**", "*.pem", ".env*"],
     "force_push": "deny",
     "block_tags": true,
     "block_deletes": true,
     "bypass_protected": false
   }
   ```
3. The `default` entry (unknown remotes) blocks everything — always add explicit entries

### Using HOUSE_GATE when committing from an agent

```bash
# Minimal: declare clean state
HOUSE_GATE='{"subagents_running":false}' git commit -m "fix: typo"

# Full: declare clean state + locked decisions + tier floor
HOUSE_GATE='{"subagents_running":false,"locked_decisions":"React per PRD §5. TypeScript strict. REST API only.","tier_floor":"standard"}' git commit -m "feat: user dashboard"
```

### How to bypass House in an emergency

| Situation | Bypass method | Audit trail |
|-----------|--------------|-------------|
| **Urgent hotfix** — can't wait for review | `HOUSE_BYPASS=1 git commit` | Logged to `house-commits.jsonl` as BYPASSED |
| **Pre-push blocking wrong files** — false positive | `HOUSE_BYPASS=1 git push` | Logged to `house-commits.jsonl` |
| **`bypass_protected: true` remote** — HOUSE_BYPASS won't work | Fix the files or update `patients.json` | Bypass blocked entirely — cannot skip |
| **Production incident** — need emergency deploy | `HOUSE_BYPASS=1 git push` (if remote allows it) | Full audit trail preserved |

**Warning:** `HOUSE_BYPASS` is logged permanently. Every bypass entry is visible in `~/.everybody-lies/reviews/house-commits.jsonl`. There is no "silent bypass."

### How to appeal a P2 finding (Wilson)

```bash
# Appeal the most recent rejection
everybody-lies --appeal "The finding is inapplicable — the schema change is intentional and no clients are affected"

# Appeal a specific RFC by ID
everybody-lies --appeal "justification" --rfc RFC-2026-06-01-pre-commit-review-routes.py
```

Wilson requires a **different provider** than the review board (separation of powers). Set `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, or `OPENROUTER_API_KEY` to enable appeals. Single-provider setups can't run Wilson.

### Fleet installation (updating all nodes)

```bash
# On each node in the fleet:
cd /path/to/everybody-lies
git pull --rebase origin main
pip install -e .

# Update hooks in your repos
cp docs/hooks/pre-push /path/to/repo/.git/hooks/pre-push
chmod +x /path/to/repo/.git/hooks/pre-push
```

Or use `git submodule update --remote` if everybody-lies is a git submodule.

## The Fine Print

- **Zero dependencies.** Standard library only. House doesn't need your npm nightmare.
- **Python 3.10+.**
- **MIT licensed.** House doesn't care about licenses. He cares about your code.
- **No telemetry.** House judges you silently. The cloud doesn't need to know.
- **Exit code 0** = APPROVED. **Exit code 1** = REJECTED. Your CI/CD pipeline knows what to do.

---

*"Everybody lies. Code especially. House just proves it faster."*

*"It's a basic truth of the human condition that everybody lies. The only variable is about what. Code is the same — the bug is always where you're not looking."*
