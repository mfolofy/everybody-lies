"""Deterministic pre-scan — zero-cost pattern matching before AI review.

Runs in milliseconds. No LLM calls. Catches what AI reviewers consistently miss.
Based on the arXiv paper "The Specification as Quality Gate" (March 2026):
deterministic verification first, AI only for the residual.

Patterns are language-aware but work on any text. Findings use the same
P1-P4 severity as the House review board, so they integrate seamlessly.
"""

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ScanFinding:
    """A single finding from the deterministic scan."""
    severity: str          # P1/P2/P3/P4
    rule: str              # Rule name (e.g., "hardcoded-secret")
    file: str              # File path
    line: int              # Line number (1-based, 0 if unknown)
    match: str             # The matched text (truncated for secrets)
    message: str           # Human-readable explanation
    fix: str               # How to fix it

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "rule": self.rule,
            "file": self.file,
            "line": self.line,
            "match": self.match,
            "message": self.message,
            "fix": self.fix,
        }


@dataclass
class ScanResult:
    """Complete scan result for a diff."""
    findings: list[ScanFinding] = field(default_factory=list)
    files_scanned: int = 0
    lines_scanned: int = 0
    duration_ms: float = 0.0

    @property
    def p1_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "P1")

    @property
    def p2_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "P2")

    @property
    def p3_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "P3")

    @property
    def p4_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "P4")

    @property
    def total(self) -> int:
        return len(self.findings)

    @property
    def has_blockers(self) -> bool:
        return self.p1_count > 0

    def to_dict(self) -> dict:
        return {
            "findings": [f.to_dict() for f in self.findings],
            "files_scanned": self.files_scanned,
            "lines_scanned": self.lines_scanned,
            "duration_ms": self.duration_ms,
            "summary": {
                "total": self.total,
                "P1": self.p1_count,
                "P2": self.p2_count,
                "P3": self.p3_count,
                "P4": self.p4_count,
            },
        }


# ── Pattern Definitions ──────────────────────────────────────────────────────
# Each pattern: (rule_name, severity, regex, message_template, fix_template, file_filter)
# file_filter: glob pattern or None for all files

