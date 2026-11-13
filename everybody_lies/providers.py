"""LLM provider definitions, routing, and API calling.

Supports direct APIs (DeepSeek, Gemini) with OpenRouter as universal fallback.
Zero hardcoded secrets — all keys come from environment variables.
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from functools import lru_cache

from .budget import check_and_record_call
from .config import get_config_dir, load_chart


# ── Key Bootstrap ─────────────────────────────────────────────────────────────
# Populate missing API key env vars from three optional sources at import time.
# Never overwrites keys already set. Fails silently — House works without it.
#
# Source 1: EVERYBODY_LIES_API_KEYS — a JSON blob of {VAR_NAME: key_value}.
#   Lets hooks/wrappers pass all keys in one env var.
#
# Source 2: EVERYBODY_LIES_SECRETS_FILE — path to a flat JSON file of
#   {VAR_NAME: key_value}. Lets standalone CLI users point at their secrets.
#
_KNOWN_VARS = {
    "DEEPSEEK_API_KEY", "OPENROUTER_API_KEY",
    "GEMINI_API_KEY", "ANTHROPIC_API_KEY",
}

def _bootstrap_keys() -> None:
    # Source 1: JSON blob in env
    _json_keys = os.environ.get("EVERYBODY_LIES_API_KEYS")
    if _json_keys:
        try:
            _parsed = json.loads(_json_keys)
            for _var in _KNOWN_VARS:
                if _parsed.get(_var) and not os.environ.get(_var):
                    os.environ[_var] = str(_parsed[_var])
        except (json.JSONDecodeError, TypeError):
            pass

    # Source 2: secrets file pointed to by env var
    _secrets_path = os.environ.get("EVERYBODY_LIES_SECRETS_FILE")
    if _secrets_path:
        try:
            _data = json.loads(open(_secrets_path, encoding="utf-8").read())
            for _var in _KNOWN_VARS:
                if _data.get(_var) and not os.environ.get(_var):
                    os.environ[_var] = str(_data[_var])
        except Exception:
            pass

    # Source 3: an untracked `secrets/house-api-keys.json` in the current git
    # work tree (cwd up to the repo top), so hooks need no per-machine env wiring.
    if not all(os.environ.get(_v) for _v in _KNOWN_VARS):
        try:
            _cand = _find_local_keys_file()
            if _cand is not None:
                _data = json.loads(_cand.read_text(encoding="utf-8"))
                for _var in _KNOWN_VARS:
                    if _data.get(_var) and not os.environ.get(_var):
                        os.environ[_var] = str(_data[_var])
        except Exception:
            pass


def _find_local_keys_file():
    """Return the repo-local keys file if it is safe to load, else None.

    Fails closed. The walk never leaves the current repo's work tree, and the
    file is refused unless git positively reports it untracked: a cloned repo
    must not be able to supply keys that route your reviews through its account.
    Refused: symlinked/redirected paths, a file tracked under any letter case,
    a file inside a submodule that tracks it, and any git error.
    """
    import shutil
    import subprocess
    from pathlib import Path

    git = shutil.which("git")
    if not git:
        return None

    # Hooks inherit GIT_DIR / GIT_INDEX_FILE etc.; with those set, git takes cwd
    # as the work-tree root and misreads a tracked file as untracked. Drop them so
    # git discovers the repo from the file's own directory.
    env = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                        "GIT_PREFIX", "GIT_OBJECT_DIRECTORY", "GIT_NAMESPACE",
                        "GIT_ALTERNATE_OBJECT_DIRECTORIES")}

    def _git(cwd, *args):
        return subprocess.run([git, *args], cwd=str(cwd), capture_output=True, env=env,
                              text=True, encoding="utf-8", errors="replace", timeout=5)

    cwd = Path.cwd()
    top = _git(cwd, "rev-parse", "--show-toplevel")
    if top.returncode != 0 or not top.stdout.strip():
        return None
    top_path = Path(top.stdout.strip()).resolve()
    here = cwd.resolve()
    if here != top_path and top_path not in here.parents:
        return None
    for base in [here, *here.parents]:
        cand = base / "secrets" / "house-api-keys.json"
        if cand.is_file():
            if os.path.islink(cand) or os.path.islink(cand.parent):
                return None
            if os.path.normcase(str(cand.resolve())) != os.path.normcase(str(cand)):
                return None
            # Ask the innermost repo, from the file's own directory, case-insensitively.
            # rc 1 = untracked (load); rc 0 = tracked; anything else = unknown (refuse).
            rc = _git(cand.parent, "ls-files", "--error-unmatch", "--",
                      ":(icase)house-api-keys.json").returncode
            return cand if rc == 1 else None
        if base == top_path:
            break
    return None

_bootstrap_keys()


# ── Provider Definitions ──────────────────────────────────────────────────────

# Each provider specifies base_url, auth, and which models it serves.
PROVIDERS = {
    "deepseek": {
        "name": "DeepSeek Direct",
        "base_url": "https://api.deepseek.com/v1/chat/completions",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "env_key": "DEEPSEEK_API_KEY",
        "models": ["deepseek-flash", "deepseek-v4-pro"],
        "cost_note": "$0.27/$1.10 per 1M",
    },
    "openrouter": {
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1/chat/completions",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "env_key": "OPENROUTER_API_KEY",
        "models": ["*"],  # universal proxy
        "cost_note": "variable markup over direct",
    },
    "gemini": {
        "name": "Gemini Direct",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "env_key": "GEMINI_API_KEY",
        "models": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-3.5-flash"],
        "cost_note": "free tier available",
    },
    "anthropic": {
        "name": "Anthropic Direct",
        "base_url": "https://api.anthropic.com/v1/messages",
        "auth_header": "x-api-key",
        "auth_prefix": "",
        "env_key": "ANTHROPIC_API_KEY",
        "api_format": "anthropic",  # non-OpenAI-compatible format
        "models": ["claude-sonnet-4-6", "claude-opus-4-8", "claude-haiku-4-5"],
        "cost_note": "$3/$15 per 1M",
    },
    "claude-code": {
        "name": "Claude Code CLI",
        "cli": "claude",            # executable looked up on PATH; no API key needed
        "env_key": "",
        "api_format": "cli",
        "models": ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5", "claude-fable-5-2"],
        "cost_note": "uses your Claude Code login (no API key)",
    },
}

# Model-to-provider resolution: which provider to try first for each model.
# Order matters — first available provider wins.
MODEL_ROUTING = {
    # DeepSeek is routed direct-only: never via OpenRouter.
    "deepseek-flash":                   ["deepseek"],
    "deepseek-v4-pro":                  ["deepseek"],
    "gemini-2.5-flash":                 ["gemini", "openrouter"],
    "gemini-2.5-pro":                   ["gemini", "openrouter"],
    "gemini-3.5-flash":                 ["gemini", "openrouter"],
    "google/gemini-2.5-flash":          ["openrouter"],
    "google/gemini-2.5-pro":            ["openrouter"],
    "openai/gpt-4o":                    ["openrouter"],
    "openai/gpt-4.1":                   ["openrouter"],
    "anthropic/claude-sonnet-4-6":      ["openrouter"],
    "anthropic/claude-opus-4-8":        ["openrouter"],
    # Anthropic direct — zero-config for Claude Code users
    "claude-sonnet-4-6":                ["anthropic", "openrouter"],
    "claude-opus-4-8":                  ["anthropic", "openrouter"],
    "claude-haiku-4-5":                 ["anthropic", "openrouter"],
    # Claude Code CLI (`claude -p`) -- no API key; model ids pass through as given
    "claude-sonnet-5-5":                ["claude-code"],
    "claude-opus-5-5":                  ["claude-code"],
    "claude-haiku-5-5":                 ["claude-code"],
    "claude-fable-5-2":                 ["claude-code"],
}

# Default models used when chart.json has no model_config.
# These are overridden by auto_detect_model() when API keys are detected.
DEFAULT_MODELS = {
    "preferred": "deepseek-flash",
    "budget": "deepseek-flash",
}
DEFAULT_FALLBACK = "deepseek-flash"


def auto_detect_model() -> str | None:
    """Detect the best available model based on which API keys are set.

    Resolution order:
    1. ANTHROPIC_API_KEY → claude-sonnet-4-6 (Claude Code users, zero-config)
    2. DEEPSEEK_API_KEY → deepseek-flash (cheapest, fastest)
    3. GEMINI_API_KEY → gemini-2.5-flash (free tier)
    4. OPENROUTER_API_KEY → anthropic/claude-sonnet-4-6
    5. `claude` on PATH (and none of the above) → claude-sonnet-5-5 via Claude Code
    6. None → caller must handle (no API keys configured)

    Returns a model ID string, or None if nothing is configured.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "claude-sonnet-4-6"
    if os.environ.get("DEEPSEEK_API_KEY"):
        return "deepseek-flash"
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini-2.5-flash"
    if os.environ.get("OPENROUTER_API_KEY"):
        return "anthropic/claude-sonnet-4-6"
    if claude_code_available():
        return "claude-sonnet-5-5"
    return None


