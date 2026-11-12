# everybody-lies — Known Bugs

## BUG-001: Cuddy contradictory rulings across review rounds

**Filed:** 2026-06-02  
**Severity:** High — causes infinite review loop on valid code  
**Symptom:** Cuddy (differential diagnosis) generates new P1/P2 findings on each round that contradict her prior rulings on the same diff.

**Observed sequence on `example_feature.py` feature:**
- Round 1: Rejected — "use shared constants (MIN_THRESHOLD), not separate ones"
- Round 2: Rejected — "separate constants are duplication, use shared ones" *(same finding, different framing)*
- Round 3: **PASS** — accepted iterative line-by-line parsing with docstring justification
- Round 4: Rejected — "iterative parsing is wrong, use regex" *(re-raised finding already accepted)*
- Round 5: Rejected — "use email stdlib for MIME parsing" *(already using it)*
- Round 6: Rejected — "don't use email stdlib, use payload.parts directly" *(contradicts round 5)*

**Root cause hypothesis:**  
Cuddy's prompt instructs her to find simpler alternatives without awareness of prior rounds. Each round she reads the diff fresh with no memory of previous verdicts. She re-discovers the same alternatives and flags them as un-ruled-out even when the docstring or commit message explicitly addresses them.

**Proposed fix:**  
1. Pass prior round review IDs / findings to Cuddy so she can see what was already addressed
2. Or: Cuddy should read the commit message for documented justifications before flagging alternatives
3. Or: add a "prior findings acknowledged" section to the review context

**Workaround:** Appeal to Wilson. Wilson has global context and correctly resolves contradictions. Two appeals on this diff both returned PARTIAL GRANT.

---

## BUG-002: Foreman raises P1 on gitignored secrets/audit-log paths

**Filed:** 2026-06-02  
**Severity:** Medium — generates false P1 blockers  
**Symptom:** Foreman flags `secrets/secrets.json` as a security P1 ("secrets stored in plaintext in repo") and `docs/reviews/house-commits.jsonl` as P2 ("audit log triggers feedback loop") on every commit involving House hook files.

**Why it's a false positive:**
- `secrets/` is in `.gitignore` (line: `secrets/`) — already established repo-wide pattern
- `docs/reviews/` is in `.gitignore` (line: `docs/reviews/`) — House artifacts are never tracked
- Neither file can be accidentally committed or trigger the pre-commit hook

**Root cause hypothesis:**  
Foreman's review prompt doesn't instruct him to verify `.gitignore` before raising security concerns about file paths. He sees `secrets/secrets.json` referenced in code and flags it without checking whether it's tracked.

**Proposed fix:**  
1. Add a `.gitignore` check to Foreman's prompt: "Before raising security concerns about file paths, verify whether the file is in `.gitignore`. If it is, note that and reduce severity accordingly."
2. Or: run a deterministic pre-scan step that checks gitignore status for referenced secret paths and suppresses known-gitignored findings.

**Workaround:** Appeal to Wilson with the gitignore evidence. Wilson grants when the evidence is clear.

---

## BUG-003: Wilson's appeal mechanism only shows pre-scan findings to Wilson

**Filed:** 2026-06-02  
**Severity:** High — Wilson can only rule on pre-scan P3s, not the actual specialist P1/P2 findings  
**Symptom:** When `--appeal` is invoked, Wilson receives the pre-scan finding list instead of the full specialist review. He rules on P3 `print-statement-production` findings while the actual blockers (P1/P2 from Foreman/Thirteen) are not in his context.

**Observed:** On hook files commit — Wilson said "I must base my decision on the provided Original House Review" which only contained the pre-scan. Wilson denied all print() findings (unrelated to the actual blockers) and exited 0 (partial grant).

**Root cause hypothesis:**  
The appeal path in `gatekeeper.py` passes a summary or the JSON record to Wilson, but the JSON record only has the pre-scan `deterministic_scan` field, not the full specialist responses.

**Proposed fix:**  
The `run_appeal` function should load the full review markdown (not just the JSON record) and pass it to Wilson so he can see all findings — including specialist P1/P2 — not just the pre-scan table.