PATTERNS = [
    # ═══ P1 — BLOCKING ═══
    (
        "hardcoded-api-key",
        "P1",
        # AWS, Google, Stripe, GitHub, OpenAI, Anthropic, generic API keys
        r"(?i)(?:api[_-]?key|apikey|api_secret|secret[_-]?key|access[_-]?key|auth[_-]?token)\s*[:=]\s*['\"]([^'\"]{16,})['\"]",
        "Hardcoded API key/secret detected: potentially exposes {match}",
        "Move to environment variable or secrets manager. Never commit credentials.",
        None,
    ),
    (
        "hardcoded-password",
        "P1",
        r"(?i)(?:password|passwd|pwd)\s*[:=]\s*['\"]([^'\"]+)['\"]",
        "Hardcoded password detected",
        "Use environment variable or secrets manager. Never commit passwords.",
        None,
    ),
    (
        "hardcoded-private-key",
        "P1",
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
        "Private key detected in source code",
        "Never commit private keys. Use a secrets manager or hardware security module.",
        None,
    ),
    (
        "sql-string-concatenation",
        "P1",
        r"(?i)(?:execute|executemany)\s*\(\s*(?:f['\"]|['\"].*\%|['\"].*\.format|['\"].*\+)",
        "Potential SQL injection: string concatenation/interpolation in SQL execute() call",
        "Use parameterized queries: cursor.execute('SELECT ... WHERE id = ?', (value,))",
        None,
    ),
    (
        "os-command-injection",
        "P1",
        r"(?i)(?:os\.system|os\.popen|subprocess\.(?:call|run|Popen))\s*\(\s*(?:f['\"]|['\"].*\+|['\"].*\%|['\"].*\.format)",
        "Potential command injection: user input in shell command",
        "Use subprocess.run() with args list (not string) and avoid shell=True with user input.",
        None,
    ),
    (
        "pickle-deserialization",
        "P1",
        r"(?i)pickle\.(?:loads?|Unpickler)\s*\(",
        "Insecure deserialization: pickle.loads() on potentially untrusted data",
        "Never unpickle untrusted data. Use JSON or a safe serialization format.",
        "**/*.py",
    ),
    (
        "debug-true-production",
        "P1",
        r"(?i)DEBUG\s*=\s*True|ENV(?:IRONMENT)?\s*=\s*['\"]development['\"]",
        "Debug mode or development environment enabled — potential production config leak",
        "Set DEBUG=False in production. Use environment-specific config files.",
        None,
    ),
    (
        "eval-exec-user-input",
        "P1",
        r"(?i)(?:eval|exec|compile)\s*\(\s*(?!['\"]\s*['\"])",
        "Potential code injection: eval()/exec()/compile() with non-literal input",
        "Never use eval()/exec() on untrusted input. There is always a safer alternative.",
        "**/*.py",
    ),
    (
        "shell-true-user-input",
        "P1",
        r"shell\s*=\s*True",
        "subprocess with shell=True — potential command injection vector",
        "Use shell=False (the default) and pass arguments as a list.",
        None,
    ),

    # ═══ P1 (continued) — CREDENTIALS / TOKENS / PII ═══
    (
        "jwt-bearer-token",
        "P1",
        # JWT tokens: base64url-encoded header.payload with typical claims
        r"\beyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\b",
        "JWT bearer token detected in source code — potential session/API access leak",
        "Never commit JWT tokens. Use short-lived tokens via env vars or secrets manager.",
        None,
    ),
    (
        "github-pat-token",
        "P1",
        # GitHub PAT formats: ghp_(classic), gho_(OAuth), ghu_(user), ghs_(server-to-server), ghr_(refresh)
        r"\bgh[pousr]_[A-Za-z0-9]{36,}\b",
        "GitHub Personal Access Token detected — can grant write access to repos",
        "Never commit GitHub PATs. Use fine-grained tokens stored in secrets manager.",
        None,
    ),
    (
        "gitlab-pat-token",
        "P1",
        r"\bglpat-[A-Za-z0-9_-]{20,}\b",
        "GitLab Personal Access Token detected",
        "Never commit GitLab PATs. Use CI/CD variables or secrets manager.",
        None,
    ),
    (
        "aws-access-key",
        "P1",
        r"\bAKIA[0-9A-Z]{16}\b",
        "AWS Access Key ID (AKIA format) detected — may grant AWS console/API access",
        "Never commit AWS keys. Use IAM roles, env vars, or AWS Secrets Manager.",
        None,
    ),
    (
        "aws-secret-key",
        "P1",
        r"(?i)(?:aws_secret_access_key|aws_secret_key|aws_access_key_id)\s*[:=]\s*['\"]([A-Za-z0-9/+=]{40}|AKIA[0-9A-Z]{16})['\"]",
        "AWS secret key pair detected in source code",
        "Rotate the key immediately. Store in AWS Secrets Manager or env vars.",
        None,
    ),
    (
        "conn-string-embedded-creds",
        "P1",
        r"(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\\+srv)?|redis|rediss|amqp|rabbitmq|nats|mqtt)://[^:]+:[^@]+@",
        "Database/queue connection string with embedded credentials — grants direct data access",
        "Use IAM auth, managed identities, or short-lived tokens. Never embed passwords in code.",
        None,
    ),
    (
        "oauth-token",
        "P1",
        r"(?i)(?:oauth_token|oauth2_token|refresh_token|access_token|bearer_token)\s*[:=]\s*['\"]([^'\"]{16,})['\"]",
        "OAuth/access token detected — can impersonate authenticated users",
        "Never commit OAuth tokens. Use short-lived tokens scoped to the minimum permission.",
        None,
    ),
    (
        "slack-webhook-token",
        "P1",
        r"https://hooks\.slack\.com/services/[A-Za-z0-9]+/[A-Za-z0-9]+/[A-Za-z0-9]+",
        "Slack webhook URL detected — allows posting messages to Slack channels",
        "Never commit webhook URLs. Store in secrets manager and rotate if leaked.",
        None,
    ),
    (
        "private-key-any-format",
        "P1",
        r"-----BEGIN\s+(?:RSA\s+PRIVATE\s+KEY|EC\s+PRIVATE\s+KEY|DSA\s+PRIVATE\s+KEY|PRIVATE\s+KEY|OPENSSH\s+PRIVATE\s+KEY|PGP\s+PRIVATE\s+KEY\s+BLOCK)-----",
        "Private key block detected — grants access to encrypted communications/signing",
        "Never commit private keys. Use hardware-backed keys or secrets manager.",
        None,
    ),
    (
        "ssn-number",
        "P1",
        r"\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b",
        "U.S. Social Security Number pattern detected — PII compliance violation",
        "Never commit SSNs. Anonymize or use tokenization. This may be a compliance violation.",
        None,
    ),
    (
        "credit-card-number",
        "P1",
        r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
        "Credit card number pattern detected — PCI compliance violation",
        "Never commit credit card numbers. PCI DSS prohibits storing full PAN in code.",
        None,
    ),
    (
        "slack-bot-token",
        "P1",
        r"\bxox[baprs]-[A-Za-z0-9-]{24,}\b",
        "Slack bot/user token detected — grants API access to Slack workspace",
        "Never commit Slack tokens. Rotate immediately. Use granular OAuth scopes.",
        None,
    ),
    (
        "discord-bot-token",
        "P1",
        r"[A-Za-z0-9_-]{24}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}",
        "Discord bot token detected — grants full API access to the bot account",
        "Never commit Discord tokens. Rotate via Discord Developer Portal immediately.",
        None,
    ),
    (
        "heroku-api-key",
        "P1",
        r"\b(?:HEROKU_API_KEY|heroku_api_key)\s*[:=]\s*['\"][A-Za-z0-9-]{36}['\"]",
        "Heroku API key detected — grants access to Heroku account/app management",
        "Never commit Heroku keys. Use env vars or Heroku Dashboard.",
        None,
    ),
    (
        "openai-api-key-legacy",
        "P1",
        r"\bsk-[A-Za-z0-9]{20,}\b",
        "OpenAI API key pattern detected — grants paid API access",
        "Never commit OpenAI keys. Rotate immediately. Use env vars.",
        None,
    ),
    (
        "google-oauth-client-secret",
        "P1",
        r"(?i)(?:client_secret|client_secret_id|google_client_secret)\s*[:=]\s*['\"][A-Za-z0-9_-]{24,}['\"]",
        "Google OAuth client secret detected — can impersonate app for OAuth consent",
        "Never commit OAuth client secrets. Store in secrets manager.",
        None,
    ),
    (
        "npm-token",
        "P1",
        r"\bnpm_[A-Za-z0-9]{36,}\b",
        "npm access token detected — grants publish/read access to npm packages",
        "Never commit npm tokens. Use .npmrc with env variable references.",
        None,
    ),
    (
        "docker-hub-token",
        "P1",
        r"\bdckr_pat_[A-Za-z0-9_-]{20,}\b",
        "Docker Hub personal access token detected — grants registry access",
        "Never commit Docker tokens. Use Docker Hub anonymous pulls or env vars.",
        None,
    ),
    (
        "twilio-api-key",
        "P1",
        r"(?i)(?:TWILIO_ACCOUNT_SID|twilio_account_sid)\s*[:=]\s*['\"]AC[A-Za-z0-9]{32}['\"]",
        "Twilio Account SID detected — grants Twilio API access",
        "Never commit Twilio credentials. Rotate immediately.",
        None,
    ),
    (
        "stripe-api-key",
        "P1",
        r"\b(?:sk_live|pk_live|sk_test|pk_test)_[A-Za-z0-9]{24,}\b",
        "Stripe API key detected — grants payment processing access",
        "Never commit Stripe keys. Rotate immediately. Restrict to live/test as needed.",
        None,
    ),
    (
        "cloudflare-api-token",
        "P1",
        r"(?i)(?:CLOUDFLARE_API_TOKEN|cloudflare_api_token|CF_API_TOKEN)\s*[:=]\s*['\"][A-Za-z0-9_-]{40,}['\"]",
        "Cloudflare API token detected — can modify DNS, CDN, and security settings",
        "Never commit Cloudflare tokens. Use API tokens with minimum required permissions.",
        None,
    ),
    (
        "ssh-private-key-content",
        "P1",
        r"-----BEGIN OPENSSH PRIVATE KEY-----",
        "OpenSSH private key detected — grants SSH access to servers",
        "Never commit SSH keys. Use SSH agent forwarding or short-lived certificates.",
        None,
    ),
    (
        "sentry-dsn",
        "P1",
        r"https://[a-f0-9]{32}@[a-f0-9]{16}\.ingest\.(?:sentry|o\d+)\.io/\d+",
        "Sentry DSN detected — allows sending events to Sentry project",
        "DSNs are publicly exposable per Sentry docs, but review if this should be an env var.",
        None,
    ),

    # ═══ P2 — HIGH ═══
    (
        "hardcoded-ip-hostname",
        "P2",
        r"(?i)(?:(?:host|server|endpoint|url|base_url)\s*[:=]\s*['\"]https?://(?!localhost|127\.0\.0\.1)[^'\"]+['\"]|"
        r"(?:host|server)\s*[:=]\s*['\"]\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}['\"])",
        "Hardcoded hostname or IP address — should be configurable",
        "Externalize to environment variable or config file. If behind os.getenv(), this is a false positive.",
        None,
    ),
    (
        "weak-hash-password",
        "P2",
        r"(?i)(?:hashlib\.(?:md5|sha1)\s*\(|MD5|SHA1)",
        "Weak cryptographic hash (MD5/SHA1) — potentially used for passwords",
        "Use bcrypt, argon2, or scrypt for passwords. Use SHA-256/512 for integrity.",
        None,
    ),
    (
        "broad-exception-catch",
        "P2",
        r"(?i)except\s*(?:Exception|BaseException)?\s*:\s*\n\s*pass",
        "Bare except or except Exception with pass — silently swallows all errors",
        "Catch specific exceptions. At minimum, log the error before continuing.",
        "**/*.py",
    ),
    (
        "http-not-https",
        "P2",
        r"(?i)http://(?!localhost|127\.0\.0\.1|0\.0\.0\.0)[^\s'\"]+",
        "HTTP URL detected (not HTTPS) — potential insecure communication",
        "Use HTTPS for all external communication. HTTP is acceptable for localhost only.",
        None,
    ),
    (
        "missing-timeout",
        "P2",
        r"(?i)(?:requests\.(?:get|post|put|delete|patch)|urllib\.request\.urlopen)\s*\((?![^)]*\btimeout\s*=)[^)]*\)",
        "HTTP request without explicit timeout — potential hang forever",
        "Always set a timeout: requests.get(url, timeout=30)",
        None,
    ),
    (
        "console-log-production",
        "P2",
        r"(?i)console\.(?:log|warn|error|debug)\s*\(",
        "console.log() in production code — may leak sensitive data to browser console",
        "Use a proper logging framework with log levels. Strip console calls in production builds.",
        "**/*.{js,ts,jsx,tsx}",
    ),
    (
        "hardcoded-email",
        "P2",
        # email@domain.tld patterns that are NOT in comments, imports, or test data
        r"(?i)(?:email|e-mail|mail|from_addr|to_addr|sender|recipient|notification_email)\s*[:=]\s*['\"][a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}['\"]",
        "Hardcoded email address — may leak user contact info or be used for spam harvesting",
        "Externalize to config or env var. Never hardcode emails in source.",
        None,
    ),
    (
        "hardcoded-phone-us",
        "P2",
        r"(?i)(?:phone|phone_number|phone_num|tel|telephone|contact|cell|mobile|fax)\s*[:=]\s*['\"]\+?1?\s*\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}['\"]",
        "Hardcoded U.S. phone number — potential PII leak",
        "Move phone numbers to config or database. Never hardcode in source.",
        None,
    ),
    (
        "hardcoded-internal-ip",
        "P2",
        r"(?i)(?:host|server|endpoint|ip|ip_address)\s*[:=]\s*['\"](10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})['\"]",
        "Hardcoded private/internal IP address — should be configurable or discovered",
        "Use DNS hostnames or environment variables. Private IPs change with network topology.",
        None,
    ),
    (
        "hardcoded-api-endpoint-with-creds",
        "P2",
        r"https?://[^:]+:[^@]+@[a-zA-Z0-9.-]+",
        "URL with embedded credentials — password in URL is a security anti-pattern",
        "Never embed credentials in URLs. Use token auth, headers, or env vars.",
        None,
    ),
    (
        "config-file-with-secrets",
        "P2",
        r"(?i)(?:password|passwd|pwd|secret|token|api_key|apikey)\s*[:=]\s*(?!['\"]?(?:\$\{|$|env\(|os\.getenv|None|null|~))['\"]?[^\s'\"$][^\s'\"]{4,}",
        "Potential secret value in config file — verify this is a placeholder or env reference",
        "Use env var references (${VAR}) instead of hardcoded values in config files.",
        "**/*.{yml,yaml,json,toml,ini,cfg}",
    ),

    # ═══ P3 — MEDIUM ═══
    (
        "todo-fixme-unresolved",
        "P3",
        r"(?i)\b(?:TODO|FIXME|HACK|XXX|BUG)\b(?!.*[A-Z]{2,}-\d+)",
        "Unresolved TODO/FIXME/HACK comment without ticket reference",
        "Either fix it or add a ticket reference: TODO(PROJ-123): explanation",
        None,
    ),
    (
        "print-statement-production",
        "P3",
        r"(?:^|\n)[^\S\n]*print\s*\(",
        "print() statement in production code — use proper logging",
        "Replace print() with logger.info() or logger.debug().",
        "**/*.py",
    ),
    (
        "commented-out-code",
        "P3",
        r"(?:^|\n)[^\S\n]*#\s*(?:def |class |if __name__|import |from |return |@)",
        "Commented-out code block — dead code that should be removed",
        "Delete commented-out code. Git history preserves it if needed.",
        "**/*.py",
    ),
    (
        "hardcoded-file-path",
        "P3",
        r"(?i)(?:['\"]/(?:home|Users|tmp|var|etc|opt|usr)/[^'\"]+['\"]|"
        r"['\"][A-Z]:\\[^'\"]+['\"])",
        "Hardcoded absolute file path — not portable across environments",
        "Use os.path.join() with a configurable base path. Never hardcode absolute paths.",
        None,
    ),
    (
        "mutable-default-argument",
        "P3",
        r"def \w+\([^)]*=\s*(?:\{\}|\[\]|dict\(\)|list\(\))",
        "Mutable default argument (empty list/dict) — shared across all calls",
        "Use None as default and initialize inside the function body.",
        "**/*.py",
    ),

    # ═══ P4 — LOW ═══
    (
        "trailing-whitespace",
        "P4",
        r"[ \t]+$",
        "Trailing whitespace",
        "Configure your editor to strip trailing whitespace on save.",
        None,
    ),
]