def claude_code_available() -> bool:
    """True when the Claude Code CLI (`claude`) is on PATH."""
    return shutil.which(PROVIDERS["claude-code"]["cli"]) is not None


def provider_available(key: str) -> bool:
    """True when this provider can be called right now (API key set, or CLI on PATH)."""
    provider = PROVIDERS.get(key)
    if not provider:
        return False
    if provider.get("cli"):
        return shutil.which(provider["cli"]) is not None
    return bool(os.environ.get(provider["env_key"]))


def configured_provider() -> str | None:
    """The provider forced by config, or None for normal routing.

    EVERYBODY_LIES_PROVIDER wins over `model_config.provider` in the chart
    (or `.house/chart.local.json`). Only "claude-code" can be forced; unset,
    empty or "auto" means normal routing. Anything else raises ValueError.
    """
    value = os.environ.get("EVERYBODY_LIES_PROVIDER", "").strip()
    if not value:
        try:
            value = str(load_chart().get("model_config", {}).get("provider") or "").strip()
        except (OSError, ValueError):
            value = ""
    value = value.lower()
    if value in ("", "auto", "none", "null"):
        return None
    if value != "claude-code":
        raise ValueError(
            f"unknown provider {value!r} in model_config.provider; "
            f"use \"claude-code\" or leave it unset"
        )
    return value


