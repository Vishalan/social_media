"""
CommonCreed AI Avatar Content Pipeline.

Daily orchestrator — three phases, pod only runs during GPU b-roll work:

  Phase 1 — CPU + cloud APIs (pod OFF):
    For each topic: fetch script → voiceover → upload audio → avatar generation.
    Avatar is generated via HeyGen or Kling cloud API — no GPU needed.

  Phase 2 — GPU (pod ON, ~10 min for 3 videos):
    For each topic: b-roll generation via ComfyUI on RunPod.
    Pod stops immediately after all b-roll is done.

  Phase 3 — CPU (pod OFF, free):
    For each topic: trim silence → assemble video → Telegram approval → post.
    On rejection: retry once (no pre-generated backup — new avatar call not required
    at this phase; owner sees assembled video and can approve or skip).
    No GPU needed.

Cost: ~$0.35/day fixed (3 topics × ~10 min b-roll GPU time × $0.69/hr).

Usage:
    python commoncreed_pipeline.py

Required environment variables (see .env.example):
    ANTHROPIC_API_KEY, ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID,
    AYRSHARE_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_OWNER_USER_ID,
    RUNPOD_API_KEY,
    AVATAR_PROVIDER (default: kling),
    FAL_API_KEY + KLING_AVATAR_IMAGE_URL  (when AVATAR_PROVIDER=kling)
    HEYGEN_API_KEY + HEYGEN_AVATAR_ID     (when AVATAR_PROVIDER=heygen)

Optional (RunPod tuning):
    RUNPOD_GPU_TYPE_ID       — defaults to "NVIDIA GeForce RTX 4090"
    RUNPOD_TEMPLATE_ID       — pre-built ComfyUI template ID (speeds up startup)
    RUNPOD_NETWORK_VOLUME_ID — network volume with cached model weights
    RUNPOD_COMFYUI_PORT      — defaults to 8188

Set COMFYUI_URL to skip RunPod and point at a local/existing ComfyUI instance.

Note: REFERENCE_VIDEO_PATH is no longer needed at runtime — it is only used once
during the one-time avatar setup script (scripts/avatar_gen/setup_heygen_avatar.py).
"""

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from analytics.tracker import AnalyticsTracker
from approval.telegram_bot import TelegramApprovalBot
from avatar_gen import AvatarQualityError, make_avatar_client
from content_gen.script_generator import ScriptGenerator
from gpu.pod_manager import PodManager, PodStartupError
from news_sourcing.news_sourcer import InsufficientTopicsError, NewsSourcer
from posting.social_poster import SocialPoster
from video_edit.video_editor import VideoEditor
from video_gen.comfyui_client import ComfyUIClient
from voiceover.voice_generator import VoiceGenerator

logger = logging.getLogger(__name__)


@dataclass
class VideoJob:
    """Holds all generated assets for one topic, ready for Phase 3 assembly."""

    topic: dict
    script: dict
    trimmed_audio_path: str
    avatar_path: str
    audio_url: str = ""       # Ayrshare-hosted audio URL used for avatar generation
    broll_path: str = ""
    caption_segments: list[dict] = field(default_factory=list)
    affiliate_links: list[str] = field(default_factory=list)
    broll_only: bool = False   # True if avatar generation failed completely


