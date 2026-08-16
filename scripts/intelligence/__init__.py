"""Intelligence layer for the CommonCreed pipeline.

Two interchangeable backends, chosen by ``config["intelligence_backend"]``:

``claude_cli`` (default)
    Shells out to the Claude Code CLI in headless mode (``claude -p``). Billed
    against the owner's Claude subscription rather than per-token API credit,
    which is why it is the default — the owner asked to be consulted before any
    metered API spend.

``anthropic``
    The regular ``AsyncAnthropic`` SDK client. Costs API credit per call.

Both expose the same surface the existing callers already use::

    response = await client.messages.create(
        model=..., max_tokens=..., system=..., messages=[...],
        output_config={"format": {"type": "json_schema", "schema": {...}}},
    )
    text = response.content[0].text

so ``BrollSelector`` and the script generator need no changes beyond being
handed a different client object.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["make_intelligence_client", "ClaudeCliClient", "ClaudeCliError"]

from .claude_cli import ClaudeCliClient, ClaudeCliError  # noqa: E402

_DEFAULT_BACKEND = "claude_cli"


def make_intelligence_client(config: dict) -> Any:
    """Return an Anthropic-shaped client for the configured backend.

    Raises:
        ValueError: if ``intelligence_backend`` is unrecognised.
    """
    backend = str(config.get("intelligence_backend", _DEFAULT_BACKEND)).lower()

    if backend == "claude_cli":
        logger.info("Intelligence backend: Claude Code CLI (claude -p, subscription-billed)")
        return ClaudeCliClient(
            binary=config.get("claude_cli_binary", "claude"),
            default_model=config.get("claude_cli_model", "sonnet"),
            timeout_s=int(config.get("claude_cli_timeout_s", 180)),
            cwd=config.get("claude_cli_cwd"),
        )

    if backend == "anthropic":
        from anthropic import AsyncAnthropic
        logger.warning(
            "Intelligence backend: Anthropic API — this spends metered API credit"
        )
        return AsyncAnthropic(api_key=config["anthropic_api_key"])

    raise ValueError(
        f"Unknown intelligence_backend {backend!r} (expected 'claude_cli' or 'anthropic')"
    )