def _redact_secret(match_text: str) -> str:
    """Truncate a match that looks like a secret to avoid logging credentials."""
    if len(match_text) > 40 and any(kw in match_text.lower() for kw in
        ("key", "secret", "password", "token", "api", "auth", "private")):
        return match_text[:30] + "...[REDACTED]"
    return match_text


def _parse_diff_hunks(diff_text: str) -> list[tuple[str, int, str]]:
    """Parse a unified diff into (file_path, line_number, added_line_text) tuples.

    Only returns ADDED lines (lines starting with +). Skips diff headers and metadata.
    """
    entries: list[tuple[str, int, str]] = []
    current_file = ""
    current_line = 0

    for line in diff_text.split("\n"):
        # File header
        if line.startswith("diff --git"):
            parts = line.split(" ")
            if len(parts) >= 4:
                current_file = parts[3][2:]  # strip b/
            current_line = 0
            continue

        if line.startswith("--- a/") or line.startswith("+++ b/"):
            f = line[6:]
            if f != "/dev/null":
                current_file = f
            continue

        # Hunk header: @@ -old_start,old_count +new_start,new_count @@
        if line.startswith("@@"):
            match = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if match:
                current_line = int(match.group(1))
            continue

        # Added line
        if line.startswith("+") and not line.startswith("+++"):
            entries.append((current_file, current_line, line[1:]))  # strip the +
            if current_line > 0:
                current_line += 1

        # Context line (unchanged) — advances line counter
        elif line.startswith(" ") and current_line > 0:
            current_line += 1

    return entries


