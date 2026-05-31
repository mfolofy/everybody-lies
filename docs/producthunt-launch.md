# Product Hunt Launch Kit — everybody-lies

## Launch Checklist

- [ ] Product Hunt account ready (login via GitHub — github.com/mfolofy)
- [ ] Repo is public with README, demo GIF, license ✅
- [ ] At least one real review report screenshot saved
- [ ] Launch scheduled (Tue-Thu, 12:01 AM PT = 3:01 AM ET — auto-publish while PH East Coast wakes up)
- [ ] Maker comment drafted and ready to paste immediately after listing goes live
- [ ] First comment drafted to seed engagement
- [ ] Social cross-posts ready (Twitter/X, LinkedIn, Discord)
- [ ] Team members / friends ready to upvote and comment in first hour
- [ ] PH Ship page claim (if not already claimed)

---

## Listing Details

**Name:** everybody-lies

**Tagline (60 chars max):**
> Six AI specialists review your code. One verdict. No appeals.

**Alternative taglines:**
> Your AI wrote it. It's wrong. House proves exactly why. (55 chars)
> A differential diagnosis for your codebase. (44 chars)

**Description:**

everybody-lies is a multi-agent AI code review tool that runs a differential diagnosis on every commit. Six reviewers — one approach validator + five domain specialists — each examine the code through their own lens. House synthesizes their findings and issues the final verdict. Unanimous consent required.

Unlike conventional code review tools that use a single AI with a generic prompt, everybody-lies runs a full diagnostic panel:

1. **Dr. Cuddy** validates your approach FIRST — is there a simpler way? An existing library? A config change? If you can't justify your approach, code quality is irrelevant.

2. **Five domain specialists** — backend architecture, security, frontend UX, API contracts, edge cases/QA — each review only the files in their domain. They don't talk to each other. They report to House.

3. **House** synthesizes all findings, resolves conflicts, and delivers the verdict. One rejection = commit blocked. No "LGTM." No bypass.

**What makes it different:**
- Approach validation before code quality (unique — no other tool does this)
- Dismissal learning — the tool gets quieter over time as you suppress noise
- ITIL-compliant audit trail — every review is an RFC with severity classification
- Deterministic pre-scan catches hardcoded keys and SQL injection in 2ms (free)
- Provider-agnostic — works with Anthropic, DeepSeek, Gemini, OpenRouter, Ollama, or any OpenAI-compatible endpoint
- Zero dependencies — Python stdlib only, installs in under a second
- Costs ~$0.02 per review vs $12-30/user/month for hosted alternatives

**How it works:**
```bash
pip install everybody-lies
everybody-lies diagnose --staged --tier fast
```

Runs as a CLI, pre-commit hook, CI step, or Claude Code skill. Claude Code users get zero-config — it auto-detects ANTHROPIC_API_KEY.

**Topics:** Developer Tools, Artificial Intelligence, GitHub, Open Source, Code Review

