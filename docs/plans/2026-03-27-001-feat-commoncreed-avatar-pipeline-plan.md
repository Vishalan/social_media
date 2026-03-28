---
date: 2026-03-27
id: 2026-03-27-001
feature: feat-commoncreed-avatar-pipeline
requirements: docs/brainstorms/2026-03-27-commoncreed-content-pipeline-requirements.md
status: completed
---

# CommonCreed AI Avatar Content Pipeline — Implementation Plan

## Source

Requirements: `docs/brainstorms/2026-03-27-commoncreed-content-pipeline-requirements.md`

## Resolved Planning Decisions

| Decision | Resolution |
|----------|------------|
| Video hosting between assembly and Telegram/Ayrshare | Telegram `sendVideo()` API hosts the file inline — no S3/R2 needed. Ayrshare uses multipart file upload (local path), not a public URL. |
| Layout switching logic (R6) | Fixed-ratio: first 3s full-screen hook, middle body half-screen (A-roll bottom / B-roll top), last 3s full-screen CTA |
| Silence trimming implementation (R6) | faster-whisper word-level timestamps (already produced by caption step); no auto-editor dependency |
| Topic deduplication storage (R1) | New `news_items` SQLite table in existing `analytics/tracker.py` DB (existing `posts` table has no `source_url` column) |
| ComfyUI placeholder format (R10) | New EchoMimic V3 workflow uses `{{double-brace}}` to match `ComfyUIClient._substitute_params()` (existing workflows use `{single-brace}` — that is a pre-existing bug, not changed here) |
| Affiliate links source | `config/settings.py` AFFILIATES dict (already exists); topic-matched subset appended to caption string |

## Architecture Overview

```
CommonCreedPipeline (scripts/commoncreed_pipeline.py)
  │
  ├── NewsSourcer          (scripts/news_sourcing/news_sourcer.py)
  │     └── AnalyticsTracker.is_duplicate()  [new method + news_items table]
  │
  ├── ScriptGenerator      (scripts/content_gen/script_generator.py)  [existing, unchanged]
  │
  ├── VoiceGenerator       (scripts/voiceover/voice_generator.py)      [existing, unchanged]
  │
  ├── EchoMimicClient      (scripts/avatar_gen/echomimic_client.py)
  │     └── ComfyUI workflow: comfyui_workflows/echomimic_v3_avatar.json
  │
  ├── ComfyUIClient        (scripts/video_gen/comfyui_client.py)        [existing, unchanged]
  │     └── ComfyUI workflow: comfyui_workflows/broll_generator.json
  │
  ├── VideoEditor          (scripts/video_edit/video_editor.py)
  │
  ├── TelegramApprovalBot  (scripts/approval/telegram_bot.py)
  │
  ├── SocialPoster         (scripts/posting/social_poster.py)           [extended]
  │
  └── AnalyticsTracker     (scripts/analytics/tracker.py)               [extended]
```

All new modules follow the existing convention: one class per sub-package, exported via `__init__.py`, no cross-sub-package imports except through the pipeline orchestrator.

## Implementation Units

### Unit 0 (Spike) — EchoMimic V3 Validation

**Purpose:** Quality and cost gate required before Units 3-8. Do not build the full pipeline until VS1 and VS2 pass.

**Files:** None created. Manual spike on GPU instance.

