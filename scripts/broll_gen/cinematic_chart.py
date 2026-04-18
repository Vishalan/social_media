"""B-roll type: ``cinematic_chart`` — Remotion-rendered chart clip (Unit C2).

Thin Python client for the ``commoncreed_remotion`` sidecar (see
``deploy/remotion/src/server.ts``). When a topic carries a structured
``chart_spec`` (extracted upstream by :func:`extract_chart_spec` or populated
by the pipeline from another source) and the ``CINEMATIC_CHART_ENABLED`` env
flag is set, the selector prefers this type. The generator POSTs the spec to
the sidecar's ``/render`` endpoint and returns the rendered MP4 path.

The sidecar writes its output under a shared ``commoncreed_output`` Docker
volume, so the path returned from ``/render`` is already readable by the
Python pipeline — no file copy is needed. The ``output_path`` argument on
``generate()`` is accepted for interface compatibility with
:class:`~broll_gen.base.BrollBase` but is not used to steer the sidecar's
write path (the sidecar allocates a collision-free path itself).

Chart spec shapes
-----------------

The three supported template IDs (matching ``deploy/remotion/src/render.ts``
and ``deploy/remotion/src/index.tsx``) and their ``props`` shape:

* ``bar_chart``      — ``{title, bars: [{label, value, suffix?}]}``
* ``number_ticker``  — ``{label, start, end, prefix?, suffix?}``
* ``line_chart``     — ``{title, x_label, y_label, points: [[x, y], ...]}``

``extract_chart_spec`` uses Claude Haiku to decide whether a given script has
the numeric density to benefit from an animated chart; it returns ``None``
when no structured comparison is present. The extractor is intentionally
conservative — emitting only when the template, props, and target duration
can be filled deterministically.
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Any, Optional

import httpx

from .base import BrollBase, BrollError

if TYPE_CHECKING:  # pragma: no cover
    from commoncreed_pipeline import VideoJob


logger = logging.getLogger(__name__)


# ─── Constants ───────────────────────────────────────────────────────────────

# Sidecar service name inside the docker-compose network; HOST override lets
# local dev point at a machine-local Remotion server.
_DEFAULT_REMOTION_URL = "http://commoncreed_remotion:3030"
_RENDER_PATH = "/render"

# Render timeout — Remotion cold-start + one chart is typically < 30s; we give
# generous headroom for the worst case (first render after a bundle warmup
# failure, large line_chart, high-fps encoding).
_RENDER_TIMEOUT_S = 120.0

_VALID_TEMPLATE_IDS = frozenset({"bar_chart", "number_ticker", "line_chart"})

# Env flag that gates this type end-to-end. Both the selector and the
# generator itself check it — even if the selector were bypassed, generating
# with the flag off would surface a clean BrollError rather than silently
# taxing the sidecar.
ENV_FLAG = "CINEMATIC_CHART_ENABLED"


# ─── Helpers ─────────────────────────────────────────────────────────────────


def is_enabled() -> bool:
    """Return True when ``CINEMATIC_CHART_ENABLED`` is truthy in the env."""
    return os.environ.get(ENV_FLAG, "false").lower() == "true"


def _resolve_remotion_url() -> str:
    """Pick the Remotion sidecar base URL from the env, falling back to the
    docker-compose service name. Trailing slashes are stripped."""
    url = os.environ.get("REMOTION_SIDECAR_URL", _DEFAULT_REMOTION_URL)
    return url.rstrip("/")


# ─── Chart spec extraction (Haiku) ───────────────────────────────────────────


_EXTRACT_SYSTEM_PROMPT = """\
You decide whether a short-form video script contains a structured numeric
comparison or trend worth animating as a chart.

Return JSON matching the response schema:
  - If the script has 2+ comparable numbers (e.g. "GPT-5 at 92, GPT-4 at 78"),
    a single dramatic value to count up ("82 tokens/sec"), or a trend across
    time ("throughput grew from 10 to 90 over four quarters") — fill in the
    ``chart_spec`` with the best-fitting template and its props.
  - Otherwise, set ``chart_spec`` to null. Err on the side of null for purely
    narrative scripts without concrete numbers.

Templates:
  - bar_chart     — two or more labelled bars to compare magnitudes.
  - number_ticker — one headline number to count up from start to end.
  - line_chart    — ordered (x, y) points showing a trend.

Props per template:
  - bar_chart:     {title, bars: [{label, value, suffix?}, ...]}
  - number_ticker: {label, start, end, prefix?, suffix?}
  - line_chart:    {title, x_label, y_label, points: [[x, y], ...]}

