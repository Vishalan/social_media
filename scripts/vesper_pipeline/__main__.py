"""CLI entrypoint for the Vesper daily pipeline.

Invoked by the LaunchAgent (``deploy/run_vesper_pipeline.sh``) as
``python -m vesper_pipeline``. Builds concrete collaborators from
environment variables + channel profile, then runs
:meth:`VesperPipeline.run_daily`.

This is the last-mile wiring. Everything it imports is already shipped;
the module itself just assembles them. Missing env vars raise loud
errors so the LaunchAgent log surfaces a clear cause.

Required env vars:

    ANTHROPIC_API_KEY         — for ArchivistStoryWriter + TimelinePlanner
    CHATTERBOX_ENDPOINT       — chatterbox sidecar URL on the server
    CHATTERBOX_REFERENCE_AUDIO — container path to Vesper's archivist.wav
    COMFYUI_URL               — server ComfyUI endpoint (for Flux + parallax)
    REDIS_URL                 — server Redis (GPU mutex)
    FAL_API_KEY               — fal.ai key for Flux fallback
    POSTIZ_URL, POSTIZ_API_KEY — Postiz base URL + API key
    TELEGRAM_BOT_TOKEN, TELEGRAM_OWNER_USER_ID — approval flow

Optional env vars:

    VESPER_MAX_SHORTS_PER_RUN — defaults to 2
    VESPER_COST_CEILING_USD   — defaults to 0.75
    VESPER_I2V_ENABLED        — "1"/"true" to enable hero I2V (Unit 10
                                wired; defaults to off until the ComfyUI
                                workflow + benchmarks land)
    VESPER_FLUX_WORKFLOW_PATH — defaults to comfyui_workflows/flux_still.json
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

# Path bootstrap so absolute imports under scripts/ resolve.
_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

logger = logging.getLogger(__name__)


# ─── Boolean env helper ────────────────────────────────────────────────────


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


# ─── Runtime wiring ────────────────────────────────────────────────────────


def build_pipeline_from_env():
    """Construct a fully-wired :class:`VesperPipeline`.

    Every collaborator that the orchestrator accepts is instantiated
    here from env vars + the Vesper channel profile. Missing secrets
    raise ``RuntimeError`` with the exact env var name.
    """
    # Imports kept local so `python -m vesper_pipeline --help` and
    # module import smoke-tests don't pay the full dependency cost.
    from anthropic import Anthropic
    from approval.telegram_bot import TelegramApprovalBot
    from analytics.tracker import AnalyticsTracker
    from channels import load_channel_config
    from still_gen.flux_client import FalFluxClient
    from still_gen.flux_router import FluxRouter
    from still_gen.local_flux_client import LocalFluxClient
    from story_gen.archivist_writer import (
        ArchetypeLibrary,
        ArchivistStoryWriter,
    )
    from story_gen.mod_filter import MonetizationModFilter
    from topic_signal.reddit_story_signal import (
        RedditStorySignalConfig,
        RedditStorySignalSource,
    )
    from video_gen.comfyui_client import ComfyUIClient
    from video_gen.gpu_mutex import GpuPlaneMutex, RedisMutexBackend
    from voiceover.chatterbox_generator import ChatterboxVoiceGenerator

    from . import VesperPipeline, VesperPipelineConfig
    from .assembler import VesperAssembler
    from .parallax_adapter import VesperParallaxAdapter
    from .thumbnail_adapter import VesperThumbnailAdapter
    from .timeline_planner import TimelinePlanner

    # ── Secrets + required URLs ─────────────────────────────────────────
    def _required(name: str) -> str:
        val = os.getenv(name)
        if not val:
            raise RuntimeError(
                f"missing required env var: {name}. "
                f"See scripts/vesper_pipeline/__main__.py docstring for the full list."
            )
        return val

    anthropic_key = _required("ANTHROPIC_API_KEY")
    redis_url = _required("REDIS_URL")
    comfyui_url = _required("COMFYUI_URL")
    postiz_url = _required("POSTIZ_URL")
    postiz_key = _required("POSTIZ_API_KEY")
    telegram_token = _required("TELEGRAM_BOT_TOKEN")
    telegram_owner_id = int(_required("TELEGRAM_OWNER_USER_ID"))

    # ── Channel profile ─────────────────────────────────────────────────
    profile = load_channel_config("vesper")

    # ── Analytics tracker ───────────────────────────────────────────────
    tracker = AnalyticsTracker(db_path="data/analytics.db")

    # ── Reddit topic signal ─────────────────────────────────────────────
    topic_source = RedditStorySignalSource(
        RedditStorySignalConfig(
            subreddits=profile.source.params["subreddits"],
            min_score=profile.source.params.get("min_score", 500),
            time_filter=profile.source.params.get("time_filter", "day"),
            limit=profile.source.params.get("limit", 10),
        ),
    )

    # ── Archivist writer ────────────────────────────────────────────────
    library = ArchetypeLibrary.load(
        Path(profile.source.params["archetype_library"])
    )
    llm_adapter = _AnthropicLlmAdapter(
        Anthropic(api_key=anthropic_key),
        model="claude-sonnet-4-6",
    )
    writer = ArchivistStoryWriter(
        llm=llm_adapter,
        library=library,
        mod_filter=MonetizationModFilter(),
    )

    # ── Chatterbox voice ────────────────────────────────────────────────
    voice = ChatterboxVoiceGenerator(
        reference_audio=os.getenv("CHATTERBOX_REFERENCE_AUDIO"),
        endpoint=os.getenv("CHATTERBOX_ENDPOINT"),
    )

    # ── GPU plane mutex ─────────────────────────────────────────────────
    import redis  # local import — redis-py only needed at runtime
    redis_client = redis.from_url(redis_url)
    mutex = GpuPlaneMutex(RedisMutexBackend(redis_client))

    # ── Flux router (local primary, fal.ai fallback) ────────────────────
    comfy = ComfyUIClient(server_url=comfyui_url)
    local_flux = LocalFluxClient(
        comfyui_client=comfy,
        mutex=mutex,
        workflow_path=os.getenv(
            "VESPER_FLUX_WORKFLOW_PATH",
            "comfyui_workflows/flux_still.json",
        ),
        output_dir="output/vesper/stills",
    )
    fallback_flux = None
    fal_key = os.getenv("FAL_API_KEY")
    if fal_key:
        fallback_flux = FalFluxClient(
            fal_api_key=fal_key,
            endpoint="fal-ai/flux-pro/v1.1",
            output_dir="output/vesper/stills",
        )
    flux_router = FluxRouter(local=local_flux, fallback=fallback_flux)

    # ── Timeline planner ────────────────────────────────────────────────
    timeline_llm = _AnthropicLlmAdapter(
        Anthropic(api_key=anthropic_key),
        model="claude-haiku-4-5-20251001",
    )
    planner = TimelinePlanner(llm=timeline_llm)

    # ── Parallax + I2V backends ─────────────────────────────────────────
    # Parallax adapter is real code now; its ComfyUI workflow JSON is
    # still a server-side deliverable (fails at animate() with a clear
    # runbook-pointer error when absent).
    parallax = VesperParallaxAdapter(
        comfyui_client=comfy,
        mutex=mutex,
        workflow_path=os.getenv(
            "VESPER_PARALLAX_WORKFLOW_PATH",
            "comfyui_workflows/depth_parallax.json",
        ),
    )
    # I2V still Unit-10-hardware-gated; keep the stub until Wan2.2
    # benchmarks on the 3090 pick a model.
    i2v = _NotYetWiredI2VBackend() if _env_bool("VESPER_I2V_ENABLED") else None

    # ── Assembly + thumbnail ────────────────────────────────────────────
    assembler = VesperAssembler()
    thumbnails = VesperThumbnailAdapter(
        palette=profile.palette,
        thumbnail_style=profile.thumbnail,
    )

    # ── Approval + publish ──────────────────────────────────────────────
    approval_bot = TelegramApprovalBot(
        bot_token=telegram_token,
        owner_user_id=telegram_owner_id,
        channel_prefix="[Vesper]",
    )

    from sidecar.postiz_client import PostizClient
    from sidecar.postiz_rate_ledger import PostizRateLedger
    publisher = PostizClient(base_url=postiz_url, api_key=postiz_key)
    rate_ledger = PostizRateLedger(Path("data/postiz_rate_budget.jsonl"))

    # ── Async runner ────────────────────────────────────────────────────
    def _run_async(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    # ── Config ──────────────────────────────────────────────────────────
    config = VesperPipelineConfig(
        channel_id="vesper",
        channel_display_name=profile.display_name,
        postiz_channel_profile=profile.postiz.profile,
        max_shorts_per_run=int(os.getenv("VESPER_MAX_SHORTS_PER_RUN", "2")),
        output_base_dir="output/vesper",
    )

    # ── Cost-ledger factory with env-configurable ceiling ───────────────
    ceiling = float(os.getenv("VESPER_COST_CEILING_USD", "0.75"))

    def _cost_ledger_factory():
        from .cost_telemetry import CostLedger
        return CostLedger(ceiling_usd=ceiling)

    return VesperPipeline(
        config=config,
        topic_source=topic_source,
        writer=writer,
        voice=voice,
        flux=flux_router,
        parallax=parallax,
        i2v=i2v,
        assembler=assembler,
        thumbnails=thumbnails,
        approval=approval_bot,
        publisher=publisher,
        rate_ledger=rate_ledger,
        tracker=tracker,
        async_runner=_run_async,
        timeline_planner=planner,
        cost_ledger_factory=_cost_ledger_factory,
    )


# ─── Remaining stub — I2V gated on Unit 10 hardware benchmarks ─────────────


class _NotYetWiredI2VBackend:
    async def generate(self, still_path, output_path, *, motion_hint):
        raise NotImplementedError(
            "Vesper I2V backend not yet wired. Per Unit 10, benchmark "
            "Wan2.2-class models on the 3090 and add a ComfyUI client "
            "mirroring LocalFluxClient + VesperParallaxAdapter."
        )


# ─── Anthropic SDK adapter matching both LlmClient Protocols ───────────────


class _AnthropicLlmAdapter:
    """Shared adapter — both ArchivistStoryWriter and TimelinePlanner
    require ``complete_json(system_prompt, user_message, max_tokens)``."""

    def __init__(self, client, model: str):
        self._client = client
        self._model = model

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 1024,
    ) -> str:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        # Anthropic returns a list of content blocks; the first text
        # block is the JSON. When more blocks exist, concatenate text.
        parts = []
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                parts.append(block.text)
        return "".join(parts)


# ─── CLI ───────────────────────────────────────────────────────────────────


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    try:
        pipe = build_pipeline_from_env()
    except Exception as exc:
        print(f"vesper_pipeline: wiring failed: {exc}", file=sys.stderr)
        return 2
    try:
        pipe.run_daily()
    except Exception as exc:
        logger.exception("vesper_pipeline: run failed")
        print(f"vesper_pipeline: run failed: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