**Steps:**
1. Provision a RunPod or Vast.ai RTX 4090 instance.
2. Clone `antgroup/EchoMimicV3` and install dependencies (CUDA 12.1+, Python 3.10).
3. Download checkpoints: EchoMimic V3 weights + Wan2.1 1.3B base (already referenced in `deploy/runpod/setup_comfyui.sh`).
4. Record a 10-30s reference video of owner's face (1080p, H.264, neutral background, clear lip movement) per the spec in the requirements doc.
5. Run inference on a 45-second audio clip with the reference video as conditioning input.
6. Score output on three axes (1-5 scale):
   - Lip-sync accuracy
   - Natural motion (no jitter, blending artifacts)
   - Identity consistency (owner's face preserved)
7. Record wall-clock inference time and GPU cost at actual instance rate.
8. Decision gate:
   - Score ≥ 4/5 average AND cost ≤ $2/video → proceed to Unit 1
   - Score < 4/5 OR cost > $2 → evaluate Duix.Avatar (VS3); if also fails, use HeyGen API bridge

**Validation criteria:** ≥ 4/5 average across all three axes on blind review; inference time fits within $2/video budget at target instance rate.

---

### Unit 1 — SQLite: `news_items` Table

**Files:** `scripts/analytics/tracker.py`

**Purpose:** Enable topic deduplication (R1). Existing `posts` table has no `source_url` or `normalized_title` column and must not be altered.

**Changes to `tracker.py`:**

Add to `_create_tables()`:
```python
self.conn.execute("""
    CREATE TABLE IF NOT EXISTS news_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT NOT NULL,
        normalized_title TEXT NOT NULL,
        fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(url)
    )
""")
self.conn.execute(
    "CREATE INDEX IF NOT EXISTS idx_news_items_normalized_title "
    "ON news_items (normalized_title)"
)
self.conn.execute(
    "CREATE INDEX IF NOT EXISTS idx_news_items_fetched_at "
    "ON news_items (fetched_at)"
)
```

Add two new public methods:

```python
def is_duplicate_topic(self, url: str, title: str, window_days: int = 7) -> bool:
    """Return True if this URL or normalized title appeared within window_days."""
    normalized = self._normalize_title(title)
    cutoff = datetime.now() - timedelta(days=window_days)
    row = self.conn.execute(
        """SELECT 1 FROM news_items
           WHERE (url = ? OR normalized_title = ?)
             AND fetched_at >= ?
           LIMIT 1""",
        (url, normalized, cutoff),
    ).fetchone()
    return row is not None

def record_news_item(self, url: str, title: str) -> None:
    """Insert a news item; ignore if URL already present."""
    normalized = self._normalize_title(title)
    self.conn.execute(
        "INSERT OR IGNORE INTO news_items (url, normalized_title) VALUES (?, ?)",
        (url, normalized),
    )
    self.conn.commit()

@staticmethod
def _normalize_title(title: str) -> str:
    import re
    return re.sub(r"[^a-z0-9 ]", "", title.lower()).strip()
```

**Verification:** `AnalyticsTracker(":memory:")` → call `record_news_item` and `is_duplicate_topic` → assert returns True for same URL and normalized title variant.

---

### Unit 2 — News Sourcer

**Files:**
- `scripts/news_sourcing/__init__.py`
- `scripts/news_sourcing/news_sourcer.py`

**Purpose:** Source 2-3 tech news topics/day from RSS feeds (R1). Sanitize, deduplicate, and fall back to Telegram alert if fewer than 2 topics are found.

**`__init__.py`:**
```python
from .news_sourcer import NewsSourcer
__all__ = ["NewsSourcer"]
```

**`NewsSourcer` class:**

```python
class NewsSourcer:
    GOOGLE_NEWS_TECH_RSS = "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtVnVHZ0pWVXlBQlAB"
    HN_TOP_STORIES_API = "https://hacker-news.firebaseio.com/v0/topstories.json"
    HN_ITEM_API = "https://hacker-news.firebaseio.com/v0/item/{}.json"

    MAX_TITLE_LEN = 200
    MAX_SUMMARY_LEN = 1000

    def __init__(self, tracker: AnalyticsTracker, telegram_bot=None, max_topics: int = 3):
        self.tracker = tracker
        self.telegram_bot = telegram_bot  # Optional; used for low-topic alert
        self.max_topics = max_topics

    def fetch(self) -> list[dict]:
        """
        Fetch and return up to max_topics unique tech news topics.
        Each item: {title, url, summary, source}
        Raises InsufficientTopicsError if fewer than 2 unique topics found.
        """
        candidates = []
        candidates.extend(self._fetch_google_news())
        if len(candidates) < self.max_topics:
            candidates.extend(self._fetch_hacker_news())

        unique = []
        for item in candidates:
            if self.tracker.is_duplicate_topic(item["url"], item["title"]):
                continue
            unique.append(item)
            if len(unique) == self.max_topics:
                break

        if len(unique) < 2:
            if self.telegram_bot:
                self.telegram_bot.send_alert(
                    "CommonCreed pipeline: fewer than 2 unique tech topics found today. Skipping generation."
                )
            raise InsufficientTopicsError(f"Only {len(unique)} unique topics found")

        for item in unique:
            self.tracker.record_news_item(item["url"], item["title"])

        return unique

    def _fetch_google_news(self) -> list[dict]:
        import feedparser, html
        feed = feedparser.parse(self.GOOGLE_NEWS_TECH_RSS)
        items = []
        for entry in feed.entries[:20]:
            title = html.unescape(entry.get("title", ""))[:self.MAX_TITLE_LEN]
            url = entry.get("link", "")
            summary = html.unescape(entry.get("summary", ""))[:self.MAX_SUMMARY_LEN]
            if title and url:
                items.append({"title": title, "url": url, "summary": summary, "source": "google_news"})
        return items

    def _fetch_hacker_news(self) -> list[dict]:
        import requests
        try:
            ids = requests.get(self.HN_TOP_STORIES_API, timeout=10).json()[:30]
        except Exception:
            return []
        items = []
        for story_id in ids:
            try:
                story = requests.get(self.HN_ITEM_API.format(story_id), timeout=5).json()
                if story.get("type") != "story" or not story.get("url"):
                    continue
                title = story.get("title", "")[:self.MAX_TITLE_LEN]
                url = story["url"]
                items.append({"title": title, "url": url, "summary": "", "source": "hacker_news"})
                if len(items) >= 10:
                    break
            except Exception:
                continue
        return items


class InsufficientTopicsError(RuntimeError):
    pass
```

**Verification:** Mock feedparser with 3 entries, 2 of which are already in the `news_items` table → assert only 1 returned → assert `InsufficientTopicsError` raised.

---

### Unit 3 — EchoMimic V3 Client + ComfyUI Workflow

**Files:**
- `scripts/avatar_gen/__init__.py`
- `scripts/avatar_gen/echomimic_client.py`
- `comfyui_workflows/echomimic_v3_avatar.json`

**Purpose:** Generate avatar A-roll video from reference footage + voiceover audio (R4).

**`__init__.py`:**
```python
from .echomimic_client import EchoMimicClient
__all__ = ["EchoMimicClient"]
```

**`EchoMimicClient` class:**

```python
class EchoMimicClient:
    WORKFLOW_PATH = Path(__file__).parents[2] / "comfyui_workflows" / "echomimic_v3_avatar.json"

    def __init__(self, comfyui_client: ComfyUIClient, output_dir: str = "output/avatar"):
        self.client = comfyui_client
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def generate(
        self,
        reference_video_path: str,
        audio_path: str,
        output_path: str,
        seed: int | None = None,
    ) -> str:
        """
        Generate an upper-body avatar clip synchronized to audio.
        Returns output_path on success.
        Raises AvatarQualityError if face presence check fails.
        """
        import json, random
        workflow = json.loads(self.WORKFLOW_PATH.read_text())
        params = {
            "reference_video": reference_video_path,
            "audio_path": audio_path,
            "output_path": output_path,
            "seed": seed if seed is not None else random.randint(0, 2**31),
        }
        await self.client.run_workflow(workflow, params, wait_for_completion=True)
        self._check_face_presence(output_path)
        return output_path

    def _check_face_presence(self, video_path: str) -> None:
        """
        Basic face presence check: sample N frames, verify at least one face detected.
        Raises AvatarQualityError if check fails.
        Uses OpenCV Haar cascade (no GPU required for detection step).
        """
        import cv2
        cap = cv2.VideoCapture(video_path)
        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        found = False
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        sample_interval = max(1, frame_count // 10)
        for i in range(0, frame_count, sample_interval):
            cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            ret, frame = cap.read()
            if not ret:
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.1, 4)
            if len(faces) > 0:
                found = True
                break
        cap.release()
        if not found:
            raise AvatarQualityError(f"No face detected in avatar output: {video_path}")


class AvatarQualityError(RuntimeError):
    pass
```

**`comfyui_workflows/echomimic_v3_avatar.json`:**

Skeleton workflow with `{{double-brace}}` placeholders (matches `ComfyUIClient._substitute_params()`):

```json
{
  "1": {
    "inputs": {
      "reference_video": "{{reference_video}}",
      "audio_path": "{{audio_path}}",
      "output_path": "{{output_path}}",
      "seed": "{{seed}}",
      "width": 576,
      "height": 1024,
      "fps": 24,
      "num_frames": -1,
      "cfg": 3.5,
      "steps": 20
    },
    "class_type": "EchoMimicV3Sampler",
    "_meta": { "title": "EchoMimic V3 — Avatar Sampler" }
  },
  "2": {
    "inputs": {
      "images": ["1", 0],
      "filename_prefix": "avatar_"
    },
    "class_type": "SaveVideo",
    "_meta": { "title": "Save Avatar Video" }
  }
}
```

**Note:** The exact node class names and input keys must be adjusted after completing the VS1 spike with the actual EchoMimic V3 ComfyUI node library. The skeleton above captures the required parameters; node wiring is finalized during the spike.

**Retry logic (in pipeline orchestrator, Unit 8):** On `AvatarQualityError`, call `generate()` once more with a new seed before falling back to b-roll-only format.

**Verification:** Mock `ComfyUIClient.run_workflow` to write a synthetic test video; mock `cv2` face detection to return one face → assert `generate()` returns path. Mock no-face case → assert `AvatarQualityError` raised.

---

### Unit 4 — GPU Deploy Script: EchoMimic V3

**Files:**
- `deploy/runpod/setup_echomimic.sh`
- `deploy/vastai/setup_echomimic.sh`

**Purpose:** Bootstrap a fresh GPU instance with EchoMimic V3 dependencies (R11).

**`deploy/runpod/setup_echomimic.sh`:**

```bash
#!/usr/bin/env bash
set -e

ECHOMIMIC_DIR=${ECHOMIMIC_DIR:=/workspace/EchoMimicV3}
MODELS_DIR=${MODELS_DIR:=/workspace/models}
PYTHON=${PYTHON:=python3.10}

echo "=== EchoMimic V3 Setup ==="

# System dependencies
apt-get update -qq
apt-get install -y -qq ffmpeg libgl1-mesa-glx libglib2.0-0

# Clone repo (skip if already present)
if [ ! -d "$ECHOMIMIC_DIR" ]; then
  git clone https://github.com/antgroup/EchoMimicV3.git "$ECHOMIMIC_DIR"
fi
cd "$ECHOMIMIC_DIR"

# Python deps
$PYTHON -m pip install -q -r requirements.txt

# Wan2.1 base weights (shared with existing ComfyUI workflow)
WAN21_PATH="$MODELS_DIR/wan2.1-1.3b"
if [ ! -d "$WAN21_PATH" ]; then
  echo "Downloading Wan2.1 1.3B base weights..."
  mkdir -p "$WAN21_PATH"
  # HuggingFace download — requires HF_TOKEN env var for gated models
  $PYTHON -c "
from huggingface_hub import snapshot_download
snapshot_download('Wan-AI/Wan2.1-T2V-1.3B', local_dir='$WAN21_PATH', token='${HF_TOKEN:-}')
"
fi

# EchoMimic V3 checkpoints
ECHOMIMIC_CKPT="$MODELS_DIR/echomimic_v3"
if [ ! -d "$ECHOMIMIC_CKPT" ]; then
  echo "Downloading EchoMimic V3 checkpoints..."
  mkdir -p "$ECHOMIMIC_CKPT"
  $PYTHON -c "
from huggingface_hub import snapshot_download
snapshot_download('antgroup/EchoMimicV3', local_dir='$ECHOMIMIC_CKPT', token='${HF_TOKEN:-}')
"
fi

echo "=== EchoMimic V3 setup complete ==="
echo "ECHOMIMIC_DIR=$ECHOMIMIC_DIR"
echo "MODELS_DIR=$MODELS_DIR"
```

**`deploy/vastai/setup_echomimic.sh`:** Identical content. Vast.ai and RunPod use the same workspace path convention.

**Note on reference footage security:** The owner's reference video must NOT be bundled in the Docker image or baked into the instance snapshot. It must be uploaded at job time via an authenticated call (e.g., `scp`, RunPod API file upload, or `curl` with a short-lived signed URL), stored in ephemeral instance storage only, and deleted after conditioning is complete. The pipeline orchestrator (Unit 8) is responsible for this upload/delete lifecycle.

**Verification:** Source the script in a dry-run test environment; confirm all paths are guarded by `[ ! -d ]` or `[ ! -f ]` checks; no hardcoded credentials.

---

### Unit 5 — Video Editor

**Files:**
- `scripts/video_edit/__init__.py`
- `scripts/video_edit/video_editor.py`

**Purpose:** Assemble the final 9:16 vertical short from A-roll (avatar) and B-roll clips (R6).

**`__init__.py`:**
```python
from .video_editor import VideoEditor
__all__ = ["VideoEditor"]
```

**`VideoEditor` class:**

```python
class VideoEditor:
    OUTPUT_WIDTH = 1080
    OUTPUT_HEIGHT = 1920
    HOOK_DURATION_S = 3.0   # First N seconds: full-screen avatar
    CTA_DURATION_S = 3.0    # Last N seconds: full-screen avatar

    def __init__(self, output_dir: str = "output/video"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def assemble(
        self,
        avatar_path: str,
        broll_path: str,
        audio_path: str,
        caption_segments: list[dict],
        output_path: str,
    ) -> str:
        """
        Assemble a 9:16 vertical short.

        Layout:
          - [0, HOOK_DURATION_S): full-screen avatar (hook)
          - [HOOK_DURATION_S, total - CTA_DURATION_S): half-screen — B-roll top half, avatar bottom half
          - [total - CTA_DURATION_S, total): full-screen avatar (CTA)

        caption_segments: list of {word, start, end} dicts from faster-whisper.
        Returns output_path.
        """
        from moviepy.editor import (
            VideoFileClip, AudioFileClip, CompositeVideoClip,
            concatenate_videoclips, ColorClip,
        )
        import subprocess, tempfile

        avatar = VideoFileClip(avatar_path).resize((self.OUTPUT_WIDTH, self.OUTPUT_HEIGHT))
        broll = VideoFileClip(broll_path).resize((self.OUTPUT_WIDTH, self.OUTPUT_HEIGHT // 2))
        audio = AudioFileClip(audio_path)
        total_duration = audio.duration

        hook_end = self.HOOK_DURATION_S
        cta_start = max(hook_end, total_duration - self.CTA_DURATION_S)

        # Hook segment: full-screen avatar
        hook = avatar.subclip(0, hook_end)

        # Body segment: B-roll top, avatar bottom
        body_duration = cta_start - hook_end
        body_avatar = (
            avatar.subclip(hook_end, cta_start)
                  .set_position(("center", self.OUTPUT_HEIGHT // 2))
        )
        body_broll = (
            broll.subclip(0, min(body_duration, broll.duration))
                 .loop(duration=body_duration)
                 .set_position(("center", 0))
        )
        body_bg = ColorClip(
            size=(self.OUTPUT_WIDTH, self.OUTPUT_HEIGHT), color=(0, 0, 0), duration=body_duration
        )
        body = CompositeVideoClip([body_bg, body_broll, body_avatar])

        # CTA segment: full-screen avatar
        cta = avatar.subclip(cta_start, min(total_duration, avatar.duration))

        # Concatenate and attach audio
        final = concatenate_videoclips([hook, body, cta]).set_audio(audio)

        # Write intermediate without captions
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name
        final.write_videofile(tmp_path, codec="libx264", audio_codec="aac", fps=24, logger=None)

        # Burn captions via FFmpeg drawtext filter
        caption_filter = self._build_drawtext_filter(caption_segments)
        subprocess.run(
            ["ffmpeg", "-y", "-i", tmp_path, "-vf", caption_filter,
             "-c:a", "copy", output_path],
            check=True, capture_output=True,
        )
        Path(tmp_path).unlink(missing_ok=True)

        return output_path

    def _build_drawtext_filter(self, segments: list[dict]) -> str:
        """
        Build an FFmpeg drawtext filter chain for word-level animated captions.
        Style: bold white text, black outline, centered bottom third.
        Each word fades in at its start timestamp and disappears at its end.
        """
        parts = []
        font_size = 64
        for seg in segments:
            word = seg["word"].replace("'", "\\'").replace(":", "\\:")
            start = seg["start"]
            end = seg["end"]
            parts.append(
                f"drawtext=fontsize={font_size}:fontcolor=white:borderw=3:bordercolor=black"
                f":x=(w-text_w)/2:y=h*0.75"
                f":text='{word}'"
                f":enable='between(t,{start:.3f},{end:.3f})'"
                f":fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            )
        return ",".join(parts) if parts else "null"

    def trim_silence(self, audio_path: str, segments: list[dict], output_path: str) -> str:
        """
        Remove silence using faster-whisper word-level timestamps.
        Copies only speech spans (with 50ms padding) via FFmpeg concat demuxer.
        Returns output_path.
        """
        import subprocess, tempfile
        if not segments:
            import shutil
            shutil.copy2(audio_path, output_path)
            return output_path

        PADDING = 0.05  # seconds
        spans = [(max(0.0, s["start"] - PADDING), s["end"] + PADDING) for s in segments]

        # Merge overlapping spans
        merged = [spans[0]]
        for start, end in spans[1:]:
            if start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            for start, end in merged:
                f.write(f"file '{Path(audio_path).resolve()}'\n")
                f.write(f"inpoint {start:.3f}\n")
                f.write(f"outpoint {end:.3f}\n")
            concat_file = f.name

        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", concat_file, "-c", "copy", output_path],
            check=True, capture_output=True,
        )
        Path(concat_file).unlink(missing_ok=True)
        return output_path
```

**Verification:**
- `assemble()` with 10s test clips → assert output file exists, duration ≈ audio duration, resolution 1080x1920
- `trim_silence()` with synthetic segments → assert output is shorter than input
- `_build_drawtext_filter()` with known segments → assert filter string contains expected `between(t,...)` patterns

---

### Unit 6 — Telegram Approval Bot

**Files:**
- `scripts/approval/__init__.py`
- `scripts/approval/telegram_bot.py`

**Purpose:** Send video previews to owner for approve/reject; enforce sender-ID allowlist; handle auto-reject TTL (R7).

**`__init__.py`:**
```python
from .telegram_bot import TelegramApprovalBot
__all__ = ["TelegramApprovalBot"]
```

**`TelegramApprovalBot` class:**

```python
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

APPROVE_CB = "approve"
REJECT_CB = "reject"
AUTO_REJECT_HOURS = 4


class TelegramApprovalBot:
    def __init__(self, bot_token: str, owner_user_id: int):
        """
        bot_token: Telegram bot token from .env (BotFather)
        owner_user_id: hardcoded integer Telegram user ID — all other IDs are ignored
        """
        from telegram.ext import Application
        self.bot_token = bot_token
        self.owner_user_id = owner_user_id
        self._app = Application.builder().token(bot_token).build()
        self._pending: dict[str, asyncio.Future] = {}  # message_id -> Future[str]

    async def request_approval(
        self,
        video_path: str,
        caption: str,
        topic: str,
        timeout_seconds: int = AUTO_REJECT_HOURS * 3600,
    ) -> str:
        """
        Send video to owner and wait for approve/reject callback.
        Returns "approved" or "rejected".
        Auto-rejects after timeout_seconds with a follow-up notification.
        """
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Approve", callback_data=f"{APPROVE_CB}"),
                InlineKeyboardButton("Reject", callback_data=f"{REJECT_CB}"),
            ]
        ])
        with open(video_path, "rb") as f:
            msg = await self._app.bot.send_video(
                chat_id=self.owner_user_id,
                video=f,
                caption=f"[Review] {topic}\n\n{caption}",
                reply_markup=keyboard,
                supports_streaming=True,
            )

        loop = asyncio.get_event_loop()
        fut: asyncio.Future[str] = loop.create_future()
        self._pending[str(msg.message_id)] = fut

        self._register_callback_handler()
        await self._app.start()

        try:
            result = await asyncio.wait_for(fut, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            logger.warning("No response from owner within %d hours — auto-rejecting topic: %s", AUTO_REJECT_HOURS, topic)
            await self._app.bot.send_message(
                chat_id=self.owner_user_id,
                text=f"Auto-rejected (no response in {AUTO_REJECT_HOURS}h): {topic}",
            )
            result = "rejected"
        finally:
            self._pending.pop(str(msg.message_id), None)
            await self._app.stop()

        return result

    def _register_callback_handler(self) -> None:
        from telegram.ext import CallbackQueryHandler
        if not self._app.handlers:
            self._app.add_handler(CallbackQueryHandler(self._handle_callback))

    async def _handle_callback(self, update, context) -> None:
        """
        Process inline button callbacks.
        Silently ignore any callback not from owner_user_id.
        """
        query = update.callback_query
        if query.from_user.id != self.owner_user_id:
            logger.warning("Ignoring callback from unauthorized user ID: %d", query.from_user.id)
            return

        await query.answer()
        msg_id = str(query.message.message_id)
        fut = self._pending.get(msg_id)
        if fut and not fut.done():
            action = APPROVE_CB if query.data == APPROVE_CB else REJECT_CB
            fut.set_result(action)

    async def send_alert(self, message: str) -> None:
        """Send a plain-text alert to the owner (used for pipeline errors, low-topic warnings)."""
        await self._app.bot.send_message(chat_id=self.owner_user_id, text=message)
```

**Security requirements:**
- `bot_token` sourced from `os.environ["TELEGRAM_BOT_TOKEN"]` — never logged, never committed
- `owner_user_id` hardcoded as integer in `.env` (as `TELEGRAM_OWNER_USER_ID`) — loaded at instantiation
- All callbacks from non-owner IDs are silently ignored (no response sent)

**Verification:**
- Mock `Application.bot.send_video`, inject fake callback with owner ID → assert `request_approval()` returns "approved"
- Inject callback from non-owner ID → assert future not resolved (bot stays waiting)
- Mock timeout → assert returns "rejected" after wait_for fires

---

### Unit 7 — SocialPoster: Affiliate Links + AI Disclosure

**Files:** `scripts/posting/social_poster.py`

**Purpose:** Add affiliate links and platform-specific AI disclosure labels to posts (R8).

**Changes:**

1. Add `_build_caption_with_affiliates(caption, affiliate_links)` private method:

```python
def _build_caption_with_affiliates(
    self, caption: str, affiliate_links: list[str]
) -> str:
    """Append affiliate links to caption, one per line."""
    if not affiliate_links:
        return caption
    links_block = "\n".join(affiliate_links)
    return f"{caption}\n\n{links_block}"
```

2. Add `_ai_disclosure(platform)` private method:

```python
_DISCLOSURES = {
    "instagram": "\n\n[AI-generated content]",
    "tiktok": "\n\n#AIGenerated #SyntheticMedia",
    "youtube": "\n\nThis video contains AI-generated/altered content.",
}

def _ai_disclosure(self, platform: str) -> str:
    return self._DISCLOSURES.get(platform, "")
```

3. Add `affiliate_links: list[str] | None = None` parameter to `post_instagram_reel`, `post_tiktok`, and `post_youtube_video`. In each method, build the final caption as:

```python
final_caption = self._build_caption_with_affiliates(caption, affiliate_links or [])
final_caption += self._ai_disclosure("instagram")  # or "tiktok" / "youtube"
```

4. Update `post_all_short_form` to accept and pass through `affiliate_links`.

**Backward compatibility:** All new parameters have default `None` — existing call sites unaffected.

**Verification:** Call `_build_caption_with_affiliates("Hello", ["https://a.com"])` → assert result contains `"https://a.com"`. Call `post_tiktok` with `affiliate_links=["https://a.com"]` → assert mock API receives caption with link and `#AIGenerated`.

---

### Unit 8 — CommonCreed Pipeline Orchestrator

**Files:** `scripts/commoncreed_pipeline.py`

**Purpose:** Wire all units into a single daily pipeline that sources news, generates 2-3 avatar videos, gets owner approval, and posts (R1-R9).

**Class:**

```python
class CommonCreedPipeline:
    MAX_RETRIES = 1  # One retry on avatar quality failure or owner rejection

    def __init__(self, config: dict):
        """
        config keys (all from environment / config/settings.py):
          elevenlabs_api_key, voice_id, comfyui_url, comfyui_api_key,
          ayrshare_api_key, telegram_bot_token, telegram_owner_user_id,
          reference_video_path, anthropic_api_key, niche
        """
        self.tracker = AnalyticsTracker()
        self.news_sourcer = NewsSourcer(tracker=self.tracker)
        self.script_gen = ScriptGenerator(
            api_provider="anthropic",
            api_key=config["anthropic_api_key"],
            output_dir="output/scripts",
        )
        self.voice_gen = VoiceGenerator(
            api_key=config["elevenlabs_api_key"],
            voice_id=config["voice_id"],
        )
        self.comfyui = ComfyUIClient(
            server_url=config["comfyui_url"],
            api_key=config.get("comfyui_api_key", ""),
        )
        self.echomimic = EchoMimicClient(comfyui_client=self.comfyui)
        self.video_editor = VideoEditor()
        self.telegram = TelegramApprovalBot(
            bot_token=config["telegram_bot_token"],
            owner_user_id=int(config["telegram_owner_user_id"]),
        )
        self.poster = SocialPoster(ayrshare_key=config["ayrshare_api_key"])
        self.reference_video_path = config["reference_video_path"]

    async def run_daily(self) -> None:
        """Fetch topics, generate and approve videos, post all approved."""
        topics = self.news_sourcer.fetch()  # Raises InsufficientTopicsError if < 2
        for topic in topics:
            await self._process_topic(topic)

    async def _process_topic(self, topic: dict) -> None:
        script = self.script_gen.generate_short_form(topic["title"])
        audio_path = await self._generate_voice(script["script"])
        caption_segments = self._transcribe(audio_path)
        trimmed_audio = self.video_editor.trim_silence(audio_path, caption_segments, audio_path + ".trimmed.mp3")

        avatar_path = await self._generate_avatar(trimmed_audio)
        broll_path = await self._generate_broll(script)

        final_video = self.video_editor.assemble(
            avatar_path=avatar_path,
            broll_path=broll_path,
            audio_path=trimmed_audio,
            caption_segments=caption_segments,
            output_path=f"output/video/{topic['title'][:40]}_final.mp4",
        )

        affiliate_links = self._select_affiliates(topic)
        caption = script.get("description", topic["title"])
        decision = await self.telegram.request_approval(
            video_path=final_video,
            caption=caption,
            topic=topic["title"],
        )

        if decision == "rejected":
            # One retry with fresh avatar seed
            logger.info("Owner rejected video for '%s' — retrying with new seed", topic["title"])
            avatar_path = await self._generate_avatar(trimmed_audio, retry=True)
            final_video = self.video_editor.assemble(
                avatar_path=avatar_path,
                broll_path=broll_path,
                audio_path=trimmed_audio,
                caption_segments=caption_segments,
                output_path=f"output/video/{topic['title'][:40]}_retry.mp4",
            )
            decision = await self.telegram.request_approval(
                video_path=final_video,
                caption=caption,
                topic=topic["title"],
            )

        if decision == "approved":
            await self._post_approved(final_video, caption, script.get("tags", []), affiliate_links)
            self.tracker.log_post(
                platform="instagram,tiktok,youtube",
                post_id=topic["url"],
                title=topic["title"],
                description=caption,
            )
        else:
            logger.info("Topic skipped after rejection: %s", topic["title"])

    async def _generate_avatar(self, audio_path: str, retry: bool = False) -> str:
        import random
        seed = random.randint(0, 2**31) if retry else None
        try:
            return await self.echomimic.generate(
                reference_video_path=self.reference_video_path,
                audio_path=audio_path,
                output_path=f"output/avatar/avatar_{seed}.mp4",
                seed=seed,
            )
        except AvatarQualityError:
            if not retry:
                logger.warning("Avatar quality check failed — retrying with new seed")
                return await self._generate_avatar(audio_path, retry=True)
            logger.error("Avatar quality check failed on retry — falling back to b-roll-only")
            await self.telegram.send_alert(
                "Avatar generation failed twice — falling back to b-roll-only format."
            )
            raise  # Caller handles b-roll-only fallback

    async def _generate_broll(self, script: dict) -> str:
        visual_prompt = script.get("visual_cues", script["title"])
        return await self.comfyui.generate_broll(
            image_path=None,
            prompt=visual_prompt,
            output_path="output/video/broll.mp4",
        )

    async def _generate_voice(self, text: str) -> str:
        return await asyncio.to_thread(
            self.voice_gen.generate, text, "output/audio/voice.mp3"
        )

    def _transcribe(self, audio_path: str) -> list[dict]:
        from faster_whisper import WhisperModel
        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(audio_path, word_timestamps=True)
        words = []
        for seg in segments:
            for w in seg.words:
                words.append({"word": w.word.strip(), "start": w.start, "end": w.end})
        return words

    def _select_affiliates(self, topic: dict) -> list[str]:
        from config.settings import AFFILIATES
        # Return up to 3 affiliate links; no topic matching in v1 — return first 3
        links = list(AFFILIATES.values())[:3]
        return links

    async def _post_approved(
        self, video_path: str, caption: str, tags: list[str], affiliate_links: list[str]
    ) -> None:
        await asyncio.to_thread(
            self.poster.post_all_short_form,
            caption=caption,
            video_path=video_path,
            hashtags=tags,
            affiliate_links=affiliate_links,
        )
```

**CLI entry point** (add to `scripts/pipeline.py` Click group or run directly):

```python
# scripts/commoncreed_pipeline.py — bottom of file
if __name__ == "__main__":
    import asyncio, os
    from dotenv import load_dotenv
    load_dotenv()
    config = {
        "anthropic_api_key": os.environ["ANTHROPIC_API_KEY"],
        "elevenlabs_api_key": os.environ["ELEVENLABS_API_KEY"],
        "voice_id": os.environ["ELEVENLABS_VOICE_ID"],
        "comfyui_url": os.environ["COMFYUI_URL"],
        "comfyui_api_key": os.environ.get("COMFYUI_API_KEY", ""),
        "ayrshare_api_key": os.environ["AYRSHARE_API_KEY"],
        "telegram_bot_token": os.environ["TELEGRAM_BOT_TOKEN"],
        "telegram_owner_user_id": os.environ["TELEGRAM_OWNER_USER_ID"],
        "reference_video_path": os.environ["REFERENCE_VIDEO_PATH"],
        "niche": os.environ.get("NICHE", "AI & Technology"),
    }
    asyncio.run(CommonCreedPipeline(config).run_daily())
```

**Verification:**
- Mock all sub-components; call `run_daily()` with 2 topics → assert `post_all_short_form` called twice
- Mock `TelegramApprovalBot.request_approval` returning "rejected" first time then "approved" → assert retry path taken and video posted
- Mock `AvatarQualityError` on first call → assert retry with new seed attempted; if second call also raises, assert `send_alert` called

---

### Unit 9 — Config Updates

**Files:** `.env.example`, `config/settings.py`

**Purpose:** Document new required credentials and configuration keys.

**Add to `.env.example`:**

```bash
# CommonCreed Pipeline
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_OWNER_USER_ID=your_integer_telegram_user_id
REFERENCE_VIDEO_PATH=/path/to/owner_reference.mp4   # Ephemeral; do not commit
COMFYUI_URL=http://localhost:8188
# COMFYUI_API_KEY=optional_if_behind_auth
```

**Add to `config/settings.py`** (in the existing AFFILIATES dict section, ensure it is populated with at least placeholder entries):

```python
# CommonCreed affiliate links — 2-3 per video description
# Replace with actual tracked affiliate URLs before launch
AFFILIATES = {
    "ai_tools": "https://example.com/affiliate/ai-tools",
    "courses": "https://example.com/affiliate/courses",
    "hardware": "https://example.com/affiliate/hardware",
}
```

No changes to existing config keys.

---

## Dependency Map

```
Unit 0 (Spike) ──────────────────────────────── gate for all below
Unit 1 (SQLite) ──► Unit 2 (NewsSourcer)
                 ──► Unit 8 (Pipeline, tracker dependency)
Unit 2 (NewsSourcer) ──► Unit 8
Unit 3 (EchoMimic) ──► Unit 8
Unit 4 (Deploy scripts) — independent, run in parallel with Units 3-7
Unit 5 (VideoEditor) ──► Unit 8
Unit 6 (TelegramBot) ──► Unit 8
Unit 7 (SocialPoster) ──► Unit 8
Unit 9 (Config) — independent, can be done at any point
```

**Recommended build order:** 0 (spike first) → 9 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8

---

## New Python Dependencies

Add to `requirements.txt`:

```
feedparser>=6.0.10
python-telegram-bot>=20.0
faster-whisper>=1.0.0
moviepy>=1.0.3
opencv-python-headless>=4.9.0
huggingface-hub>=0.21.0
```

`ffmpeg` system package (already present in deploy scripts via `apt-get install ffmpeg`).

---

## File Checklist

| # | File | Action |
|---|------|--------|
| 1 | `scripts/analytics/tracker.py` | Extend — add `news_items` table + 2 methods |
| 2 | `scripts/news_sourcing/__init__.py` | Create |
| 3 | `scripts/news_sourcing/news_sourcer.py` | Create |
| 4 | `scripts/avatar_gen/__init__.py` | Create |
| 5 | `scripts/avatar_gen/echomimic_client.py` | Create |
| 6 | `comfyui_workflows/echomimic_v3_avatar.json` | Create (refine after VS1 spike) |
| 7 | `deploy/runpod/setup_echomimic.sh` | Create |
| 8 | `deploy/vastai/setup_echomimic.sh` | Create |
| 9 | `scripts/video_edit/__init__.py` | Create |
| 10 | `scripts/video_edit/video_editor.py` | Create |
| 11 | `scripts/approval/__init__.py` | Create |
| 12 | `scripts/approval/telegram_bot.py` | Create |
| 13 | `scripts/posting/social_poster.py` | Extend — affiliate links + AI disclosure |
| 14 | `scripts/commoncreed_pipeline.py` | Create |
| 15 | `.env.example` | Extend — new credentials |
| 16 | `config/settings.py` | Extend — AFFILIATES dict |

---

## Outstanding Questions

### Resolve Before Work

_(none — all blocking questions were resolved during planning)_

### Deferred to Work

- **[Affects Unit 3][Technical]** Exact EchoMimic V3 ComfyUI node class names and input key names — determine from VS1 spike output or EchoMimic V3 custom node source code. Update `echomimic_v3_avatar.json` accordingly.
- **[Affects Unit 4][Needs research]** Does a RunPod community template for EchoMimic V3 already exist? Check RunPod template library during implementation — if yes, `setup_echomimic.sh` may only need to install project-specific additions.
- **[Affects Unit 5][Technical]** `VideoEditor._build_drawtext_filter` uses DejaVu font path (`/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf`). Verify this path exists on both local dev machine and GPU cloud instances; add fallback to a bundled font if not.
- **[Affects Unit 7][Technical]** Instagram AI label — the Ayrshare API parameter for Instagram AI-generated content disclosure (may be a specific `labels` field rather than caption text). Check Ayrshare docs at implementation time.
- **[Affects Unit 8][Technical]** `ComfyUIClient.generate_broll` is currently a stub (returns output_path immediately without calling ComfyUI). This must be addressed either by implementing it in the existing client or calling `run_workflow` directly from the pipeline.

## Next Steps

→ Run `/ce:work` to implement Unit 0 (validation spike) first, then proceed sequentially through Units 1-9.