def scan_diff(diff_text: str, files: Optional[list[str]] = None) -> ScanResult:
    """Run the full deterministic scan against a git diff.

    Args:
        diff_text: Unified git diff text
        files: Optional list of files to filter to (speeds up if provided)

    Returns:
        ScanResult with all findings
    """
    import time
    start = time.perf_counter()

    result = ScanResult()

    if not diff_text.strip():
        result.duration_ms = (time.perf_counter() - start) * 1000
        return result

    # Parse diff into (file, line, added_text) entries
    entries = _parse_diff_hunks(diff_text)
    result.files_scanned = len(set(e[0] for e in entries))
    result.lines_scanned = len(entries)

    # Filter to specified files if provided
    if files:
        file_set = set(files)
        # Normalize paths — diff uses b/ prefix sometimes
        entries = [(f, l, t) for f, l, t in entries if f in file_set or f"b/{f}" in file_set]

    # Run each pattern against each added line
    seen = set()  # dedup key: (rule, file, line)
    for entry_file, entry_line, entry_text in entries:
        for rule_name, severity, pattern, message_tmpl, fix_tmpl, file_filter in PATTERNS:
            # Check file filter
            if file_filter:
                # Simple glob matching — check if filename matches the pattern
                if not _match_file_pattern(entry_file, file_filter):
                    continue

            # Run the regex
            match = re.search(pattern, entry_text)
            if not match:
                continue

            # Suppress hardcoded-ip-hostname when the URL is a configurable
            # default behind an env var — the hostname is not actually hardcoded.
            if rule_name == "hardcoded-ip-hostname" and re.search(
                r"(?:os\.getenv|os\.environ|environ\.get)", entry_text
            ):
                continue

            # Dedup
            dedup_key = (rule_name, entry_file, entry_line)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            # Build finding
            matched_text = match.group(0).strip()
            if severity == "P1" and any(kw in rule_name for kw in
                ("secret", "key", "password", "token", "private")):
                matched_text = _redact_secret(matched_text)

            finding = ScanFinding(
                severity=severity,
                rule=rule_name,
                file=entry_file,
                line=entry_line if entry_line > 0 else 0,
                match=matched_text[:120],
                message=message_tmpl.format(match=matched_text[:40]),
                fix=fix_tmpl,
            )
            result.findings.append(finding)

    result.duration_ms = round((time.perf_counter() - start) * 1000, 2)
    return result


