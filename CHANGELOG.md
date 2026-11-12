# Changelog

All notable changes to everybody-lies will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.1] - 2026-11-12

### Fixed
- Subprocess output decoded as UTF-8 (`errors="replace"`): Windows cp1252 no longer crashes on git diffs with non-ASCII text.
- DeepSeek model ids corrected to the served ones (`deepseek-flash`, `deepseek-v4-pro`); `deepseek-v4-flash` returned empty responses.
- DeepSeek is routed to the DeepSeek API only, never through OpenRouter.

### Added
- Key bootstrap source 3: an untracked `secrets/house-api-keys.json` found by walking up from the working directory. Tracked copies are ignored.

### Removed
- The trading-domain dynamic specialist.

## [0.3.0] - 2026-06-05

### Added
- **HOUSE_GATE** env var: agents declare `subagents_running`, `locked_decisions`, `tier_floor` before committing. Cached after first parse. Injected into Cuddy prompt and tier calculation.
- **Tier floor enforcement**: file patterns (`**/migrations/**`, `**/auth/**`, `**/financial/**`, `**/secrets/**`) and risk score (≥ 4.0 → adversarial, ≥ 2.5 → standard) auto-upgrade minimum review tier. Configurable in `chart.json` → `tier_floors`.
- **Cuddy PRD auto-injection**: auto-detects `CHARTER.md`, `PHASE*_PRD.md`, `*_SPEC.md` near repo root. Extracts "Locked Decisions" / "Non-negotiable" / "Phase X decisions" sections. Injects into Cuddy system prompt as ground truth. Eliminates false positives from re-litigating approved design decisions.
- **Patient file pre-push scope enforcement**: `.house/patients.json` declares per-remote file scope (`allowed_paths`, `blocked_paths` globs). `force_push`, `block_tags`, `block_deletes` policies. Unknown remotes blocked by default. Precedence: `blocked_paths` always wins.
- `docs/hooks/pre-push`: install script with Python/package availability guards. Falls back gracefully when python isn't available.
- `docs/patients.example.json`: annotated config template with comments.
- **`bypass_protected` flag**: when `true` on a remote, `HOUSE_BYPASS=1` does **not** skip the pre-push scope check. Only way past is fixing the files.
- **`HOUSE_GATE.subagents_running`**: `true` → Cuddy blocks commit immediately. `false` → skip process scan. Not set → fall back to process scan with psutil fallback.
- **`HOUSE_GATE.locked_decisions`**: string injected into Cuddy's differential diagnosis as ground truth, overriding auto-detection.
- **`HOUSE_GATE.tier_floor`**: minimum tier floor. Config file patterns can still raise it further, but it can never lower below what config requires.

### Changed
- Cuddy pre-flight subagent check now respects `HOUSE_GATE.subagents_running` declaration
- Tier calculation now prints upgrade reason: `[HOUSE] Tier upgraded: fast -> standard (files: migrations/003.sql)`
- Pre-commit hook now runs 3-gate pipeline: Cuddy pre-flight → pre-scan → Cuddy differential → specialists → House verdict

## [0.2.1] - 2026-06-05

### Added
- **Cuddy pre-flight subagent check**: blocks commits when opencode subagents are running (process scan with psutil, tasklist/pgrep fallback on POSIX). Ancestor exclusion prevents the caller's own session from being flagged. HOUSE_BYPASS skips.

### Fixed
- Prior review rounds now archived to `~/.everybody-lies/reviews/archive/` instead of deleted — preserves full history for debugging Cuddy contradiction loops (BUG-001)

## [0.2.0] - 2026-05-30

### Added
- Initial release: Cuddy differential diagnosis, 5 domain specialists (Foreman, Cameron, Chase, Taub, Thirteen), House verdict synthesis
- Wilson appeal judge (P2-only, different provider required for separation of powers)
- Provider auto-detection: Anthropic, DeepSeek, Gemini, OpenRouter, custom OpenAI-compatible endpoints
- Deterministic pre-scan (pattern-based, zero AI cost)
- Three tiers: fast, standard, adversarial
- Dynamic specialist system: auto-hire/fire for uncovered domains
- Dry-run mode, cleanup, ITIL RFC compliance
- Pre-commit hook integration
- Key bootstrap via `EVERYBODY_LIES_API_KEYS` env var or secrets file

[0.3.1]: https://github.com/mfolofy/everybody-lies/releases/tag/v0.3.1
[0.3.0]: https://github.com/mfolofy/everybody-lies/releases/tag/v0.3.0
[0.2.1]: https://github.com/mfolofy/everybody-lies/releases/tag/v0.2.1
[0.2.0]: https://github.com/mfolofy/everybody-lies/releases/tag/v0.2.0
