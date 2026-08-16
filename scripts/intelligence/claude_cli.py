"""Claude Code CLI adapter — an Anthropic-shaped client backed by ``claude -p``.

Why this exists
---------------
The pipeline's intelligence calls (script writing, b-roll selection, visual
design) previously went to the Anthropic API, which bills per token. The owner
asked that metered API spend be confirmed first, and separately noted the Claude
Code harness may be used for the intelligence layer. This adapter takes that
literally: identical call surface, but the work runs through the local
``claude`` binary against the owner's subscription.

Shape compatibility
-------------------
Only the slice of the SDK the pipeline actually uses is implemented:

    await client.messages.create(model=..., max_tokens=..., system=...,
                                 messages=[...], output_config=...)
    -> object with .content[0].text

``output_config`` with a ``json_schema`` format is honoured by injecting the
schema into the system prompt and validating the reply, since the CLI has no
constrained-decoding flag. A malformed reply is retried once with the parse
error fed back, then raises.

Authentication
--------------
The CLI must be able to authenticate non-interactively. Either the invoking
user has an active ``claude`` login, or ``CLAUDE_CODE_OAUTH_TOKEN`` is set in
the environment (generate one with ``claude setup-token``). Inside a container
the token is the only workable route.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Map Anthropic API model ids onto the CLI's short aliases. The pipeline passes
# full ids like "claude-haiku-4-5"; the CLI wants "haiku"/"sonnet"/"opus".
_MODEL_ALIASES = {
    "haiku": "haiku",
    "sonnet": "sonnet",
    "opus": "opus",
}

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S)


class ClaudeCliError(RuntimeError):
    """Raised when the CLI fails, times out, or returns unusable output."""


@dataclass
class _TextBlock:
    text: str
    type: str = "text"


@dataclass
class _Response:
    """Minimal stand-in for anthropic.types.Message."""
    content: list
    model: str
    stop_reason: str = "end_turn"


def _model_alias(model: Optional[str], default: str) -> str:
    if not model:
        return default
    m = model.lower()
    for key, alias in _MODEL_ALIASES.items():
        if key in m:
            return alias
    return default


def _strip_fence(text: str) -> str:
    """Unwrap ```json ... ``` if the model wrapped its reply."""
    match = _FENCE_RE.match(text)
    return match.group(1) if match else text.strip()


def _flatten_content(content: Any) -> str:
    """Accept both the plain-string and content-block message shapes."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(parts)
    return str(content)


class _Messages:
    """The ``client.messages`` namespace."""

    def __init__(self, parent: "ClaudeCliClient") -> None:
        self._parent = parent

    async def create(
        self,
        *,
        messages: list,
        model: Optional[str] = None,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,   # accepted for signature parity; the CLI has no equivalent
        output_config: Optional[dict] = None,
        **_ignored: Any,
    ) -> _Response:
        prompt = "\n\n".join(
            _flatten_content(m.get("content", "")) for m in messages if m.get("role") == "user"
        ).strip()
        if not prompt:
            raise ClaudeCliError("no user content in messages")

        schema = None
        if output_config:
            fmt = output_config.get("format") or {}
            if fmt.get("type") == "json_schema":
                schema = fmt.get("schema")

        system_parts = [system] if system else []
        if schema is not None:
            system_parts.append(
                "You must reply with a single JSON object and nothing else. "
                "No prose, no explanation, no markdown code fences. "
                "It must validate against this JSON Schema:\n"
                + json.dumps(schema, separators=(",", ":"))
            )
        system_prompt = "\n\n".join(p for p in system_parts if p)

        alias = _model_alias(model, self._parent.default_model)
        text = await self._parent._invoke(prompt, system_prompt, alias)

        if schema is not None:
            text = _strip_fence(text)
            try:
                json.loads(text)
            except json.JSONDecodeError as exc:
                logger.warning("claude -p returned invalid JSON (%s) — retrying once", exc)
                retry_prompt = (
                    f"{prompt}\n\n"
                    f"Your previous reply could not be parsed as JSON ({exc}). "
                    f"Reply with ONLY the JSON object."
                )
                text = _strip_fence(
                    await self._parent._invoke(retry_prompt, system_prompt, alias)
                )
                try:
                    json.loads(text)
                except json.JSONDecodeError as exc2:
                    raise ClaudeCliError(
                        f"claude -p did not return valid JSON after retry: {exc2}"
                    ) from exc2

        return _Response(content=[_TextBlock(text=text)], model=alias)


class ClaudeCliClient:
    """Anthropic-shaped client that executes prompts via the Claude Code CLI."""

    def __init__(
        self,
        binary: str = "claude",
        default_model: str = "sonnet",
        timeout_s: int = 180,
        cwd: Optional[str] = None,
    ) -> None:
        resolved = shutil.which(binary)
        if resolved is None:
            raise ClaudeCliError(
                f"claude CLI not found on PATH as {binary!r}. Install Claude Code, "
                f"or set intelligence_backend='anthropic' to use the metered API."
            )
        self.binary = resolved
        self.default_model = default_model
        self.timeout_s = timeout_s
        self.cwd = cwd
        self.messages = _Messages(self)

    async def _invoke(self, prompt: str, system_prompt: str, model_alias: str) -> str:
        cmd = [
            self.binary,
            "-p", prompt,
            "--output-format", "json",
            "--model", model_alias,
        ]
        if system_prompt:
            cmd += ["--append-system-prompt", system_prompt]

        env = dict(os.environ)
        # These calls are pure text generation — no file access, no shell. Deny
        # every tool so a prompt injected via article text cannot reach the disk.
        cmd += ["--allowed-tools", ""]

        logger.debug("claude -p model=%s prompt_chars=%d", model_alias, len(prompt))
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.cwd,
                env=env,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout_s
            )
        except asyncio.TimeoutError:
            raise ClaudeCliError(f"claude -p timed out after {self.timeout_s}s")
        except OSError as exc:
            raise ClaudeCliError(f"claude -p could not be launched: {exc}") from exc

        if proc.returncode != 0:
            # The CLI writes failures like "Not logged in - Please run /login"
            # to STDOUT, not stderr. Reporting stderr alone produced the
            # useless message "claude -p exited 1: " with nothing after it.
            err = (stderr or b"").decode("utf-8", "replace").strip()
            out = (stdout or b"").decode("utf-8", "replace").strip()
            detail = " | ".join(x for x in (err[-600:], out[-600:]) if x) or "(no output)"
            raise ClaudeCliError(f"claude -p exited {proc.returncode}: {detail}")

        raw = (stdout or b"").decode("utf-8", "replace").strip()
        if not raw:
            raise ClaudeCliError("claude -p produced no output")

        # --output-format json wraps the reply: {"type":"result","result":"...", ...}
        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError:
            # Older/other CLI versions may print the reply bare.
            return raw

        if isinstance(envelope, dict):
            if envelope.get("is_error"):
                raise ClaudeCliError(f"claude -p reported an error: {envelope.get('result')!r}")
            result = envelope.get("result")
            if isinstance(result, str):
                return result.strip()
        return raw
