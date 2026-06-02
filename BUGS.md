# everybody-lies — Known Bugs

## BUG-001: Cuddy contradictory rulings across review rounds

**Filed:** 2026-06-02  
**Severity:** High — causes infinite review loop on valid code  
**Symptom:** Cuddy (differential diagnosis) generates new P1/P2 findings on each round that contradict her prior rulings on the same diff.

**Observed sequence on `email_watch.py` ZipRecruiter feature:**
- Round 1: Rejected — "use shared constants (LI_SALARY_MIN), not separate ones"
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