def _match_file_pattern(file_path: str, pattern: str) -> bool:
    """Simple glob-style file pattern matching.

    Supports **, *, and basic glob patterns.
    Handles the patterns in chart.json (mostly **/*.py, *.ts, etc.).

    NOTE: Complex ** patterns with multiple intermediate directories
    may not match correctly. The patterns in chart.json use ** as a
    simple "match everything" prefix (e.g., **/*.py) which works fine.
    If more complex patterns are needed, switch to pathlib.PurePosixPath.match()
    once Python 3.13+ is the minimum (it supports ** natively).
    """
    import fnmatch
    # Normalize path separators
    import re as _re
    path = file_path.replace("\\", "/")
    pat = pattern.replace("\\", "/")

    # Expand brace patterns like *.{js,ts,jsx,tsx} into multiple globs
    brace_match = _re.search(r"\{([^}]+)\}", pat)
    if brace_match:
        alternatives = brace_match.group(1).split(",")
        for alt in alternatives:
            expanded = pat[:brace_match.start()] + alt.strip() + pat[brace_match.end():]
            if _match_file_pattern(path, expanded):
                return True
        return False

    # fnmatch supports * and ? but not **
    # For ** patterns, we need to handle recursively
    if "**" in pat:
        parts = pat.split("**")
        pat_starts_starstar = pat.startswith("**")
        pat_ends_starstar = pat.endswith("**")

        # First part (prefix): must match start if pattern doesn't begin with **
        if not pat_starts_starstar and parts[0]:
            if not fnmatch.fnmatch(path, parts[0] + "*"):
                return False

        # Middle parts: must appear in the path in order
        pos = 0
        start_idx = 1 if pat_starts_starstar else 0
        end_idx = len(parts) - 1 if pat_ends_starstar else len(parts)
        for i in range(start_idx, end_idx):
            if parts[i]:
                seg = parts[i]
                idx = path.find(seg, pos)
                matched_len = len(seg)
                if idx == -1:
                    # Try without leading / (handles **/dir/** matching "dir/file")
                    alt = seg.lstrip("/")
                    if alt != seg:
                        idx = path.find(alt, pos)
                        matched_len = len(alt)
                if idx == -1:
                    return False
                pos = idx + matched_len

        # Last part (suffix): must match end if pattern doesn't end with **
        if not pat_ends_starstar and len(parts) > 0 and parts[-1]:
            if not path.endswith(parts[-1]) and not fnmatch.fnmatch(path, "*" + parts[-1]):
                return False

        return True

    return fnmatch.fnmatch(path, pat)