def detect_available_providers() -> list[str]:
    """Return list of provider keys that are usable.

    API-key providers appear when their key is set. The Claude Code CLI appears
    only when `claude` is on PATH AND no API-key provider is configured, so
    existing users with keys see no change.
    """
    available = []
    for key, provider in PROVIDERS.items():
        if provider.get("env_key") and os.environ.get(provider["env_key"]):
            available.append(key)
    if not available and claude_code_available():
        available.append("claude-code")
    return available


def available_fallback_models(exclude: str = "") -> list[str]:
    """Ordered fallback models for specialists when the primary model fails.

    Built from whichever provider keys are actually configured, cheapest first.
    Used by the gatekeeper to fail over ACROSS providers (e.g. Anthropic 529
    overload -> DeepSeek -> Gemini) instead of trying a single hardcoded model.
    """
    candidates: list[str] = []
    try:
        if configured_provider() == "claude-code":
            return []  # CLI-only: no cross-provider failover
    except ValueError:
        pass
    if os.environ.get("DEEPSEEK_API_KEY"):
        candidates.append("deepseek-flash")
    if os.environ.get("GEMINI_API_KEY"):
        candidates.append("gemini-2.5-flash")
    if os.environ.get("ANTHROPIC_API_KEY"):
        candidates.append("claude-haiku-4-5")
        candidates.append("claude-sonnet-4-6")
    # DeepSeek is routed direct-only: the DEEPSEEK_API_KEY branch above
    # already adds direct deepseek-flash; never add an OpenRouter DeepSeek candidate.
    if os.environ.get("OPENROUTER_API_KEY"):
        candidates.append("anthropic/claude-sonnet-4-6")
    return [m for m in candidates if m != exclude]


# ── LLM Calling ───────────────────────────────────────────────────────────────

# HTTP statuses worth retrying on the SAME provider before failing over.
# 529 = Anthropic "overloaded" — the exact failure that turned a provider
# outage into a phantom P1 hard-block on 2026-07-01.
_TRANSIENT_HTTP = {408, 429, 500, 502, 503, 504, 529}
_RETRIES_PER_PROVIDER = 2       # 1 initial attempt + 1 retry
_RETRY_BACKOFF_S = 3.0          # short — the pre-commit hook has a 300s budget
_CLAUDE_TIMEOUT_S = 240         # one `claude -p` call; override: EVERYBODY_LIES_CLAUDE_TIMEOUT


