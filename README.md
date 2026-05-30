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

## Tiers

| Tier | What happens | Approx. cost |
|------|-------------|-------------|
| `fast` | 1 model per specialist. Routine changes. | ~$0.02 |
| `standard` | 1 model per specialist. Normal PRs. | ~$0.15 |
| `adversarial` | 2 models cross-check per specialist. Critical changes. | ~$0.50 |

House will tell you if you picked the wrong tier. He won't be nice about it.

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

| Provider | Models | Auth |
|----------|--------|------|
| **DeepSeek Direct** | deepseek-v4-flash, deepseek-reasoner | `DEEPSEEK_API_KEY` |
| **Gemini Direct** | gemini-2.5-flash, gemini-2.5-pro, gemini-3.5-flash | `GEMINI_API_KEY` |
| **OpenRouter** | Everything (Claude, GPT-4, Gemini, DeepSeek) | `OPENROUTER_API_KEY` |

Direct APIs are faster and cheaper. OpenRouter is the universal fallback. House tries direct first, falls back to OpenRouter automatically. If all providers fail, House tells you exactly why — and it's probably your fault.

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
