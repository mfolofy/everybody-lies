"""Regression tests for scanner false positives.

Each test pins a known false positive so it stays fixed.
"""

import sys
import pytest

sys.path.insert(0, ".")


def _make_diff(file_path: str, added_lines: list[str]) -> str:
    """Build a minimal unified diff for testing."""
    lines = [
        f"diff --git a/{file_path} b/{file_path}",
        f"index abc..def 100644",
        f"--- a/{file_path}",
        f"+++ b/{file_path}",
        "@@ -1,0 +2 @@",
    ]
    for line in added_lines:
        lines.append(f"+{line}")
    return "\n".join(lines)


class TestGoogleFontsNotFlagged:
    """Google Fonts CDN URLs must NOT trigger hardcoded-api-endpoint-with-creds.

    The regex previously matched wght@400 (CSS font weight axis) as if it were
    user:password@host. Fixed by tightening the pattern to require a real
    hostname after the @ and exclude CSS numeric tokens.
    """

    def test_fonts_googleapis_wght_single(self):
        from everybody_lies.scanner import scan_diff
        diff = _make_diff(
            "infra/nexus/html/index.html",
            ['<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap" rel="stylesheet">'],
        )
        result = scan_diff(diff)
        cred_findings = [f for f in result.findings if f.rule == "hardcoded-api-endpoint-with-creds"]
        assert cred_findings == [], (
            f"Google Fonts URL falsely flagged as hardcoded-api-endpoint-with-creds: "
            f"{[f.match for f in cred_findings]}"
        )

    def test_fonts_googleapis_ital_wght_axis(self):
        from everybody_lies.scanner import scan_diff
        diff = _make_diff(
            "static/index.html",
            ['<link href="https://fonts.googleapis.com/css2?family=Roboto:ital,wght@0,400;1,700&display=swap">'],
        )
        result = scan_diff(diff)
        cred_findings = [f for f in result.findings if f.rule == "hardcoded-api-endpoint-with-creds"]
        assert cred_findings == [], (
            f"Google Fonts ital,wght axis URL falsely flagged: {[f.match for f in cred_findings]}"
        )

    def test_fonts_googleapis_variable_range(self):
        from everybody_lies.scanner import scan_diff
        diff = _make_diff(
            "frontend/public/index.html",
            ['<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300..700">'],
        )
        result = scan_diff(diff)
        cred_findings = [f for f in result.findings if f.rule == "hardcoded-api-endpoint-with-creds"]
        assert cred_findings == [], (
            f"Google Fonts variable range URL falsely flagged: {[f.match for f in cred_findings]}"
        )

    def test_fonts_gstatic_woff2(self):
        from everybody_lies.scanner import scan_diff
        diff = _make_diff(
            "infra/nexus/html/index.html",
            ['<link rel="preload" href="https://fonts.gstatic.com/s/inter/v13/woff2">'],
        )
        result = scan_diff(diff)
        cred_findings = [f for f in result.findings if f.rule == "hardcoded-api-endpoint-with-creds"]
        assert cred_findings == [], (
            f"fonts.gstatic.com URL falsely flagged: {[f.match for f in cred_findings]}"
        )

    def test_multiple_google_fonts_in_one_diff(self):
        """Full site rebuild with multiple font links — none should be flagged."""
        from everybody_lies.scanner import scan_diff
        diff = _make_diff(
            "infra/nexus/html/index.html",
            [
                '<link rel="preconnect" href="https://fonts.googleapis.com">',
                '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
                '<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300..700&family=Inter:wght@400;700&display=swap" rel="stylesheet">',
            ],
        )
        result = scan_diff(diff)
        cred_findings = [f for f in result.findings if f.rule == "hardcoded-api-endpoint-with-creds"]
        assert cred_findings == [], (
            f"Multiple Google Fonts links in a full site rebuild falsely flagged: "
            f"{[f.match for f in cred_findings]}"
        )


class TestRealCredentialUrlsStillFlagged:
    """True positives: real embedded-credential URLs must still be caught."""

    def test_basic_user_password_url(self):
        from everybody_lies.scanner import scan_diff
        diff = _make_diff(
            "config/settings.py",
            ['API_BASE = "https://user:s3cret_pass@api.example.com/v1"'],
        )
        result = scan_diff(diff)
        cred_findings = [f for f in result.findings if f.rule == "hardcoded-api-endpoint-with-creds"]
        assert cred_findings, "Real user:password@host URL was NOT flagged — regression"

    def test_api_key_in_url_host(self):
        from everybody_lies.scanner import scan_diff
        diff = _make_diff(
            "scripts/deploy.py",
            ['url = "https://myapikey:secrettoken@hooks.service.com/endpoint"'],
        )
        result = scan_diff(diff)
        cred_findings = [f for f in result.findings if f.rule == "hardcoded-api-endpoint-with-creds"]
        assert cred_findings, "API key in URL was NOT flagged — regression"
