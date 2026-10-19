"""The one place the explanation layer talks to a language model (#27).

An `LLM` is any function `(system, user) -> text`. Tests pass a fake; `from_env()` builds a
real one from SystemCode/.env, so switching provider is a change of settings, not code:

    LLM_PROVIDER=deepseek | gemini | anthropic | openai_compatible
    LLM_API_KEY=...
    LLM_MODEL=...            # the provider's model name, e.g. deepseek-chat
    LLM_BASE_URL=...         # only for openai_compatible

The model only rewords evidence it is given; it never decides anything.
"""

import os
from collections.abc import Callable
from pathlib import Path

import httpx

LLM = Callable[[str, str], str]

# Providers that speak the OpenAI chat-completions format, and where.
OPENAI_STYLE = {
    "deepseek": "https://api.deepseek.com",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
}
TIMEOUT_S = 60.0
MAX_TOKENS = 600
_ENV = Path(__file__).resolve().parents[2] / ".env"


class LLMNotConfigured(RuntimeError):
    pass


def openai_style(base_url: str, model: str, key: str) -> LLM:
    def call(system: str, user: str) -> str:
        r = httpx.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "temperature": 0, "max_tokens": MAX_TOKENS,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}]},
            timeout=TIMEOUT_S,
        )
        r.raise_for_status()
        return str(r.json()["choices"][0]["message"]["content"])

    return call


def anthropic(model: str, key: str) -> LLM:
    def call(system: str, user: str) -> str:
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            json={"model": model, "max_tokens": MAX_TOKENS, "temperature": 0,
                  "system": system, "messages": [{"role": "user", "content": user}]},
            timeout=TIMEOUT_S,
        )
        r.raise_for_status()
        return "".join(b["text"] for b in r.json()["content"] if b["type"] == "text")

    return call


def from_env() -> LLM:
    """Build the configured model, or raise LLMNotConfigured saying what is missing."""
    from dotenv import load_dotenv

    load_dotenv(_ENV)  # never overrides a variable already set
    provider = os.environ.get("LLM_PROVIDER", "").strip().lower()
    key = os.environ.get("LLM_API_KEY", "").strip()
    model = os.environ.get("LLM_MODEL", "").strip()
    missing = [n for n, v in (("LLM_PROVIDER", provider), ("LLM_API_KEY", key),
                              ("LLM_MODEL", model)) if not v]
    if missing:
        raise LLMNotConfigured(f"set {', '.join(missing)} in SystemCode/.env")
    if provider in OPENAI_STYLE:
        return openai_style(OPENAI_STYLE[provider], model, key)
    if provider == "anthropic":
        return anthropic(model, key)
    if provider == "openai_compatible":
        base = os.environ.get("LLM_BASE_URL", "").strip()
        if not base:
            raise LLMNotConfigured("set LLM_BASE_URL for openai_compatible")
        return openai_style(base, model, key)
    raise LLMNotConfigured(f"unknown LLM_PROVIDER {provider!r}")
