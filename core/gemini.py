"""Shared Gemini REST calls, pinned to the user's selected brain.

The Live connection in main.py performs speech recognition only. Every helper
generation here uses the exact REST model below; failures never select another
model. Tier names remain compatible with the existing actions and plugins.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from core.credentials import CredentialError, read_config

from core.app_paths import runtime_root
_BASE = runtime_root()
_KEY_FILE = _BASE / "config" / "api_keys.json"

MODEL = "gemini-3.8-flash"
FAST = "fast"
SMART = "smart"
SEARCH = "search"
LIVE = "live"  # legacy tier name; it now uses the pinned REST brain
_LADDERS = {tier: (MODEL,) for tier in (FAST, SMART, SEARCH, LIVE)}
DEFAULT_TIMEOUT_MS = 30_000
MIN_TIMEOUT_MS = 10_000
def api_key(refresh: bool = False) -> str:
    """Read current private settings for every client; never retain an old key.

    ``refresh`` remains accepted for existing callers. Reads are always fresh,
    including after an atomic Settings save whose timestamp happens to match.
    """
    try:
        value = read_config(_KEY_FILE).get("gemini_api_key", "")
    except (CredentialError, OSError):
        return ""
    return value.strip() if isinstance(value, str) else ""


def client(timeout_ms: int = DEFAULT_TIMEOUT_MS, key: str = ""):
    from google import genai
    from google.genai import types

    resolved = key or api_key()
    if not resolved:
        raise RuntimeError("no Gemini API key is configured")
    return genai.Client(api_key=resolved, http_options=types.HttpOptions(
        timeout=max(MIN_TIMEOUT_MS, int(timeout_ms))))


def call(contents, tier: str = FAST, config=None,
         timeout_ms: int = DEFAULT_TIMEOUT_MS, key: str = ""):
    """Generate with gemini-3.8-flash. Retain old signatures, never fallback.

    Existing plugins may supply an old tier/model setting. The user's global
    brain selection is authoritative for those calls as well.
    """
    cl = None
    try:
        cl = client(timeout_ms=timeout_ms, key=key)
        kwargs = {"model": MODEL, "contents": contents}
        if config is not None:
            kwargs["config"] = config
        return cl.models.generate_content(**kwargs)
    except Exception as error:
        # Provider exception bodies can echo request data. Log only model,
        # exception class and numeric status, never prompts or credentials.
        status = getattr(error, "code", None)
        print(f"[Gemini] {MODEL}: {type(error).__name__}; status={status if isinstance(status, int) else 'unavailable'}")
        return None
    finally:
        if cl is not None:
            try:
                cl.close()
            except Exception:
                pass


def text(contents, tier: str = FAST, config=None,
         timeout_ms: int = DEFAULT_TIMEOUT_MS, key: str = "", default: str = "") -> str:
    response = call(contents, tier=tier, config=config, timeout_ms=timeout_ms, key=key)
    if response is None:
        return default
    return (getattr(response, "text", None) or "").strip() or default


def as_json(contents, tier: str = FAST, config=None,
            timeout_ms: int = DEFAULT_TIMEOUT_MS, key: str = "", default=None):
    raw = text(contents, tier=tier, config=config, timeout_ms=timeout_ms, key=key)
    if not raw:
        return default
    if "{" in raw and "}" in raw:
        raw = raw[raw.find("{"):raw.rfind("}") + 1]
    elif "[" in raw and "]" in raw:
        raw = raw[raw.find("["):raw.rfind("]") + 1]
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        print(f"[Gemini] {MODEL}: response is not valid JSON")
        return default
