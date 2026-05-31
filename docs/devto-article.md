# How I Built a Multi-Agent AI Code Reviewer Using Only the Python Standard Library

**Six AI specialists. Zero dependencies. One verdict: fix it.**

---

Last month, I caught my AI coding agent committing a binary SQLite database to version control. It had removed `job-tracker/` from `.gitignore` — "to track the backend code" — and accidentally scooped up a 2MB binary blob along with it. No human reviewer would have let that through. No conventional linter would have caught it. And the AI that wrote the code certainly wasn't going to flag its own mistake.

I needed something that would ask the question no existing code review tool asks: *"Is this approach even correct in the first place?"*

So I built one. It's called **[everybody-lies](https://github.com/mfolofy/everybody-lies)**, named after a certain misanthropic diagnostician, and it works like this:

<p align="center">
  <img src="../demo.gif" alt="everybody-lies demo" width="720">
</p>

## The Problem With AI Code Review

Every AI code review tool on the market follows the same pattern: one model, one generic prompt, one verdict. It's the equivalent of diagnosing a patient by asking "what hurts?" and stopping there.

Here's what that misses:

- **Domain blindness.** A generalist reviewer doesn't know it's supposed to be looking for SQL injection in your database layer. It sees code. It doesn't see *database code*.
- **No approach validation.** Before reviewing whether your code is *well-written*, nobody asks whether your code is the *right approach*. Is there an existing library? A config change? A one-liner that would do the same thing?
- **False negatives.** Most tools bias toward approval because rejection means friction. They say "LGTM" because they don't know what they don't know.
- **Cost.** Running a frontier model on every commit is expensive. Running a cheap model on every commit produces noise.

The existing players — CodeRabbit, CodeScene, Korbit, Copilot code review — are all *useful*. But none of them does a differential diagnosis. None of them rules out simpler alternatives before checking your semicolons.

## The Architecture: A Differential Diagnosis for Your Codebase

The insight came from an episode of *House, M.D.* — specifically the scene where Cuddy tells House he can't order a brain biopsy without ruling out lupus first. She's not questioning his diagnostic skill. She's requiring him to prove his approach is correct *before* drilling into a patient's skull.

That's the architecture:

```
Intake → Cuddy (Approach Validation) → 5 Specialists → House (Final Verdict)
              ↑
    "Is there a simpler way? Did you rule out:
     - An existing library? A config change?
     - Code already in the repo?
     - A one-liner instead of 200 lines?"
```

**Six AI reviewers. Each with a domain-specific prompt. Each blind to the others. House only approves when all five specialists pass — and Cuddy must rule out simpler alternatives first.**

| Reviewer | Domain | What they catch |
|----------|--------|-----------------|
| Dr. Lisa Cuddy 🏛️ | Approach validation (runs FIRST) | Unnecessary complexity, missed libraries, wrong approach entirely |
| Dr. Eric Foreman 🧠 | Backend, Infrastructure, Architecture | N+1 queries, missing indexes, architectural violations |
| Dr. Allison Cameron 🎨 | Frontend, UX, Design, Accessibility | Missing loading states, broken keyboard nav, color contrast failures |
| Dr. Robert Chase 🔒 | Security, DevOps, CI/CD | Hardcoded credentials, exposed secrets, missing CSP headers |
| Dr. Chris Taub 🔌 | API Contracts, Data Schemas, Integration | `200 OK` with error body, broken pagination, inconsistent field names |
| Dr. Remy "Thirteen" Hadley 🧪 | Edge Cases, Performance, QA | Race conditions, memory leaks, the bug that only reproduces at 3am |

Each specialist sees only the files in their domain. The router inspects the diff, classifies each file by domain, and dispatches to the relevant specialists. If your commit touches only `src/auth/login.ts`, Chase reviews it. If it touches `tests/` and `api/`, Thirteen and Taub both weigh in. House gets the full diff and all specialist reports.

## Cuddy's Prompt: The Hardest Engineering Problem in the Pipeline

The five specialists are straightforward — give an expert a domain-specific lens and they'll find domain-specific issues. But Cuddy was the hard problem.

Cuddy's job is to validate the **approach** before anyone reviews the **implementation**. She's not checking for bugs. She's asking: *"Why is this code here at all?"*

The prompt had to do three things simultaneously:

1. **Force enumeration of alternatives.** Cuddy must explicitly list simpler approaches — using an existing library, a configuration change, code already in the repo, or a one-liner replacement. She can't just say "this is fine."

2. **Require justification per alternative.** For each simpler alternative, she must state whether it was ruled out and why. "Ruled out? No. The developer committed a binary `.db` file instead of generating it at build time." This prevents hand-wavy approvals.