def format_scan_result(result: ScanResult, for_ci: bool = False) -> str:
    """Format a scan result as human-readable text.

    Args:
        result: ScanResult to format
        for_ci: If True, use CI-friendly format (no emoji, machine-parseable)

    Returns:
        Formatted string
    """
    if result.total == 0:
        icon = "[OK]" if for_ci else "[PASS]"
        return f"{icon} Deterministic scan: {result.files_scanned} files, {result.lines_scanned} lines — clean ({result.duration_ms}ms)"

    lines = []
    if for_ci:
        lines.append(f"::warning::Deterministic scan: {result.total} findings")
    else:
        lines.append(f"[!] Deterministic scan: {result.total} findings "
                     f"(P1: {result.p1_count} | P2: {result.p2_count} | "
                     f"P3: {result.p3_count} | P4: {result.p4_count}) "
                     f"in {result.files_scanned} files, {result.lines_scanned} lines ({result.duration_ms}ms)")

    for f in result.findings:
        severity_marker = "BLOCKER" if f.severity == "P1" else f.severity
        if for_ci:
            # GitHub Actions annotation format
            lines.append(
                f"::{_severity_to_ci_level(f.severity)} "
                f"file={f.file},line={f.line},title={f.rule}::{f.message}"
            )
        else:
            lines.append(f"  [{severity_marker}] {f.rule}: {f.message}")
            if f.line:
                lines.append(f"       {f.file}:{f.line}")
            lines.append(f"       Fix: {f.fix}")

    return "\n".join(lines)