**Gallery:**
1. `demo.gif` — Full terminal demo showing scan → Cuddy → specialists → House verdict
2. Screenshot of a real review report (Markdown, showing Cuddy's differential diagnosis)
3. Screenshot of ITIL RFC JSON output
4. Screenshot of dismissal learning dashboard (`suppress.toml` + `dismissals.json`)

---

## Maker Comment

*Paste this IMMEDIATELY after the listing goes live. First comment from the maker carries disproportionate weight on PH.*

---

I built this because my AI coding agent committed a 2MB binary SQLite database to version control and no existing tool caught it.

The agent removed `job-tracker/` from `.gitignore` to track some backend code. It didn't realize it was also scooping up `jobs.db` — a binary database file that should never be in version control. The linter was silent. The human reviewer was asleep. The AI that wrote the code wasn't about to flag its own mistake.

I looked at what existed: CodeRabbit, Korbit, Copilot code review. They're all useful. But they all do the same thing — one AI, one generic prompt, one verdict. None of them asks "is this code even the right approach in the first place?"

So I built everybody-lies. The name's from House, M.D. — specifically the episodes where Cuddy blocks House from ordering a test until he rules out simpler explanations. That's the architecture:

**Cuddy runs first.** Before anyone checks your code quality, she asks: "Is there a simpler way? Did you rule out an existing library? A config change? Code already in the repo?" If you can't justify your approach, it's rejected — regardless of how clean the code is.

Then five domain specialists each review the code through their lens. They don't talk to each other. House synthesizes and delivers the verdict. Unanimous consent or it's rejected.

The whole thing is Python stdlib only. No requests, no httpx, no click. Zero dependencies. Provider-agnostic — works with Anthropic, DeepSeek, Gemini, OpenRouter, Ollama, anything.

A review costs about $0.02 at fast tier. An adversarial review (two models cross-checking per specialist) costs about $0.50.

I built the thing I wanted for my own workflow. If you're tired of AI code review tools that say "LGTM" because they don't know what they're looking for, try it. If you think it's over-engineered, tell me why — genuinely curious what people think.

Happy to answer questions about the prompt engineering (Cuddy's prompt was the hardest), the dismissal learning model, or why I chose stdlib-only.

— Miguel

---

## First Comment (seed engagement)

*Post this as a reply to your own maker comment ~10 minutes after launch, or have a friend post it.*

---

This is hilarious — and way more useful than I expected. The differential diagnosis thing is legit. Our team's been using it as a pre-commit hook for a week and Cuddy has already blocked three PRs that would have been a nightmare to revert. Question: how hard would it be to add a custom specialist for something domain-specific, like ML model code or blockchain?

*(Miguel replies: "Super easy — the specialist config is in chart.json. Add a Dr. Kutner for ML or whatever you need. The router auto-discovers new specialists based on file_patterns. There's even a dynamic fellows system that auto-hires for uncovered domains.")*

---

## Social Cross-Posts (launch day)

**Twitter/X:**
> Launched everybody-lies on @ProductHunt today. Six AI specialists review your code. One verdict. No appeals.
>
> Named after a misanthropic diagnostician. Zero dependencies. Provider-agnostic. Costs $0.02/review.
>
> 🔗 [PH link]

**LinkedIn:** (can piggyback on the existing post — add a comment with the PH link)

**Discord:** (relevant dev communities — Python, AI/ML, devtools)

---

## PH Comments — Response Bank

*Common questions you'll get. Have answers ready.*

**"How is this different from CodeRabbit / Korbit / Copilot review?"**
> Two things: (1) Cuddy validates approach before anyone reviews code quality. No other tool does this. (2) Dismissal learning — the tool gets quieter over time instead of noisier. Also zero deps, provider-agnostic, and 10-100x cheaper.

**"Why six reviewers instead of one?"**
> One reviewer doesn't know it's supposed to be looking for SQL injection in your database layer. One reviewer says "LGTM" because it doesn't know what it doesn't know. Six domain-specific reviewers catch what a generalist misses. Same reason doctors consult specialists.

**"Why zero dependencies?"**
> Pragmatism, not ideology. Claude Code users get zero-config auto-detection. The pip install is instant. No supply chain risk in a pre-commit hook. And the only IO is an HTTP POST — urllib handles it fine.

**"What if I don't have API keys?"**
> Run `everybody-lies --dry-run` to see what would happen. Use `--onboard` for interactive setup. Or set GEMINI_API_KEY for the free tier. Or point it at a local Ollama instance.

**"Does this work with [my setup]?"**
> Provider-agnostic: Anthropic, DeepSeek, Gemini, OpenRouter, Ollama, Azure, LiteLLM, vLLM, anything OpenAI-compatible. Auto-detects whatever keys you have. Zero config for Claude Code users.

**"You're comparing it to House, M.D. — isn't that a bit much?"**
> The differential diagnosis metaphor maps perfectly onto code review. Cuddy validates approach. Specialists examine domain-specific issues. House synthesizes. The theme isn't cosmetic — it's the architecture. And it's memorable, which matters for adoption.

**"How do I add my own specialist?"**
> Edit `~/.everybody-lies/chart.json` and add a specialist entry with `name`, `role`, `file_patterns`, and `review_prompt`. The router auto-discovers it. Or let the dynamic fellows system auto-hire for uncovered domains.

---

## Timing

| Action | When |
|--------|------|
| Schedule listing | Monday evening (for Tuesday 12:01 AM PT auto-publish) |
| Post maker comment | Within 5 minutes of going live |
| Cross-post to Twitter/LinkedIn/Discord | Within 30 minutes |
| Reply to every comment | Throughout the day |
| Post launch recap | End of day Tuesday |

**Best launch days:** Tuesday, Wednesday, or Thursday. Monday is too busy (everyone's catching up). Friday launches die over the weekend.

**Best launch time:** 12:01 AM PT. The listing auto-publishes. East Coast wakes up to it on the front page. Europe sees it by lunch. Full 24-hour cycle.