class CommonCreedPipeline:
    """
    End-to-end daily pipeline for the @commoncreed AI avatar content channel.

    Phase 1 (CPU + cloud APIs, pod OFF): generate scripts, voiceovers, and avatar
        videos for all topics. Avatar is a cloud API call (HeyGen or Kling).
    Phase 2 (GPU, pod ON): generate b-roll for all topics via ComfyUI on RunPod.
    Phase 3 (CPU, pod OFF): trim silence, assemble, get Telegram approval, post.

    GPU cost: ~$0.35/day fixed (3 topics × ~10 min b-roll time × $0.69/hr).
    """

    def __init__(self, config: dict):
        """
        config keys (all sourced from environment variables):
            anthropic_api_key        — Anthropic API key
            elevenlabs_api_key       — ElevenLabs API key
            voice_id                 — ElevenLabs voice ID
            ayrshare_api_key         — Ayrshare API key for multi-platform posting
            telegram_bot_token       — Telegram bot token (BotFather)
            telegram_owner_user_id   — Integer Telegram user ID of owner
            runpod_api_key           — RunPod API key (auto-manages pod lifecycle)
            runpod_gpu_type_id       — GPU type (default: "NVIDIA GeForce RTX 4090")
            runpod_template_id       — (optional) pre-built ComfyUI template ID
            runpod_network_volume_id — (optional) network volume with cached weights
            runpod_comfyui_port      — (optional) ComfyUI port, default 8188
            comfyui_url              — (optional) override: skip RunPod, use this URL
            niche                    — Content niche label (e.g. "AI & Technology")
            avatar_provider          — "kling" (default) or "heygen"
            heygen_api_key           — HeyGen API key (when avatar_provider=heygen)
            heygen_avatar_id         — HeyGen Instant Avatar ID (when avatar_provider=heygen)
            fal_api_key              — fal.ai API key (when avatar_provider=kling)
            kling_avatar_image_url   — Public URL of owner portrait photo (when avatar_provider=kling)
        """
        self.config = config

        # RunPod pod manager — auto-starts/stops the GPU instance around b-roll work.
        # If comfyui_url is set directly, RunPod is bypassed (local dev mode).
        self._static_comfyui_url: str | None = config.get("comfyui_url") or None
        if self._static_comfyui_url:
            self._pod_manager = None
            logger.info("Using static ComfyUI URL: %s (RunPod disabled)", self._static_comfyui_url)
        else:
            self._pod_manager = PodManager(config)

        self.tracker = AnalyticsTracker()
        self.script_gen = ScriptGenerator(
            api_provider="anthropic",
            api_key=config["anthropic_api_key"],
            output_dir="output/scripts",
        )
        self.voice_gen = VoiceGenerator(
            api_key=config["elevenlabs_api_key"],
            voice_id=config["voice_id"],
        )
        # ComfyUI client — server_url injected at run time once pod is ready
        self.comfyui = ComfyUIClient(
            server_url=self._static_comfyui_url or "",
            api_key=config.get("comfyui_api_key", ""),
        )
        # Avatar client — provider selected by config["avatar_provider"]
        self.avatar_client = make_avatar_client(config)
        self.video_editor = VideoEditor()
        self.telegram = TelegramApprovalBot(
            bot_token=config["telegram_bot_token"],
            owner_user_id=int(config["telegram_owner_user_id"]),
        )
        self.poster = SocialPoster(ayrshare_key=config["ayrshare_api_key"])
        self.news_sourcer = NewsSourcer(
            tracker=self.tracker,
            telegram_bot=self.telegram,
            max_topics=3,
        )

    # ─── Public entry point ────────────────────────────────────────────────

    async def run_daily(self) -> None:
        """
        Run the full daily pipeline.

        Phase 1 — CPU + cloud APIs (pod OFF):
          Fetch topics → generate scripts → voiceovers → upload audio → avatar
          generation for all topics. No RunPod pod needed.

        Phase 2 — GPU (pod ON):
          B-roll generation via ComfyUI for all topics.
          Pod is guaranteed to stop even on exception.

        Phase 3 — CPU (pod OFF, free):
          Trim silence → assemble → Telegram approval → post for each job.
          On rejection, skip (no pre-generated backup; owner prompted once).

        Raises InsufficientTopicsError if fewer than 2 unique topics found.
        """
        logger.info("CommonCreed pipeline starting")

        # News fetch: no GPU needed
        topics = self.news_sourcer.fetch()
        logger.info("Fetched %d topics", len(topics))

        # Phase 1: CPU + cloud APIs — scripts, voices, avatar (pod OFF)
        jobs = await self._phase1_generate(topics)
        logger.info("Phase 1 complete — avatars generated. Starting Phase 2 (GPU b-roll).")

        # Phase 2: GPU — start pod, generate all b-roll, stop pod
        await self._phase2_broll(jobs)
        logger.info("Phase 2 complete — pod stopped. Starting Phase 3 (CPU).")

        # Phase 3: CPU — trim, assemble, approve, post (no pod running)
        await self._phase3_finalize(jobs)
        logger.info("CommonCreed pipeline complete")

    # ─── Phase 1: CPU + cloud APIs ────────────────────────────────────────

    async def _phase1_generate(self, topics: list[dict]) -> list[VideoJob]:
        """
        Generate scripts, voiceovers, and avatar videos for all topics.
        Pod is OFF — all work is CPU or cloud API calls.
        Skips failed topics and alerts owner; continues with remaining.
        """
        jobs: list[VideoJob] = []
        for topic in topics:
            try:
                job = await self._generate_script_voice_avatar(topic)
                jobs.append(job)
            except Exception as exc:
                logger.error("Phase 1 failed for topic '%s': %s", topic["title"], exc)
                await self.telegram.send_alert(
                    f"Skipping topic (Phase 1 error): '{topic['title']}' — {exc}"
                )
        return jobs

    async def _generate_script_voice_avatar(self, topic: dict) -> VideoJob:
        """
        Generate script, voiceover, upload audio, and avatar for one topic.
        Returns a VideoJob with avatar_path and audio_url set; broll_path is
        filled in Phase 2.
        """
        logger.info("[Phase 1] Generating script/voice/avatar for: %s", topic["title"])

        # Script (Anthropic API)
        script = self.script_gen.generate_short_form(topic["title"])

        # Voiceover (ElevenLabs API)
        audio_path = await self._generate_voice(script["script"], topic)

        # Upload audio to Ayrshare to get a public URL for the avatar API
        audio_url = await asyncio.to_thread(self.poster.upload_media, audio_path)
        logger.info("[Phase 1] Audio uploaded for '%s': %s", topic["title"], audio_url)

        # Avatar generation (HeyGen or Kling cloud API — no GPU)
        broll_only = False
        avatar_path = ""
        try:
            avatar_path = await self._generate_avatar(audio_url, topic)
        except AvatarQualityError:
            logger.error(
                "Avatar generation failed twice for '%s' — using b-roll-only",
                topic["title"],
            )
            await self.telegram.send_alert(
                f"Avatar failed for '{topic['title']}' — video will be b-roll only."
            )
            broll_only = True

        return VideoJob(
            topic=topic,
            script=script,
            trimmed_audio_path=audio_path,  # silence trim happens in Phase 3
            avatar_path=avatar_path,
            audio_url=audio_url,
            broll_path="",          # filled in Phase 2
            caption_segments=[],    # filled in Phase 3
            affiliate_links=self._select_affiliates(),
            broll_only=broll_only,
        )

    # ─── Phase 2: GPU (b-roll only) ───────────────────────────────────────

    async def _phase2_broll(self, jobs: list[VideoJob]) -> None:
        """
        Start pod, generate b-roll for all jobs, stop pod.
        Mutates each job's broll_path in place.
        """
        if self._pod_manager is not None:
            await self._phase2_with_pod(jobs)
        else:
            await self._phase2_broll_jobs(jobs)

    async def _phase2_with_pod(self, jobs: list[VideoJob]) -> None:
        try:
            async with self._pod_manager as comfyui_url:
                logger.info("RunPod pod ready — ComfyUI at %s", comfyui_url)
                self.comfyui.server_url = comfyui_url
                await self._phase2_broll_jobs(jobs)
        except PodStartupError as exc:
            logger.error("RunPod pod failed to start: %s", exc)
            await self.telegram.send_alert(
                f"Pipeline aborted — RunPod pod failed to start: {exc}"
            )
            raise

    async def _phase2_broll_jobs(self, jobs: list[VideoJob]) -> None:
        """Generate b-roll for all jobs sequentially. Skips failed topics."""
        for job in jobs:
            try:
                job.broll_path = await self._generate_broll(job.script, job.topic)
            except Exception as exc:
                logger.error(
                    "B-roll generation failed for topic '%s': %s",
                    job.topic["title"],
                    exc,
                )
                await self.telegram.send_alert(
                    f"B-roll failed for '{job.topic['title']}': {exc} — video will be skipped."
                )
                # Mark as unrecoverable so Phase 3 skips this job
                job.broll_path = ""
                job.broll_only = True  # flag reviewed in _assemble()

    # ─── Phase 3: CPU ─────────────────────────────────────────────────────

    async def _phase3_finalize(self, jobs: list[VideoJob]) -> None:
        """Trim silence, assemble, get Telegram approval, and post for each job.
        No GPU needed."""
        for job in jobs:
            # Skip jobs where b-roll failed and we have no avatar either
            if not job.broll_path and not job.avatar_path:
                logger.warning(
                    "Skipping '%s' — no b-roll and no avatar available",
                    job.topic["title"],
                )
                continue
            try:
                await self._finalize_job(job)
            except Exception as exc:
                logger.error(
                    "Phase 3 failed for topic '%s': %s", job.topic["title"], exc
                )
                await self.telegram.send_alert(
                    f"Post-production error for '{job.topic['title']}': {exc}"
                )

    async def _finalize_job(self, job: VideoJob) -> None:
        """Trim silence → assemble → approve → post one video."""
        safe_title = re.sub(r"[^a-z0-9_]", "_", job.topic["title"].lower())[:40]
        caption = job.script.get("description", job.topic["title"])

        # Transcribe audio for word-level captions and silence trimming (CPU)
        caption_segments = self._transcribe(job.trimmed_audio_path)
        trimmed_audio = self.video_editor.trim_silence(
            job.trimmed_audio_path,
            caption_segments,
            job.trimmed_audio_path.replace(".mp3", ".trimmed.mp3"),
        )
        # Update job fields for use in _assemble()
        job.caption_segments = caption_segments
        job.trimmed_audio_path = trimmed_audio

        # Assemble final video (CPU — MoviePy + FFmpeg)
        final_video = self._assemble(job, job.avatar_path, f"{safe_title}_final.mp4")

        # Telegram approval
        decision = await self.telegram.request_approval(
            video_path=final_video,
            caption=caption,
            topic=job.topic["title"],
        )

        if decision == "approve":
            await self._post_approved(
                final_video, caption, job.script.get("tags", []), job.affiliate_links
            )
            self.tracker.log_post(
                platform="instagram,tiktok,youtube",
                post_id=job.topic["url"],
                title=job.topic["title"],
                description=caption,
            )
            logger.info("Posted: %s", job.topic["title"])
        else:
            logger.info("Skipped after rejection: %s", job.topic["title"])

    def _assemble(self, job: VideoJob, avatar_path: str, filename: str) -> str:
        """Assemble final 9:16 video. Uses b-roll-only layout if avatar_path is empty.

        HeyGen outputs 1920x1080 (landscape) → crop_to_portrait=True.
        Kling outputs native 9:16 → no crop needed.
        """
        output_path = f"output/video/{filename}"
        crop = self.config.get("avatar_provider", "kling") == "heygen"
        if job.broll_only or not avatar_path:
            # B-roll only: full-screen b-roll with captions
            output_path = self.video_editor.assemble(
                avatar_path=job.broll_path,
                broll_path=job.broll_path,
                audio_path=job.trimmed_audio_path,
                caption_segments=job.caption_segments,
                output_path=output_path,
            )
        else:
            output_path = self.video_editor.assemble(
                avatar_path=avatar_path,
                broll_path=job.broll_path,
                audio_path=job.trimmed_audio_path,
                caption_segments=job.caption_segments,
                output_path=output_path,
                crop_to_portrait=crop,
            )
        return output_path

    # ─── Private: generation helpers ──────────────────────────────────────

    async def _generate_avatar(self, audio_url: str, topic: dict) -> str:
        """
        Generate avatar A-roll from a public audio URL.
        Retries once automatically on AvatarQualityError before raising.
        Uses make_avatar_client-selected backend (HeyGen or Kling).
        """
        output_path = f"output/avatar/{_safe(topic['title'])}_avatar.mp4"
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        try:
            return await self.avatar_client.generate(audio_url, output_path)
        except AvatarQualityError:
            # Auto-retry once (HeyGen/Kling don't have a seed param; a new call
            # may succeed if the first attempt hit a transient quality issue)
            logger.warning(
                "Avatar quality check failed on first attempt for '%s' — retrying",
                topic["title"],
            )
            # Use a distinct output path for the retry attempt
            retry_output_path = f"output/avatar/{_safe(topic['title'])}_avatar_retry.mp4"
            return await self.avatar_client.generate(audio_url, retry_output_path)
            # If this second call also raises AvatarQualityError, it propagates
            # to _generate_script_voice_avatar(), which catches it and sets broll_only=True.

    async def _generate_broll(self, script: dict, topic: dict) -> str:
        """Generate b-roll via existing ComfyUI workflow."""
        visual_prompt = script.get("visual_cues", script.get("title", "tech news"))
        output_path = f"output/video/{_safe(topic['title'])}_broll.mp4"
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        return await self.comfyui.run_workflow(
            workflow_json=None,
            params={"prompt": visual_prompt, "output_path": output_path},
            wait_for_completion=True,
        )

    async def _generate_voice(self, text: str, topic: dict) -> str:
        """Generate voiceover audio via ElevenLabs. Runs in thread."""
        output_path = f"output/audio/{_safe(topic['title'])}_voice.mp3"
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        return await asyncio.to_thread(self.voice_gen.generate, text, output_path)

    def _transcribe(self, audio_path: str) -> list[dict]:
        """
        Transcribe audio with faster-whisper, return word-level timestamps.
        Returns [] if faster-whisper is not installed (captions + trimming disabled).
        """
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            logger.warning("faster-whisper not installed — captions and silence trimming disabled")
            return []

        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(audio_path, word_timestamps=True)
        words = []
        for seg in segments:
            for w in (seg.words or []):
                words.append({"word": w.word.strip(), "start": w.start, "end": w.end})
        return words

    def _select_affiliates(self) -> list[str]:
        """Return up to 3 affiliate links from config/settings.py AFFILIATES dict."""
        try:
            from config.settings import AFFILIATES
            return list(AFFILIATES.values())[:3]
        except (ImportError, AttributeError):
            logger.warning("AFFILIATES not found in config/settings.py — no affiliate links")
            return []

    async def _post_approved(
        self,
        video_path: str,
        caption: str,
        tags: list[str],
        affiliate_links: list[str],
    ) -> None:
        """Fan out to Instagram, TikTok, YouTube Shorts via SocialPoster."""
        await asyncio.to_thread(
            self.poster.post_all_short_form,
            caption=caption,
            video_path=video_path,
            hashtags=tags,
            affiliate_links=affiliate_links,
        )