3. **Fail closed.** If a simpler alternative exists and wasn't ruled out, the approach is wrong — regardless of code quality. Full stop. P1 rejection.

The key prompt engineering insight: **Cuddy doesn't know what the developer considered. She only knows what's in the diff.** So her prompt treats the diff as the entire defense. If the diff doesn't contain justification for the approach, the approach is unjustified by default.

Here's a real Cuddy finding from a commit that removed `job-tracker/` from `.gitignore`:

> **Alternative 1: Track only the job-tracker source code, ignore the database file**
> - **Ruled out?** NO. The developer removed `job-tracker/` from `.gitignore`, which will now track everything inside that directory—including `jobs.db`, a binary SQLite database file. There is zero justification for why a binary database should be version-controlled.
> - **Better approach:** Add `job-tracker/backend/data/*.db` to `.gitignore` and track only the code. If the database is meant to be a seed, generate it during setup instead of committing a binary blob.
>
> **Verdict: FAIL P1.** The core change is poorly justified and introduces a binary artifact into version control.

This is the kind of finding a linter will never give you. It's not a syntax error. It's not a security vulnerability. It's an *approach failure* — and it's the most common failure mode in AI-generated code.

## Zero Dependencies: The Hill I Chose to Die On

`everybody-lies` has zero third-party dependencies. Not `requests`. Not `httpx`. Not `click`. Python standard library only.

This wasn't ideological purity. It was pragmatism:

**1. Claude Code users are the primary audience.** Claude Code has `ANTHROPIC_API_KEY` already in its environment. The tool auto-detects it. Zero configuration. If I depended on `requests`, I'd need to vendor it or ask users to pip install in their Claude Code environment — both friction.

**2. The `pip install` is instant.** Nobody wants to wait 30 seconds for a code review tool to download its dependency tree. `everybody-lies` installs in under a second because there's nothing to download.

**3. No supply chain risk.** Every Python dependency is a potential attack vector. A pre-commit hook that runs before every commit shouldn't pull in 50 transitive dependencies from PyPI. The entire codebase fits in one directory and you can audit it in 20 minutes.

The stdlib covers everything we need:

| Need | Stdlib solution |
|------|----------------|
| HTTP requests | `urllib.request` with `json.loads(response.read())` |
| JSON parsing | `json.loads()` (stdlib since 2.6) |
| Argument parsing | `argparse` (every `--tier`, `--staged`, `--ci` flag) |
| File paths | `pathlib.Path` (cross-platform config dirs) |
| Config storage | `~/.everybody-lies/` — JSON files, no database needed |
| Subprocess calls | `subprocess.run` (for `git diff` capture) |

The only "dependency" is the LLM API itself — and that's just an HTTP POST with a JSON body. `urllib` handles it fine. The providers module is 200 lines of configuration; the actual API call is 30 lines.

```python
# The entire LLM call implementation, simplified:
def call_llm(prompt: str, model: str) -> str:
    provider = PROVIDERS[resolve_provider(model)]
    req = urllib.request.Request(
        provider["base_url"],
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {get_key(provider)}",
                 "Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())["choices"][0]["message"]["content"]
```

## Deterministic Scanning: Free and Instant

Before any AI is invoked, the scanner runs 25 regex-based patterns across the diff. It takes 1-6 milliseconds and costs nothing:

```
[SCAN] Deterministic pre-scan: 1 files, 15 lines (2.61ms)
       3 findings: P1=2 P2=0 P3=1 P4=0
       [P1] debug-true-production: src/config.py:3
       [P1] hardcoded-api-key: src/config.py:4
       [P3] todo-fixme-unresolved: src/config.py:8
```

These patterns catch the obvious stuff — hardcoded keys, debug mode in production, SQL injection patterns, missing error handling — before burning a single API token. They also provide line-level precision for CI annotations (GitHub Actions, GitLab Code Quality, SARIF).

If the scanner already found 3 P1s, the AI review still runs — but now it has a head start. The specialists can reference the scanner findings in their analysis.

## Dismissal Learning: The Feature Nobody Else Has

Here's the #1 failure mode of AI code review: **noise**. If every commit triggers a P3 finding about "consider adding a docstring," developers learn to ignore the tool. Within two weeks, it's background noise.

`everybody-lies` has a suppression system that learns from dismissals. When a reviewer dismisses a finding, it's recorded in `~/.everybody-lies/dismissals.json`:

```json
{
  "rule": "todo-fixme-unresolved",
  "file_pattern": "docs/*.md",
  "dismissals": 5,
  "last_dismissed": "2026-05-30T14:22:00Z"
}
```