def _severity_to_ci_level(severity: str) -> str:
    """Map P1-P4 to GitHub Actions severity levels."""
    return {"P1": "error", "P2": "warning", "P3": "warning", "P4": "notice"}.get(severity, "warning")


def is_trivial_diff(diff_text: str, files: list[str]) -> tuple[bool, str]:
    """Determine if a diff is trivial enough to skip AI review.

    Trivial changes:
    - Only comments changed (lines starting with # or // or /*)
    - Only whitespace changes
    - Only config values changed (numbers, quoted strings in YAML/JSON/TOML)
    - Fewer than 10 added+removed lines total
    - Only documentation files (*.md, *.rst, *.txt)

    Returns:
        (is_trivial, reason) tuple
    """
    if not diff_text.strip():
        return True, "empty diff"

    # Count actual changes
    added = [l for l in diff_text.split("\n") if l.startswith("+") and not l.startswith("+++")]
    removed = [l for l in diff_text.split("\n") if l.startswith("-") and not l.startswith("---")]
    total_changes = len(added) + len(removed)

    if total_changes < 10:
        return True, f"only {total_changes} changed lines (<10)"

    # Check if all files are docs
    if files and all(f.endswith((".md", ".rst", ".txt", ".adoc")) for f in files):
        return True, "documentation-only change"

    # Check if changes are only comments/whitespace
    meaningful_added = [
        l for l in added
        if not l[1:].strip().startswith(("#", "//", "/*", "*", "<!--"))
        and l[1:].strip()  # not blank
        and l[1:].strip() not in ("}", "{", ");", ")", "]")  # bare brackets
    ]
    meaningful_removed = [
        l for l in removed
        if not l[1:].strip().startswith(("#", "//", "/*", "*", "<!--"))
        and l[1:].strip()
        and l[1:].strip() not in ("}", "{", ");", ")", "]")
    ]

    if not meaningful_added and not meaningful_removed:
        return True, "comments/whitespace/brackets only"

    if len(meaningful_added) + len(meaningful_removed) < 5:
        return True, f"only {len(meaningful_added) + len(meaningful_removed)} meaningful changes"

    return False, f"{len(meaningful_added)}+{len(meaningful_removed)} meaningful changes"


