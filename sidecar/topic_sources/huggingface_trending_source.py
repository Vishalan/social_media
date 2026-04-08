"""
Hugging Face trending topic source — pulls trending models and spaces
from the public HF API. No credentials required.

Two endpoints are queried in parallel-ish (sequentially via one client):
- /api/models?sort=trending  — trending models
- /api/spaces?sort=trending  — trending demo apps

Failures on one endpoint don't kill the other (per-query isolation), and
any total failure returns ``([], label)`` rather than raising.

Settings knobs (all optional):
- ``HUGGINGFACE_MAX_ITEMS``      — cap on merged output (default 20)
- ``HUGGINGFACE_MIN_DOWNLOADS``  — drop low-signal models (default 1000)
- ``HUGGINGFACE_MIN_LIKES``      — drop low-signal spaces (default 5)
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

_MODELS_URL = "https://huggingface.co/api/models?sort=trendingScore&direction=-1&limit=20"
_SPACES_URL = "https://huggingface.co/api/spaces?sort=likes7d&direction=-1&limit=20"


class HuggingFaceTrendingTopicSource:
    name = "huggingface_trending"

    def is_configured(self, settings: Any) -> bool:
        # Public API — always available.
        return True

    def fetch_items(self, settings: Any) -> tuple[list[dict], str]:
        label = f"{self.name}@{datetime.utcnow().isoformat(timespec='seconds')}Z"

        try:
            import httpx
        except ImportError as exc:
            logger.warning("huggingface source: httpx not available: %s", exc)
            return [], label

        max_items = int(getattr(settings, "HUGGINGFACE_MAX_ITEMS", 20) or 20)
        min_downloads = int(getattr(settings, "HUGGINGFACE_MIN_DOWNLOADS", 1000) or 0)
        min_likes = int(getattr(settings, "HUGGINGFACE_MIN_LIKES", 5) or 0)

        items: list[dict] = []
        any_success = False

        try:
            with httpx.Client(timeout=10.0) as client:
                # --- models ---
                try:
                    r = client.get(_MODELS_URL)
                    if r.status_code == 200:
                        any_success = True
                        for m in r.json() or []:
                            model_id = (m.get("id") or "").strip()
                            if not model_id:
                                continue
                            downloads = int(m.get("downloads") or 0)
                            if downloads < min_downloads:
                                continue
                            likes = int(m.get("likes") or 0)
                            pipeline_tag = m.get("pipeline_tag") or "general-purpose"
                            items.append(
                                {
                                    "title": f"New trending HF model: {model_id}",
                                    "url": f"https://huggingface.co/{model_id}",
                                    "summary": (
                                        f"{downloads} downloads, {likes} likes. "
                                        f"{pipeline_tag}. Trending on Hugging Face."
                                    ),
                                    "source": self.name,
                                }
                            )
                    else:
                        logger.warning(
                            "huggingface source: models HTTP %d", r.status_code
                        )
                except Exception as exc:
                    logger.info("huggingface source: models fetch failed: %s", exc)

                # --- spaces ---
                try:
                    r = client.get(_SPACES_URL)
                    if r.status_code == 200:
                        any_success = True
                        for s in r.json() or []:
                            space_id = (s.get("id") or "").strip()
                            if not space_id:
                                continue
                            likes = int(s.get("likes") or 0)
                            if likes < min_likes:
                                continue
                            sdk = s.get("sdk") or "custom"
                            items.append(
                                {
                                    "title": f"Trending HF Space: {space_id}",
                                    "url": f"https://huggingface.co/spaces/{space_id}",
                                    "summary": (
                                        f"{likes} likes. {sdk}. "
                                        f"Demo app trending on Hugging Face."
                                    ),
                                    "source": self.name,
                                }
                            )
                    else:
                        logger.warning(
                            "huggingface source: spaces HTTP %d", r.status_code
                        )
                except Exception as exc:
                    logger.info("huggingface source: spaces fetch failed: %s", exc)
        except Exception as exc:
            logger.warning("huggingface source: fetch failed: %s", exc)
            return [], label

        if not any_success:
            logger.warning("huggingface source: both endpoints failed")
            return [], label

        items = items[:max_items]
        logger.info("huggingface source: returning %d items", len(items))
        return items, label