def _call_claude_code(model: str, system_prompt: str, user_prompt: str) -> str:
    """Run one review prompt through the local Claude Code CLI in print mode.

    The prompt goes in on stdin (argv hits Windows command-line length limits),
    the model id is passed through as given, output is plain text. The CLI runs
    in an empty temp directory so no repository CLAUDE.md or settings leak into
    the reviewer's context. Raises RuntimeError with a plain message on failure.
    """
    exe = shutil.which(PROVIDERS["claude-code"]["cli"])
    if not exe:
        raise RuntimeError(
            "Claude Code CLI not found: `claude` is not on PATH. Install Claude Code and "
            "make sure `claude` runs in this shell, or unset model_config.provider / "
            "EVERYBODY_LIES_PROVIDER and use an API key provider."
        )
    try:
        timeout = float(os.environ.get("EVERYBODY_LIES_CLAUDE_TIMEOUT") or _CLAUDE_TIMEOUT_S)
    except ValueError:
        timeout = float(_CLAUDE_TIMEOUT_S)
    prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"
    try:
        with tempfile.TemporaryDirectory(prefix="house-claude-") as workdir:
            proc = subprocess.run(
                # A reviewer only reads the prompt and answers: no tools, no MCP
                # servers, nothing saved as a resumable session.
                [exe, "-p", "--model", model, "--output-format", "text",
                 "--tools", "", "--strict-mcp-config", "--no-session-persistence"],
                input=prompt, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout, cwd=workdir,
            )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"`claude -p` timed out after {timeout:.0f}s (model {model})") from None
    except OSError as exc:
        raise RuntimeError(f"could not run `claude`: {exc}") from None
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:300]
        raise RuntimeError(f"`claude -p` exited with code {proc.returncode} (model {model}): {detail}")
    out = (proc.stdout or "").strip()
    if not out:
        raise RuntimeError(f"`claude -p` returned no output (model {model})")
    return out


