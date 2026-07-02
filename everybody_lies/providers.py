"""LLM provider definitions, routing, and API calling.

Supports direct APIs (DeepSeek, Gemini) with OpenRouter as universal fallback.
Zero hardcoded secrets — all keys come from environment variables.
"""

import json
import os
import time
import urllib.error
import urllib.request
from functools import lru_cache

from .config import get_config_dir


# ── Key Bootstrap ─────────────────────────────────────────────────────────────
# Populate missing API key env vars from two optional sources at import time.
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
        "models": ["deepseek-v4-flash", "deepseek-v4-pro"],
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
}

# Model-to-provider resolution: which provider to try first for each model.
# Order matters — first available provider wins.
MODEL_ROUTING = {
    "deepseek-v4-flash":                ["deepseek", "openrouter"],
    "deepseek-v4-pro":                  ["deepseek", "openrouter"],
    "deepseek/deepseek-v4-flash":       ["openrouter"],
    "deepseek/deepseek-v4-pro":         ["openrouter"],
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
}

# Default models used when chart.json has no model_config.
# These are overridden by auto_detect_model() when API keys are detected.
DEFAULT_MODELS = {
    "preferred": "deepseek-v4-flash",
    "budget": "deepseek-v4-flash",
}
DEFAULT_FALLBACK = "deepseek-v4-flash"


def auto_detect_model() -> str | None:
    """Detect the best available model based on which API keys are set.

    Resolution order:
    1. ANTHROPIC_API_KEY → claude-sonnet-4-6 (Claude Code users, zero-config)
    2. DEEPSEEK_API_KEY → deepseek-v4-flash (cheapest, fastest)
    3. GEMINI_API_KEY → gemini-2.5-flash (free tier)
    4. OPENROUTER_API_KEY → anthropic/claude-sonnet-4-6
    5. None → caller must handle (no API keys configured)

    Returns a model ID string, or None if no keys are configured.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "claude-sonnet-4-6"
    if os.environ.get("DEEPSEEK_API_KEY"):
        return "deepseek-v4-flash"
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini-2.5-flash"
    if os.environ.get("OPENROUTER_API_KEY"):
        return "anthropic/claude-sonnet-4-6"
    return None


def detect_available_providers() -> list[str]:
    """Return list of provider keys that have API keys configured."""
    available = []
    for key, provider in PROVIDERS.items():
        if os.environ.get(provider["env_key"]):
            available.append(key)
    return available


def available_fallback_models(exclude: str = "") -> list[str]:
    """Ordered fallback models for specialists when the primary model fails.

    Built from whichever provider keys are actually configured, cheapest first.
    Used by the gatekeeper to fail over ACROSS providers (e.g. Anthropic 529
    overload -> DeepSeek -> Gemini) instead of trying a single hardcoded model.
    """
    candidates: list[str] = []
    if os.environ.get("DEEPSEEK_API_KEY"):
        candidates.append("deepseek-v4-flash")
    if os.environ.get("GEMINI_API_KEY"):
        candidates.append("gemini-2.5-flash")
    if os.environ.get("ANTHROPIC_API_KEY"):
        candidates.append("claude-haiku-4-5")
        candidates.append("claude-sonnet-4-6")
    if os.environ.get("OPENROUTER_API_KEY"):
        candidates.append("deepseek/deepseek-v4-flash")
    return [m for m in candidates if m != exclude]


# ── LLM Calling ───────────────────────────────────────────────────────────────

# HTTP statuses worth retrying on the SAME provider before failing over.
# 529 = Anthropic "overloaded" — the exact failure that turned a provider
# outage into a phantom P1 hard-block on 2026-07-01.
_TRANSIENT_HTTP = {408, 429, 500, 502, 503, 504, 529}
_RETRIES_PER_PROVIDER = 2       # 1 initial attempt + 1 retry
_RETRY_BACKOFF_S = 3.0          # short — the pre-commit hook has a 300s budget


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

    Raises RuntimeError if all providers fail.
    """
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
    return DEFAULT_MODELS.get(slot, "deepseek-v4-flash")