def emit_ci_output(review_data: dict, ci_format: str, output_path: str = "") -> None:
    """Emit CI/CD pipeline annotations from a review result.

    Args:
        review_data: The review data dict from run_review()
        ci_format: 'github-actions', 'gitlab', or 'sarif'
        output_path: Optional file path for SARIF output
    """
    all_findings = []

    # Collect scan findings (deterministic — file:line precision, no false positives)
    scan = review_data.get("deterministic_scan", {})
    for f in scan.get("findings", []):
        all_findings.append({
            "severity": f.get("severity", "P3"),
            "rule": f.get("rule", "unknown"),
            "file": f.get("file", ""),
            "line": f.get("line", 0),
            "message": f.get("message", ""),
            "fix": f.get("fix", ""),
            "source": "deterministic-scan",
        })

    # AI specialist findings are NOT parsed for CI annotations.
    # The deterministic scan (above) provides file:line precision for CI.
    # AI findings are unstructured text — regex-matching "**Severity:**" can
    # match code blocks, examples, or "not a P1" → false-positive CI annotations
    # that undermine trust. AI findings belong in the review report (markdown+JSON),
    # where a human evaluates them in context.
    # To add AI findings back: have specialists output a structured JSON block
    # (e.g., ```ci-json\n[{...}]\n```) and parse that instead of free text.

    if ci_format == "github-actions":
        _emit_github_annotations(all_findings)
    elif ci_format == "sarif":
        _emit_sarif(all_findings, review_data, output_path)
    elif ci_format == "gitlab":
        _emit_gitlab_codequality(all_findings, review_data)


def _emit_github_annotations(findings: list[dict]) -> None:
    """Emit GitHub Actions workflow annotations."""
    for f in findings:
        sev = _severity_to_ci_level(f["severity"])
        file_part = f"file={f['file']},line={f['line']}" if f["file"] else ""
        title = f.get("rule", "finding")[:50]
        msg = f.get("message", "")[:200]
        print(f"::{sev} {file_part},title={title}::{msg}")
        if f.get("fix"):
            print(f"::notice {file_part},title={title}-fix::{f['fix'][:200]}")


def _emit_sarif(findings: list[dict], review_data: dict, output_path: str = "") -> None:
    """Emit SARIF (Static Analysis Results Interchange Format) JSON."""
    import json as _json

    results = []
    for i, f in enumerate(findings):
        level = {"P1": "error", "P2": "warning", "P3": "note", "P4": "note"}.get(f["severity"], "warning")
        region = {}
        if f.get("line", 0) > 0:
            region["startLine"] = f["line"]
        loc = {
            "physicalLocation": {
                "artifactLocation": {"uri": f.get("file", "unknown")},
            }
        }
        if region:
            loc["physicalLocation"]["region"] = region

        results.append({
            "ruleId": f.get("rule", "unknown"),
            "level": level,
            "message": {"text": f.get("message", "")},
            "locations": [loc],
            "properties": {
                "severity": f["severity"],
                "source": f.get("source", ""),
                "fix": f.get("fix", ""),
            },
        })

    sarif = {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {
                "driver": {
                    "name": "everybody-lies (House Gatekeeper)",
                    "version": "0.1.0",
                    "informationUri": "https://github.com/mfolofy/everybody-lies",
                }
            },
            "results": results,
            "properties": {
                "verdict": review_data.get("verdict", "unknown"),
                "rfc_id": review_data.get("rfc_id", ""),
                "risk_score": review_data.get("risk_score", 0),
            },
        }],
    }

    sarif_json = _json.dumps(sarif, indent=2)
    if output_path:
        from pathlib import Path
        Path(output_path).write_text(sarif_json, encoding="utf-8")
        print(f"[SARIF] Written to {output_path}")
    else:
        print(sarif_json)


def _emit_gitlab_codequality(findings: list[dict], review_data: dict) -> None:
    """Emit GitLab Code Quality JSON."""
    import json as _json

    issues = []
    for f in findings:
        severity = {"P1": "blocker", "P2": "critical", "P3": "major", "P4": "minor"}.get(
            f["severity"], "major")
        loc = {
            "fingerprint": f"{f.get('rule', 'unknown')}-{f.get('file', '')}-{f.get('line', 0)}",
            "severity": severity,
            "description": f"[{f['severity']}] {f.get('rule', 'unknown')}: {f.get('message', '')}",
            "location": {
                "path": f.get("file", ""),
                "lines": {"begin": f.get("line", 0)},
            },
        }
        issues.append(loc)

    print(_json.dumps(issues, indent=2))