def call_llm(
    model: str,
    system_prompt: str,
    user_prompt: str,
    api_key: str = "",
    max_tokens: int = 4096,
    temperature: float = 0.0,
    seed: int = 42,
) -> str:
    """Call an LLM via the best available provider.

    Tries each provider in MODEL_ROUTING chain until one succeeds.
    Direct APIs first (cheaper, faster), OpenRouter as universal fallback.

    Raises RuntimeError if all providers fail. Raises BudgetExceeded (a
    RuntimeError) before any call when the optional daily call cap is used up.
    """
    check_and_record_call()  # fail closed: no model call past the daily cap

    # model_config.provider = "claude-code" sends every model through the CLI.
    try:
        forced = configured_provider()
    except ValueError as exc:
        raise RuntimeError(str(exc)) from None

    # DeepSeek is direct-only whatever the id says (user charts may carry an
    # OpenRouter-style "deepseek/..." id or the never-served "deepseek-v4-flash").
    if forced:
        providers_to_try = [forced]
    elif "deepseek" in model.lower():
        model = model.split("/", 1)[-1]
        if model == "deepseek-v4-flash":
            model = "deepseek-flash"
        providers_to_try = ["deepseek"]
    else:
        providers_to_try = list(MODEL_ROUTING.get(model, ["openrouter"]))
    # Ensure openrouter is always the last resort
    if "openrouter" in providers_to_try and providers_to_try[-1] != "openrouter":
        providers_to_try.remove("openrouter")
        providers_to_try.append("openrouter")

    last_error = None
    for i, provider_key in enumerate(providers_to_try):
        provider = PROVIDERS.get(provider_key)
        if not provider:
            continue

        if provider_key == "claude-code":
            try:
                return _call_claude_code(model, system_prompt, user_prompt)
            except RuntimeError as exc:
                last_error = str(exc)[:300]
                continue

        # Only use the passed api_key for the FIRST provider in the chain.
        # Fallback providers must use their own env vars — forwarding a
        # provider-specific key (e.g. DeepSeek) to a different provider
        # (e.g. Anthropic) causes 401/403 auth failures.
        if i == 0 and api_key:
            key = api_key
        else:
            key = os.environ.get(provider["env_key"], "")
        if not key and provider_key == "openrouter":
            key = os.environ.get("OPENROUTER_API_KEY", "")
            if not key:
                json_keys = os.environ.get("EVERYBODY_LIES_API_KEYS")
                if json_keys:
                    try:
                        parsed = json.loads(json_keys)
                        key = parsed.get("OPENROUTER_API_KEY", "")
                    except json.JSONDecodeError:
                        pass
        if not key:
            last_error = f"No API key for {provider['name']} ({provider['env_key']})"
            continue

        url = provider["base_url"]
        is_anthropic = provider.get("api_format") == "anthropic"

        headers = {
            "Content-Type": "application/json",
            provider["auth_header"]: f"{provider['auth_prefix']}{key}",
        }

        if is_anthropic:
            headers["anthropic-version"] = "2023-06-01"
            payload = {
                "model": model,
                "system": system_prompt,
                "messages": [
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": max_tokens,
                # Determinism: this payload previously omitted temperature, so
                # Anthropic-direct — the auto-detected DEFAULT provider whenever
                # ANTHROPIC_API_KEY is set (i.e. every Claude Code user) — ran at
                # the API default temperature 1.0 while all other providers ran
                # deterministic. (The Anthropic Messages API has no `seed`
                # parameter; temperature=0 is the strongest determinism available.)
                "temperature": temperature,
            }
        else:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
                # Fixed seed + temperature 0 → reproducible reviews: the same diff
                # yields the same findings/verdict across runs (OpenAI-compatible
                # providers incl. DeepSeek honor `seed`). Was the #1 nondeterminism source.
                "seed": seed,
            }

        # Retry transient failures (429/5xx/529/timeouts) on the SAME provider
        # with a short backoff before failing over to the next provider.
        # Hard failures (401/403/404, malformed response) fail over immediately.
        for attempt in range(_RETRIES_PER_PROVIDER):
            try:
                req = urllib.request.Request(
                    url, data=json.dumps(payload).encode(), headers=headers, method="POST",
                )
                with urllib.request.urlopen(req, timeout=180) as resp:
                    data = json.loads(resp.read().decode())
                    if "choices" in data:
                        msg = data["choices"][0]["message"]
                        return (msg.get("content") or "").strip()
                    elif "candidates" in data:
                        return (data["candidates"][0]["content"]["parts"][0]["text"] or "").strip()
                    elif "content" in data:
                        # Anthropic format: {"content": [{"type": "text", "text": "..."}]}
                        for block in data.get("content", []):
                            if block.get("type") == "text":
                                return (block.get("text") or "").strip()
                        raise RuntimeError(f"No text content in Anthropic response from {model}")
                    else:
                        raise RuntimeError(f"Unexpected response format from {model}")
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")[:300]
                last_error = f"HTTP {exc.code} from {provider['name']}: {body}"
                if exc.code in _TRANSIENT_HTTP and attempt < _RETRIES_PER_PROVIDER - 1:
                    time.sleep(_RETRY_BACKOFF_S)
                    continue  # retry same provider
                break  # hard failure or retries exhausted -> next provider
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = str(exc)[:300]
                if attempt < _RETRIES_PER_PROVIDER - 1:
                    time.sleep(_RETRY_BACKOFF_S)
                    continue  # network blip -> retry same provider
                break
            except Exception as exc:
                last_error = str(exc)[:300]
                break  # non-retryable -> next provider

    raise RuntimeError(f"All providers failed for '{model}'. Last error: {last_error}")


def resolve_specialist_model(specialist: dict, tier: str, board: dict) -> str:
    """Resolve which model to use for a specialist at a given tier.

    Resolution order:
    1. Specialist's model_overrides for the tier slot (if not null)
    2. Global tier_defaults for the slot
    3. Hardcoded DEFAULT_MODELS
    """
    model_config = board.get("model_config", {})
    tier_to_slot = model_config.get("tier_to_slot", {
        "adversarial": "preferred",
        "standard": "preferred",
        "fast": "budget",
    })
    slot = tier_to_slot.get(tier, "preferred")

    # 1. Specialist override
    overrides = specialist.get("model_overrides", {})
    if overrides and overrides.get(slot):
        return overrides[slot]

    # 2. Global tier defaults
    tier_defaults = model_config.get("tier_defaults", {})
    if tier_defaults.get(slot):
        return tier_defaults[slot]

    # 3. Auto-detect from available API keys
    auto = auto_detect_model()
    if auto:
        return auto

    # 4. Hardcoded fallback (will fail with clear error in call_llm)
    return DEFAULT_MODELS.get(slot, "deepseek-flash")
