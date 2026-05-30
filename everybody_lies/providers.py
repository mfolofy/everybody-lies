"""LLM provider definitions, routing, and API calling.

Supports direct APIs (DeepSeek, Gemini) with OpenRouter as universal fallback.
Zero hardcoded secrets — all keys come from environment variables.
"""

import json
import os
import urllib.error
import urllib.request
from functools import lru_cache

from .config import get_config_dir


# ── Provider Definitions ──────────────────────────────────────────────────────

# Each provider specifies base_url, auth, and which models it serves.
PROVIDERS = {
    "deepseek": {
        "name": "DeepSeek Direct",
        "base_url": "https://api.deepseek.com/v1/chat/completions",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "env_key": "DEEPSEEK_API_KEY",
        "models": ["deepseek-v4-flash", "deepseek-reasoner"],
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
    "deepseek-reasoner":                ["deepseek", "openrouter"],
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

# Default models used when review_board.json has no model_config.
# These are overridden by auto_detect_model() when API keys are detected.
DEFAULT_MODELS = {
    "preferred": "deepseek-v4-flash",
    "budget": "deepseek-v4-flash",
}
DEFAULT_FALLBACK = "deepseek-v4-flash"


def auto_detect_model() -> str:
    """Detect the best available model based on which API keys are set.

    Resolution order:
    1. ANTHROPIC_API_KEY → claude-sonnet-4-6 (Claude Code users, zero-config)
    2. DEEPSEEK_API_KEY → deepseek-v4-flash (cheapest, fastest)
    3. GEMINI_API_KEY → gemini-2.5-flash (free tier)
    4. OPENROUTER_API_KEY → anthropic/claude-sonnet-4-6
    5. None → same error as before, user must configure

    Returns a model ID resolvable by _get_provider_for_model().
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "claude-sonnet-4-6"
    if os.environ.get("DEEPSEEK_API_KEY"):
        return "deepseek-v4-flash"
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini-2.5-flash"
    if os.environ.get("OPENROUTER_API_KEY"):
        return "anthropic/claude-sonnet-4-6"
    return ""


def detect_available_providers() -> list[str]:
    """Return list of provider keys that have API keys configured."""
    available = []
    for key, provider in PROVIDERS.items():
        if os.environ.get(provider["env_key"]):
            available.append(key)
    return available


# ── Key Resolution ────────────────────────────────────────────────────────────

def _get_provider_for_model(model_id: str) -> dict | None:
    """Find the first available provider for a model. Returns provider dict or None."""
    providers_to_try = MODEL_ROUTING.get(model_id, ["openrouter"])
    for provider_key in providers_to_try:
        provider = PROVIDERS.get(provider_key)
        if provider and os.environ.get(provider["env_key"]):
            return provider
    return PROVIDERS.get("openrouter")


def _get_api_key_for_model(model_id: str) -> str:
    """Resolve API key for a model.

    Resolution order:
    1. Standard provider env var (DEEPSEEK_API_KEY, GEMINI_API_KEY, etc.)
    2. OPENROUTER_API_KEY env var
    3. EVERYBODY_LIES_API_KEYS JSON env var  →  api_keys.OPENROUTER_API_KEY
    """
    provider = _get_provider_for_model(model_id)
    if provider:
        key = os.environ.get(provider["env_key"])
        if key:
            return key

    # OpenRouter fallback
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key

    # JSON config fallback
    json_keys = os.environ.get("EVERYBODY_LIES_API_KEYS")
    if json_keys:
        try:
            parsed = json.loads(json_keys)
            if isinstance(parsed, dict):
                key = parsed.get("OPENROUTER_API_KEY", "")
                if key:
                    return key
        except json.JSONDecodeError:
            pass

    return ""


# ── LLM Calling ───────────────────────────────────────────────────────────────

def call_llm(
    model: str,
    system_prompt: str,
    user_prompt: str,
    api_key: str = "",
    max_tokens: int = 4096,
    temperature: float = 0.3,
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
    for provider_key in providers_to_try:
        provider = PROVIDERS.get(provider_key)
        if not provider:
            continue

        key = api_key if api_key else os.environ.get(provider["env_key"], "")
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
            }

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
            continue
        except Exception as exc:
            last_error = str(exc)[:300]
            continue

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
