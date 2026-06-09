# everybody-lies 💊

> *"To paraphrase Occam: the simplest explanation is your AI wrote shit code."*

**Code review tools ask nicely. House doesn't. Five specialists. One verdict. Fix it.**

**Three gates. Zero escapes.** Pre-commit quality review. Cuddy pre-flight subagent check. Pre-push scope enforcement.

<p align="center">
  <img src="demo.gif" alt="everybody-lies demo" width="720">
</p>

---

## Why This Exists

Your agents write code that passes tests and still drops indexes in prod. Pre-commit review catches the logic. Cuddy pre-flight blocks the commit when another agent is mid-edit with uncommitted changes. Pre-push scope enforcement stops the monorepo (secrets included) from landing on the wrong remote. HOUSE_GATE forces the agent to declare its actual intent so the rest of the system isn't guessing from a diff.

Because "it worked on my run" has already cost real data.

A differential diagnosis for your codebase. Cuddy rules out simpler alternatives first. Then five domain specialists review every commit through their own lens. House issues the final verdict. Unanimous consent required. P1 findings are absolute. P2 findings can be appealed to Wilson. No apologies. No "looks good to me."

Three built-in enforcement gates keep your repo clean: pre-commit quality review, Cuddy pre-flight, and pre-push scope enforcement. Agents declare context via `HOUSE_GATE`. Tier floors auto-upgrade review intensity for high-risk files.

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

See [HOUSE_GATE](#house_gate--agent-declared-context) for the single source of truth on that variable.

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

One reviewer doesn't ask "is this even necessary?", misses domain-specific issues, or catches security when it isn't looking for security. Cuddy + five specialists who hate your code > one model who barely read it.

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

(The pipeline diagram above is the single canonical description; the sections below reference it.)

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
| `**/financial/**`, `**/proprietary-*/**` | `adversarial` | Financial code = adversarial by default |
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

======================================================================
  [REJECTED] VERDICT: REJECTED
  BLOCKER: Cuddy: P1 — simpler alternative exists, approach is wrong
  BLOCKER: Dr. Remy Hadley (Thirteen): P2 — binary database in version control
  Fix the issues above and resubmit. P1 findings are not appealable.
  P2 findings: everybody-lies --appeal "your justification"
======================================================================
```

Cuddy caught a binary `.db` file committed to version control because someone removed `job-tracker/` from `.gitignore` with zero justification. The deterministic scan caught `DEBUG=True` and a hardcoded API key in 1.75ms before any AI was invoked. House's synthesis: *"Fix the approach first. Come back when you've thought about it for more than 30 seconds."*

## Quickstart

```bash
pip install everybody-lies
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

(The pipeline it actually runs is documented in The Pipeline section.)

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

---

Exit 0 = APPROVED. Exit 1 = REJECTED. House judges silently; the cloud doesn't need to know.

*"Everybody lies. Code especially. House just proves it faster."*