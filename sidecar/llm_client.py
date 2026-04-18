"""
Thin LLM provider abstraction — routes calls to Ollama or Anthropic.

Supports per-task model selection and automatic fallback: if the primary
provider fails (connection error, timeout, 5xx), retries once against the
fallback provider so the pipeline always completes.

Both providers return plain text. JSON parsing is the caller's responsibility
(same as before). Ollama's ``format: "json"`` option is used when the caller
requests JSON mode, which constrains output to valid JSON at the decoding
level.

Usage::

    from sidecar.llm_client import llm_call

    text = llm_call(
        prompt="Rate these items...",
        provider="ollama",          # or "anthropic"
        model="qwen3:8b",           # or "claude-haiku-4-5-20251001"
        json_mode=True,
        anthropic_api_key="sk-...", # needed for anthropic provider + fallback
        ollama_base_url="http://host.docker.internal:11434",
    )
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_TIMEOUT = 180.0  # generous for Ollama cold-start + thinking + inference


def llm_call(
    prompt: str,
    *,
    provider: str = "ollama",
    model: str = "qwen3:8b",
    json_mode: bool = False,
    max_tokens: int = 1000,
    temperature: float = 0.2,
    anthropic_api_key: str = "",
    ollama_base_url: str = "http://host.docker.internal:11434",
    fallback: bool = True,
) -> str:
    """Send a prompt to the configured LLM provider, return response text.

    If ``fallback`` is True and the primary provider fails, retries once
    with the other provider. Raises on double failure.
    """
    primary = provider.lower().strip()
    if primary not in ("ollama", "anthropic"):
        raise ValueError(f"unknown LLM provider: {primary!r}")

    try:
        return _dispatch(
            primary, prompt, model, json_mode, max_tokens, temperature,
            anthropic_api_key, ollama_base_url,
        )
    except Exception as exc:
        if not fallback:
            raise
        secondary = "anthropic" if primary == "ollama" else "ollama"
        fallback_model = (
            "claude-haiku-4-5-20251001" if secondary == "anthropic" else "qwen3:8b"
        )
        logger.warning(
            "llm_call: %s/%s failed (%s), falling back to %s/%s",
            primary, model, exc, secondary, fallback_model,
        )
        return _dispatch(
            secondary, prompt, fallback_model, json_mode, max_tokens,
            temperature, anthropic_api_key, ollama_base_url,
        )


def _dispatch(
    provider: str,
    prompt: str,
    model: str,
    json_mode: bool,
    max_tokens: int,
    temperature: float,
    anthropic_api_key: str,
    ollama_base_url: str,
) -> str:
    if provider == "ollama":
        return _call_ollama(prompt, model, json_mode, max_tokens, temperature, ollama_base_url)
    return _call_anthropic(prompt, model, json_mode, max_tokens, temperature, anthropic_api_key)


def _call_ollama(
    prompt: str,
    model: str,
    json_mode: bool,
    max_tokens: int,
    temperature: float,
    base_url: str,
) -> str:
    import httpx

    # Prepend /no_think tag for Qwen 3 models to disable chain-of-thought
    # and get direct JSON output. Other models ignore this tag harmlessly.
    effective_prompt = prompt
    model_lower = model.lower()
    if "qwen3" in model_lower or "qwen-3" in model_lower:
        effective_prompt = "/no_think\n" + prompt

    body: dict = {
        "model": model,
        "messages": [{"role": "user", "content": effective_prompt}],
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }
    if json_mode:
        body["format"] = "json"

    url = f"{base_url.rstrip('/')}/api/chat"
    resp = httpx.post(url, json=body, timeout=_TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"Ollama {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    msg = data.get("message") or {}
    # Qwen 3 may put output in "thinking" when in think mode, or "content"
    # when /no_think is used. Check both.
    text = msg.get("content") or msg.get("thinking") or ""
    if not text:
        raise RuntimeError(f"Ollama returned empty content: {data!r}")
    return text.strip()


def _call_anthropic(
    prompt: str,
    model: str,
    json_mode: bool,
    max_tokens: int,
    temperature: float,
    api_key: str,
) -> str:
    import httpx

    if not api_key:
        raise RuntimeError("Anthropic API key required but not provided")

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }
    resp = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers=headers,
        json=body,
        timeout=_TIMEOUT,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Anthropic {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    text = data["content"][0]["text"]
    return text.strip()
