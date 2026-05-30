# everybody-lies 💊

> *"To paraphrase Occam: the simplest explanation is your AI wrote shit code."*

**Code review tools ask nicely. House doesn't. Five specialists. One verdict. Fix it.**

---

## What is this?

A differential diagnosis for your codebase. Cuddy rules out simpler alternatives first. Then five domain specialists review every commit through their own lens. House issues the final verdict. Unanimous consent required. No bypass. No apologies. No "looks good to me."

Your AI wrote it. It's wrong. House proves exactly why.

```
$ everybody-lies --staged --tier fast
```

## The Pipeline

```
Intake → Cuddy (Differential Diagnosis) → Specialists → House (Verdict)
              ↑
    "Is there a simpler way? Did you rule out:
     - An existing library? A config change?
     - Code already in the repo?
     - A one-liner instead of 200 lines?
     No? Prove it. Then the specialists can have you."
```

## The Review Board

| Reviewer | Role | Vibe |
|----------|------|------|
| **Dr. Lisa Cuddy** 🏛️ | Differential Diagnosis — runs FIRST | House's boss. Rules out simpler alternatives before anyone touches the code. If you didn't justify your approach, you're not getting past her. |
| **Dr. Eric Foreman** 🧠 | Backend, Infrastructure, Architecture | Skeptical. Experienced. Will find your N+1 query. |
| **Dr. Allison Cameron** 🎨 | Frontend, UX, Design, Accessibility | Cares about humans. Finds your missing loading state. |
| **Dr. Robert Chase** 🔒 | Security, DevOps, CI/CD, Automation | Finds your hardcoded credentials. Defaults to P1. |
| **Dr. Chris Taub** 🔌 | API Contracts, Data Schemas, Integration | Obsessed with consistency. Hates `200 OK` with error body. |
| **Dr. Remy "Thirteen" Hadley** 🧪 | Edge Cases, Performance, QA | Finds the bug that only reproduces at 3am under peak load. |

Cuddy runs FIRST. She is the gate before the gate. If a simpler approach exists and you didn't rule it out, the code is the wrong approach — regardless of code quality. Then every specialist must PASS for House to approve. One rejection = change rejected. There is no appeal.

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
            │     └── Dr. Thirteen — QA / Edge Cases / Performance
            └── Deploy — only AFTER House approval
```

**Ways to invoke House:**

```bash
# Standalone CLI — any terminal, any machine
everybody-lies --staged --tier standard

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
  Fix the issues above and resubmit. There is no appeal.
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

House routes to whatever LLM providers you have. Set any API key — House detects it and uses the best available model.

| Provider | Example models | Auth |
|----------|---------------|------|
| **Anthropic Direct** | claude-sonnet-4-6, claude-opus-4-8, claude-haiku-4-5 | `ANTHROPIC_API_KEY` |
| **DeepSeek Direct** | deepseek-v4-flash, deepseek-reasoner | `DEEPSEEK_API_KEY` |
| **Gemini Direct** | gemini-2.5-flash, gemini-2.5-pro, gemini-3.5-flash | `GEMINI_API_KEY` |
| **OpenRouter** | Everything (Claude, GPT-4, Gemini, DeepSeek, …) | `OPENROUTER_API_KEY` |

Direct APIs are faster and cheaper. OpenRouter is the universal fallback — any model, any provider. House tries direct first for models he knows, falls back to OpenRouter automatically.

**This is not tied to specific providers.** The provider registry in `everybody_lies/providers.py` is a few lines of configuration. Any OpenAI-compatible endpoint works — point it at a local Ollama instance, an Azure deployment, a LiteLLM proxy, or your own model server. House doesn't care who serves the model. He only cares what the model finds.

```python
# Add a custom provider in ~/.everybody-lies/providers.json or via env:
# Any OpenAI-compatible chat/completions endpoint works.
export EVERYBODY_LIES_CUSTOM_BASE_URL="http://localhost:11434/v1"
export EVERYBODY_LIES_CUSTOM_API_KEY="ollama"
```

If all providers fail, House tells you exactly why — and it's probably your fault.

## Configuration

House stores everything in `~/.everybody-lies/`:

```
~/.everybody-lies/
├── review_board.json      # Your specialist config (from --onboard)
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

## The Fine Print

- **Zero dependencies.** Standard library only. House doesn't need your npm nightmare.
- **Python 3.10+.**
- **MIT licensed.** House doesn't care about licenses. He cares about your code.
- **No telemetry.** House judges you silently. The cloud doesn't need to know.
- **Exit code 0** = APPROVED. **Exit code 1** = REJECTED. Your CI/CD pipeline knows what to do.

---

*"Everybody lies. Code especially. House just proves it faster."*

*"It's a basic truth of the human condition that everybody lies. The only variable is about what. Code is the same — the bug is always where you're not looking."*