# ─── Helpers ──────────────────────────────────────────────────────────────

def _safe(title: str) -> str:
    """Sanitize a topic title for use in file paths."""
    return re.sub(r"[^a-z0-9_]", "_", title.lower())[:40]


# ─── CLI entry point ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stdout,
    )
    load_dotenv()

    # COMFYUI_URL is optional — if set, RunPod is bypassed (local dev mode)
    use_runpod = not os.environ.get("COMFYUI_URL") and bool(os.environ.get("RUNPOD_API_KEY"))

    required_keys = [
        "ANTHROPIC_API_KEY",
        "ELEVENLABS_API_KEY",
        "ELEVENLABS_VOICE_ID",
        "AYRSHARE_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_OWNER_USER_ID",
    ]
    if use_runpod:
        required_keys.append("RUNPOD_API_KEY")
    else:
        required_keys.append("COMFYUI_URL")

    # Avatar provider validation
    avatar_provider = os.environ.get("AVATAR_PROVIDER", "kling").lower()
    if avatar_provider == "heygen":
        required_keys += ["HEYGEN_API_KEY", "HEYGEN_AVATAR_ID"]
    else:
        required_keys += ["FAL_API_KEY", "KLING_AVATAR_IMAGE_URL"]

    missing = [k for k in required_keys if not os.environ.get(k)]
    if missing:
        logger.error("Missing required environment variables: %s", ", ".join(missing))
        sys.exit(1)

    config = {
        "anthropic_api_key": os.environ["ANTHROPIC_API_KEY"],
        "elevenlabs_api_key": os.environ["ELEVENLABS_API_KEY"],
        "voice_id": os.environ["ELEVENLABS_VOICE_ID"],
        "comfyui_url": os.environ.get("COMFYUI_URL", ""),  # empty = use RunPod
        "comfyui_api_key": os.environ.get("COMFYUI_API_KEY", ""),
        "ayrshare_api_key": os.environ["AYRSHARE_API_KEY"],
        "telegram_bot_token": os.environ["TELEGRAM_BOT_TOKEN"],
        "telegram_owner_user_id": os.environ["TELEGRAM_OWNER_USER_ID"],
        "niche": os.environ.get("NICHE", "AI & Technology"),
        # RunPod config (used when COMFYUI_URL is not set)
        "runpod_api_key": os.environ.get("RUNPOD_API_KEY", ""),
        "runpod_gpu_type_id": os.environ.get("RUNPOD_GPU_TYPE_ID", "NVIDIA GeForce RTX 4090"),
        "runpod_template_id": os.environ.get("RUNPOD_TEMPLATE_ID", ""),
        "runpod_network_volume_id": os.environ.get("RUNPOD_NETWORK_VOLUME_ID", ""),
        "runpod_comfyui_port": os.environ.get("RUNPOD_COMFYUI_PORT", "8188"),
        # Avatar provider config
        "avatar_provider": os.environ.get("AVATAR_PROVIDER", "kling"),
        "heygen_api_key": os.environ.get("HEYGEN_API_KEY", ""),
        "heygen_avatar_id": os.environ.get("HEYGEN_AVATAR_ID", ""),
        "fal_api_key": os.environ.get("FAL_API_KEY", ""),
        "kling_avatar_image_url": os.environ.get("KLING_AVATAR_IMAGE_URL", ""),
    }

    asyncio.run(CommonCreedPipeline(config).run_daily())