Pick a ``target_duration_s`` between 3 and 8 seconds that matches the drama
of the numbers. Keep titles <= 40 chars and labels <= 18 chars.\
"""


_EXTRACT_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "chart_spec": {
            "oneOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "properties": {
                        "template": {
                            "type": "string",
                            "enum": ["bar_chart", "number_ticker", "line_chart"],
                        },
                        "props": {
                            "type": "object",
                            "additionalProperties": True,
                        },
                        "target_duration_s": {"type": "number"},
                    },
                    "required": ["template", "props", "target_duration_s"],
                    "additionalProperties": False,
                },
            ]
        }
    },
    "required": ["chart_spec"],
    "additionalProperties": False,
}


async def extract_chart_spec(
    anthropic_client: Any,
    script_text: str,
    topic: Optional[dict] = None,
) -> Optional[dict]:
    """Ask Claude Haiku whether a script warrants an animated chart.

    Args:
        anthropic_client: ``AsyncAnthropic``-compatible client with
            ``messages.create`` exposing ``output_config`` JSON-schema mode.
        script_text: The voiceover script (typically the first ~1500 chars
            suffice; the caller may pre-trim).
        topic: Optional ``{title, url}``-shaped dict for extra context.

    Returns:
        ``{template, props, target_duration_s}`` dict when the script has a
        real numeric comparison, or ``None`` for purely narrative text. On any
        exception the function returns ``None`` — the chart path is strictly
        optional and must never break the surrounding selector.
    """
    if not script_text or not script_text.strip():
        return None

    topic_title = (topic or {}).get("title", "") if isinstance(topic, dict) else ""
    user_msg = (
        f"Topic: {topic_title}\n\n"
        f"Script:\n{script_text[:1500]}\n\n"
        "Decide whether a chart would add real value here. Return "
        "chart_spec=null unless there are concrete numbers to animate."
    )

    try:
        response = await anthropic_client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=512,
            system=_EXTRACT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
            output_config={
                "format": {
                    "type": "json_schema",
                    "schema": _EXTRACT_RESPONSE_SCHEMA,
                }
            },
        )
        raw = response.content[0].text
        data = json.loads(raw)
        spec = data.get("chart_spec")
        if not spec:
            return None
        template = spec.get("template")
        if template not in _VALID_TEMPLATE_IDS:
            logger.warning(
                "extract_chart_spec: unknown template %r — discarding", template,
            )
            return None
        if not isinstance(spec.get("props"), dict):
            return None
        try:
            target = float(spec.get("target_duration_s", 0))
        except (TypeError, ValueError):
            return None
        if target <= 0:
            return None
        return {
            "template": template,
            "props": spec["props"],
            "target_duration_s": target,
        }
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("extract_chart_spec: Haiku call failed (%s)", exc)
        return None


# ─── Generator ───────────────────────────────────────────────────────────────


class CinematicChartGenerator(BrollBase):
    """Render an animated chart via the Remotion sidecar.

    The generator is a thin HTTP client. It reads ``job.chart_spec`` (shape:
    ``{template, props, target_duration_s}``), POSTs it to the sidecar's
    ``/render`` endpoint, and returns the MP4 path the sidecar wrote inside
    the shared ``commoncreed_output`` volume.

    Args:
        base_url: Remotion sidecar base URL. Defaults to the
            ``REMOTION_SIDECAR_URL`` env var, falling back to
            ``http://commoncreed_remotion:3030`` (the docker-compose service
            name).
        timeout_s: HTTP timeout for the render call. Remotion bundling is
            done once at server startup, so each render is a pure
            ``renderMedia`` pass — 120s is generous.

    Raises:
        BrollError: When ``job.chart_spec`` is missing or malformed, when the
            env flag is not set, when the sidecar returns a non-200 response,
            or when the HTTP call times out / errors.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout_s: float = _RENDER_TIMEOUT_S,
    ) -> None:
        self._base_url = (base_url or _resolve_remotion_url()).rstrip("/")
        self._timeout_s = float(timeout_s)

    async def generate(
        self,
        job: "VideoJob",
        target_duration_s: float,
        output_path: str,
    ) -> str:
        if not is_enabled():
            raise BrollError(
                f"cinematic_chart disabled: set {ENV_FLAG}=true to enable"
            )

        spec = getattr(job, "chart_spec", None)
        if not spec:
            raise BrollError(
                "cinematic_chart requires job.chart_spec "
                "({template, props, target_duration_s})"
            )
        if not isinstance(spec, dict):
            raise BrollError(
                f"cinematic_chart: job.chart_spec must be a dict; got {type(spec).__name__}"
            )

        template_id = spec.get("template")
        if template_id not in _VALID_TEMPLATE_IDS:
            raise BrollError(
                f"cinematic_chart: unknown template {template_id!r}; "
                f"allowed: {sorted(_VALID_TEMPLATE_IDS)}"
            )
        props = spec.get("props")
        if not isinstance(props, dict):
            raise BrollError("cinematic_chart: chart_spec.props must be a dict")

        # Prefer the caller's target_duration_s (derived from audio length)
        # but fall back to the spec's own preference when the caller passes 0.
        effective_duration = float(target_duration_s) or float(
            spec.get("target_duration_s", 0.0)
        )
        if effective_duration <= 0:
            raise BrollError(
                "cinematic_chart: target_duration_s must be > 0"
            )

        audio_url = getattr(job, "audio_url", "") or None
        payload = {
            "template_id": template_id,
            "props": props,
            "audio_url": audio_url,
            "target_duration_s": effective_duration,
        }

        url = f"{self._base_url}{_RENDER_PATH}"
        logger.info(
            "CinematicChartGenerator: POST %s (template=%s, target=%.1fs)",
            url, template_id, effective_duration,
        )

        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                response = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise BrollError(
                f"remotion render timed out after {self._timeout_s:.0f}s: {exc}"
            ) from exc
        except httpx.HTTPError as exc:
            raise BrollError(f"remotion render request failed: {exc}") from exc

        if response.status_code != 200:
            # The sidecar returns JSON bodies with an ``error`` field for both
            # 4xx (validation) and 5xx (render failure). Surface the raw text
            # so callers see the real reason (spec diff, bundle error, etc.).
            raise BrollError(
                f"remotion render failed: HTTP {response.status_code} — {response.text}"
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise BrollError(
                f"remotion render returned non-JSON 200 response: {response.text[:200]}"
            ) from exc

        mp4_path = body.get("output_path")
        if not mp4_path or not isinstance(mp4_path, str):
            raise BrollError(
                f"remotion render response missing output_path: {body}"
            )

        logger.info(
            "CinematicChartGenerator: wrote %s (render_time_ms=%s)",
            mp4_path, body.get("render_time_ms"),
        )
        return mp4_path