After three dismissals of the same rule on the same file pattern, the tool suggests adding it to `suppress.toml`. Once suppressed, the rule is skipped for those files — permanently. No more "TODO in comments" findings in your documentation directory.

This also feeds into **cross-review problem detection**. If a P1 or P2 pattern appears in three or more reviews, it auto-creates an ITIL Problem Record — a permanent alert that something systemic is wrong:

```
[PROBLEM] ITIL Problem Record created: PROBLEM-hardcoded-api-key.json
  Pattern 'hardcoded-api-key' found in 5 of the last 10 reviews.
  This is not normal. Investigate: are developers copying example code?
  Are API keys in scaffolded templates? Are pre-commit hooks configured?
```

This is the difference between a code review *tool* and a code review *system*. The tool tells you what's wrong right now. The system tells you what keeps going wrong.

## ITIL Compliance: Because "Looks Good to Me" Isn't an Audit Trail

Every review is an ITIL **Request for Change (RFC)**. Every finding is classified by impact:

| Severity | Meaning | Action |
|----------|---------|--------|
| **P1** | Security vuln, data loss, production outage risk | Automatic rejection. No override. |
| **P2** | User-facing bug, performance regression | Rejected. Written justification required. |
| **P3** | Code quality, technical debt | Should fix. Can defer with ticket. |
| **P4** | Style nit, docs gap | Nice to fix. Optional. |

All review reports are archived to `~/.everybody-lies/reviews/` as both Markdown and structured JSON. Every specialist finding is timestamped, attributed to a model, and traceable. If you're in a regulated industry, this is your audit trail. If you're not, it's still useful when someone asks "who approved this?" six months later.

The RFC headers are machine-readable. Your CI pipeline can extract them:

```json
{
  "rfc_id": "RFC-2026-05-31-a1b2c3d4",
  "verdict": "REJECTED",
  "blockers": ["Cuddy: P1 — simpler alternative exists", "Chase: P2 — hardcoded API key"],
  "specialists_consulted": ["cuddy", "foreman", "chase", "thirteen"],
  "review_duration_ms": 28471,
  "tokens_consumed": 18453
}
```

## What It Costs

The tool auto-detects available API keys and picks the cheapest model that can do the job:

| Tier | Specialists | Approx. cost | When to use |
|------|-------------|-------------|-------------|
| `fast` | 1 model each | ~$0.02 | Routine changes, typo fixes |
| `standard` | 1 model each | ~$0.15 | Normal PRs, feature work |
| `adversarial` | 2 models cross-check per specialist | ~$0.50 | Critical changes, security-sensitive code |

At `fast` tier, a review costs less than the electricity your CI runner used while waiting for it. At `adversarial` tier, each specialist gets a second model cross-checking their findings — two independent reviews per domain before House synthesizes.

Compare to CodeRabbit ($12/user/month) or Korbit ($30/user/month). If you run 50 reviews a month at `standard` tier, you're paying $7.50. If you run 200 reviews a month, you're paying $30. And that $30 bought you 1,200 specialist reviews, not one.

## The House MD Theme: Why It Matters

I could have named this "Multi-Agent Code Review Pipeline" and precisely zero people would have read about it.

The House MD theme isn't cosmetic. It's a memory hook. Every developer who's seen the show understands the premise instantly: *Five specialists. One verdict. No appeals.* The differential diagnosis metaphor maps perfectly onto code review, and the cynical tone matches what developers actually think about AI-generated code.

The CLI alias is `diagnose` because House doesn't "review" code — he diagnoses it. The specialist config is `chart.json` because it's the patient's chart. The onboarding is an intake interview. These details don't affect the code, but they affect adoption. A tool with personality gets shared. A tool without it gets bookmarked and forgotten.

## What's Next

The package is MIT-licensed, zero-dependency, and pip-installable:

```bash
pip install everybody-lies
everybody-lies diagnose --staged --tier fast
```

It works as a CLI, a pre-commit hook, a CI step, or a Claude Code skill. It auto-detects your API keys — if you're using Claude Code, it works out of the box with zero configuration.

The repo is at [github.com/mfolofy/everybody-lies](https://github.com/mfolofy/everybody-lies). There's a v0.1.0 release with a pre-built wheel.

If you want to contribute: the specialist definitions in `chart.json` are designed to be extended. Want a Dr. Wilson for documentation? A Dr. Kutner for ML model code? Add them to the board and House will route to them automatically. The `dynamic_fellows.json` system even auto-hires specialists for domains the static board doesn't cover — and fires them if they don't produce useful findings across five reviews.

---

*"Everybody lies. Code especially. House just proves it faster."*

*— House (probably)*
