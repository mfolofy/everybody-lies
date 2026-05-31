# Social Posts — everybody-lies

## Show HN

**Title:** Show HN: everybody-lies — A differential diagnosis for your codebase

**Body:**

My AI coding agent recently committed a 2MB binary SQLite database to version control. It removed `job-tracker/` from `.gitignore` — "to track the backend code" — and scooped up `jobs.db` along with it. No linter caught it. No human reviewed it. The AI that wrote it didn't flag it.

I realized the problem: every code review tool checks whether your code is *well-written*. None of them check whether your code is the *right approach in the first place*.

So I built one that does both. It's called everybody-lies (named after a certain misanthropic diagnostician) and it runs six AI reviewers against every commit:

1. **Dr. Cuddy** — differential diagnosis: rules out simpler alternatives BEFORE anyone reviews code quality. Is there an existing library? A config change? Code already in the repo? If you can't justify your approach, you don't get past her.

2-5. **Four domain specialists** (backend, security, frontend, integration) — each reviews only the files in their domain. Foreman finds N+1 queries. Chase finds hardcoded keys. They don't talk to each other. They report to House.

6. **House** — synthesizes all findings, resolves conflicts, issues the final verdict. Unanimous consent required. One rejection = commit blocked.

Here's what makes it different from existing tools (CodeRabbit, Korbit, Copilot review):

- **Approach validation before code quality.** Cuddy runs first. If the approach is wrong, the code quality doesn't matter. No other tool does this.
- **ITIL-compliant audit trail.** Every review is an RFC with P1-P4 severity classification. All findings are archived as structured JSON. Permanent record.
- **Dismissal learning.** If the same rule gets dismissed 3+ times on the same file pattern, it auto-suggests suppression. The tool gets quieter over time — the opposite of every other linter.
- **Zero dependencies.** Python stdlib only. Installs in under a second. No supply chain risk. Provider-agnostic — works with Anthropic, DeepSeek, Gemini, OpenRouter, Ollama, anything OpenAI-compatible.

Cost: ~$0.02 per review at fast tier (one model per specialist), ~$0.50 at adversarial (two models cross-check). You can run it as a CLI, pre-commit hook, CI step, or Claude Code skill. Claude Code users get zero-config — it auto-detects your ANTHROPIC_API_KEY.

Repo: https://github.com/mfolofy/everybody-lies
Install: `pip install everybody-lies` then `everybody-lies diagnose --staged --tier fast`

MIT licensed. Would love feedback — especially on the specialist prompt design and the dismissal learning model. Happy to answer questions.

---

## r/Python

**Title:** I built a multi-agent AI code reviewer using only the Python standard library

**Body:**

No `requests`. No `httpx`. No `click`. Just `urllib`, `argparse`, `pathlib`, and `json`.

**everybody-lies** is a six-reviewer AI code review pipeline that runs as a CLI, pre-commit hook, or CI step. Five domain specialists + one differential diagnostician review every commit through domain-specific lenses, then a synthesizer issues the final verdict. Unanimous consent required.

**Architecture:**
```
git diff → Deterministic scanner (25 regex patterns, ~2ms, free)
        → Cuddy (approach validation — "is there a simpler way?")
        → 5 domain specialists (backend, security, frontend, API, QA)
        → Cross-review problem detection + dismissal learning
        → House (final verdict)
```

**Why stdlib-only?**
- Instant pip install (nothing to download)
- No supply chain risk in a pre-commit hook
- Claude Code compatibility — auto-detects ANTHROPIC_API_KEY, zero config
- The only IO is HTTP POST to an LLM API — `urllib` handles it in 30 lines

**Cool Python bits:**
- Provider-agnostic LLM routing with auto-detection of available API keys
- `argparse` with a "diagnose" positional alias (House doesn't "review" code, he diagnoses it)
- `pathlib` for cross-platform config dirs (`~/.everybody-lies/`)
- `fnmatch` for file-to-specialist domain routing
- Deterministic scanner using compiled regex patterns — catches hardcoded keys, SQL injection, debug mode in prod before any AI is called

Repo: https://github.com/mfolofy/everybody-lies
`pip install everybody-lies`

Curious what the r/Python community thinks about the zero-dependency approach. Was it worth the friction? At what point would you have caved and imported `requests`?

---

## r/LocalLLaMA

**Title:** everybody-lies — Provider-agnostic AI code review that works with Ollama, DeepSeek, Gemini, Anthropic, or anything OpenAI-compatible

**Body:**

Built a multi-agent code review tool that doesn't care what serves your models. Six AI reviewers (differential diagnosis + 5 domain specialists) review your commits. I wanted something that:

1. Auto-detects whatever API keys you have set — zero config
2. Works with local models via Ollama
3. Tries direct APIs first (cheaper, faster), falls back to OpenRouter automatically
4. Costs ~$0.02/review at fast tier (DeepSeek) vs $12-30/user/month for hosted tools

**Provider support:**
```bash
# Any of these work. More keys = smarter routing.
export DEEPSEEK_API_KEY="sk-..."       # $0.27/1M — cheapest
export ANTHROPIC_API_KEY="sk-ant-..."  # Claude Code users: already set
export GEMINI_API_KEY="..."            # Free tier available
export OPENROUTER_API_KEY="sk-or-..."  # Universal fallback

# Or go local:
export EVERYBODY_LIES_CUSTOM_BASE_URL="http://localhost:11434/v1"
export EVERYBODY_LIES_CUSTOM_API_KEY="ollama"
```

The tool ships with providers for Anthropic (non-OpenAI format — `x-api-key` header, `system` as top-level field), DeepSeek, Gemini, and OpenRouter. But any OpenAI-compatible endpoint works — LiteLLM, Azure, vLLM, text-generation-webui, your own server.

**How it routes models:**
- Claude Code users → Anthropic direct (auto-detected from `ANTHROPIC_API_KEY`)
- Budget users → DeepSeek direct ($0.27/1M input)
- Free tier → Gemini (free tier available)
- Local only → Ollama (set `EVERYBODY_LIES_CUSTOM_BASE_URL`)
- Everything else → OpenRouter (any model under the sun)

Each specialist gets a model assigned based on their domain. The model config lives in `chart.json` and is fully overridable.

Repo: https://github.com/mfolofy/everybody-lies
Install: `pip install everybody-lies` (stdlib only, no deps)

Would love feedback from the local LLM crowd — what models are you running locally that would work well for domain-specific code review? I'm thinking Gemma 3 27B for the specialists and something beefier for House's synthesis.

---

## Posting Strategy

| Platform | Best time | Notes |
|----------|-----------|-------|
| **Show HN** | Tue-Thu, 8-10am ET | Most important. Respond to every comment. Don't be defensive. |
| **r/Python** | Mon-Thu, 8am-12pm ET | Text post. Don't link-drop — use the post body. |
| **r/LocalLLaMA** | Any weekday | Link to repo is fine. Lead with local model compatibility. |
| **r/programming** | After Show HN | Cross-post if Show HN does well. Different title. |

**Order:** Show HN first → wait 1-2 hours → Reddit posts (staggered 30 min apart)

**Replying:** Answer every comment. The thread is the content. Don't argue — "interesting point, here's why we did it differently" wins over "you're wrong."
