"""Avatar, design, b-roll and assembly stages.

Split from pipeline.py to keep each file readable; these are mixin methods
attached to ShortsPipeline at import time.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .branding import BRAND
from .config import ShortsConfig
from .pipeline import ShortsError, ShortsPipeline

from .net import BROWSER_UA as _UA

logger = logging.getLogger(__name__)


def height_for_panel(cfg) -> int:
    """Panel height for the active layout."""
    return cfg.content_height if cfg.layout == "half_stacked" else cfg.height



# ---------------------------------------------------------------- avatar
def render_avatar(self: ShortsPipeline, *, force: bool = False) -> str:
    """Render one LatentSync segment per narration segment, then join.

    Each segment is trimmed back to its audio's exact frame count before
    concatenation. LatentSync returns ~2 frames more than it is given; per
    segment that is harmless, but across six segments it compounded to 0.48s
    of drift — the mouth running ahead of the words by the final beat. That is
    the `avatar-lip-sync-desync-across-segments` failure, and it is why the
    trim is not optional.
    """
    cfg = self.cfg
    final = cfg.path("avatar_full.mp4")
    if os.path.exists(final) and not force:
        logger.info("avatar_full.mp4 exists — reusing")
        return final

    if cfg.avatar_mode == "hold":
        # A stand-in of exactly the narration's length. Everything downstream
        # — spans, layout, captions, thumbnail frame — works off this file's
        # duration and geometry, so it has to match both or the timeline it
        # feeds is not the one that will ship.
        dur = self._dur(cfg.path("vo_master.wav"))
        logger.warning("AVATAR ON HOLD — %.2fs stand-in instead of LatentSync. "
                       "Set avatar_mode='render' to ship.", dur)

        # A LABELLED stand-in, not black.
        #
        # Black is indistinguishable from a failed render, and it is the state
        # a reviewer sees most often — the hold path exists precisely so the
        # rest of the video can be judged without paying 35 minutes for lip
        # sync. Every frame the reviewer looks at should say what it is, and
        # a moving progress bar also makes it obvious the timeline is running
        # rather than stalled.
        from .placeholder import card
        card(final, width=cfg.width, height=cfg.height, fps=cfg.fps,
             duration_s=dur, label="PRESENTER — NOT RENDERED",
             detail="LatentSync lip sync over the gesture library",
             cost="avatar_mode=hold  ~22s compute per second")
        return final

    from avatar_gen.gesture_library import (
        GestureLibrary, GestureLibraryError, load_windows_from_manifest)

    segments = [tuple(x) for x in self._load("segments.json")]
    lib = GestureLibrary(source=cfg.gesture_source,
                         windows=load_windows_from_manifest(cfg.gesture_manifest),
                         output_dir=cfg.path("gesture"))
    need = sum(e - s for s, e in segments)
    if need > lib.total_usable_s:
        logger.warning(
            "Need %.2fs of footage but only %.2fs is usable — clips will be "
            "reused and may read as looped. Film more.", need, lib.total_usable_s)

    trimmed = []
    for i, (start, end) in enumerate(segments):
        dur = end - start
        tag = cfg.segment_tags[i] if i < len(cfg.segment_tags) else "moderate"
        seg_wav = cfg.path(f"seg{i}_16k.wav")
        self._sh("ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}",
                 "-t", f"{dur:.3f}", "-i", cfg.path("vo_master.wav"),
                 "-ac", "1", "-ar", "16000", seg_wav)
        try:
            clip = lib.cut(dur, prefer_tag=tag, name=f"{cfg.run_id}_seg{i}")
        except GestureLibraryError as exc:
            raise ShortsError(f"no footage for segment {i} ({dur:.2f}s): {exc}") from exc

        self._sh("docker", "cp", seg_wav,
                 f"commoncreed_latentsync:/app/work/{cfg.run_id}_s{i}.wav")
        self._sh("docker", "cp", clip,
                 f"commoncreed_latentsync:/app/work/{cfg.run_id}_d{i}.mp4")
        res = self._post(f"{cfg.latentsync_endpoint}/lipsync", {
            "video_path": f"/app/work/{cfg.run_id}_d{i}.mp4",
            "audio_path": f"/app/work/{cfg.run_id}_s{i}.wav",
            "output_filename": f"{cfg.run_id}_seg{i}.mp4",
            "inference_steps": cfg.inference_steps,
            "guidance_scale": cfg.guidance_scale,
            "seed": cfg.seed,
        }, timeout=5400)
        raw = cfg.path(f"avatar_seg{i}.mp4")
        self._sh("docker", "cp",
                 f"commoncreed_latentsync:/app/output/{cfg.run_id}_seg{i}.mp4", raw)
        logger.info("seg%d: %.2fs rendered in %.0fs (%.1fs per second of video)",
                    i, dur, res["generation_ms"] / 1000,
                    res["generation_ms"] / 1000 / dur)

        frames = int(round(dur * cfg.fps))
        cut = cfg.path(f"avatar_seg{i}_trim.mp4")
        self._sh("ffmpeg", "-v", "error", "-y", "-i", raw, "-vf",
                 f"select='lt(n\\,{frames})',setpts=N/{cfg.fps}/TB",
                 "-r", str(cfg.fps), "-c:v", "libx264", "-crf", "17",
                 "-pix_fmt", "yuv420p", "-an", cut)
        trimmed.append(cut)

    listing = cfg.path("avatar_concat.txt")
    Path(listing).write_text("".join(f"file '{p}'\n" for p in trimmed))
    self._sh("ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
             "-i", listing, "-r", str(cfg.fps), "-c:v", "libx264", "-crf", "17",
             "-pix_fmt", "yuv420p", "-an", final)
    logger.info("Avatar: %.3fs vs audio %.3fs (drift %+.3fs)",
                self._dur(final), need, self._dur(final) - need)
    return final


# ---------------------------------------------------------------- design
async def render_designs(self: ShortsPipeline, script: dict, *,
                         force: bool = False) -> list[dict]:
    cfg = self.cfg
    if self._done("designs.json") and not force:
        logger.info("designs.json exists — reusing")
        return self._load("designs.json")

    # max_designs <= 0 means the stage is OFF, not "plan zero graphics". It
    # previously ran anyway and then failed the whole pipeline with
    # "intelligence layer returned no briefs" — a disabled stage must skip, and
    # skipping has to be cheap because designed graphics now come from the
    # director's Remotion compositions instead.
    if cfg.max_designs <= 0:
        logger.info("Design stage off (max_designs=0) — graphics come from the "
                    "director's Remotion compositions")
        self._save("designs.json", [])
        return []

    from design import DesignBrief, DesignBriefGenerator, HyperFramesRenderer

    vi = script["visual_identity"]
    source_with_identity = (
        f"{script['title']}\n\n{script['description']}\n\n"
        f"VISUAL IDENTITY CHOSEN FOR THIS PIECE:\n"
        f"palette: {vi['palette']}\ntypography: {vi['typography']}\n"
        f"motifs available: {vi['motifs']}\nrationale: {vi['rationale']}\n"
        f"Each graphic should be built from ONE of these motifs; say which in 'motion'."
    )
    briefs = await DesignBriefGenerator(self.llm).generate(
        source_text=source_with_identity, script=script["script"],
        source_kind="article", max_briefs=cfg.max_designs)

    if cfg.layout == "pip_circle":
        reserved = ("the LOWER-LEFT region: a circle of diameter 34% of frame "
                    "width whose bounding box spans x 5%-39% and y 60%-79%. "
                    "Keep it empty.")
    else:
        # Stacked: the graphic owns its whole canvas, which is landscape-ish
        # rather than vertical. Composing for a tall frame here wastes the
        # sides and pushes content out of the panel.
        reserved = ("none — you own the whole canvas. Note it is roughly 1:1, "
                    "NOT a tall 9:16 frame: compose for a squarish panel.")
    style = {
        "palette": ", ".join(vi["palette"]),
        "typography": vi["typography"],
        "motifs": "; ".join(vi["motifs"]),
        "identity_rationale": vi["rationale"],
        "register": "editorial, borrowed from the source's own product surface",
        "reserved_zone": reserved,
        "background": vi["palette"][0] if vi["palette"] else "#0A0C10",
        "accent": vi["palette"][2] if len(vi["palette"]) > 2 else "#22D3EE",
        "muted": vi["palette"][-1] if vi["palette"] else "#A8B8C5",
    }
    # Render at the CONTENT PANEL's aspect, not the full frame. Designs were
    # composed for 1080x1920 and then cropped to the 1080x998 panel, which cut
    # them in half — the SKILL.md graphic lost its own title. A graphic that
    # knows its real canvas composes for it.
    panel_h = cfg.content_height if cfg.layout == "half_stacked" else cfg.height
    from .vision import review_design
    renderer = HyperFramesRenderer(
        output_dir=cfg.design_dir, work_dir=cfg.path("design_work"),
        width=cfg.width, height=panel_h, fps=cfg.fps, style=style,
        model=cfg.intelligence_model, timeout_s=cfg.design_timeout_s,
        reviewer=review_design if cfg.review_designs else None,
        max_attempts=cfg.design_attempts)
    results = await renderer.render_all(briefs, concurrency=cfg.design_concurrency)
    self._save("designs.json", results)
    return results



def _pick_regions(self: ShortsPipeline, url: str, panel_h: int):
    """Choose which page regions illustrate which narration beats.

    Without this the clips are an even walk down the page, which puts the
    commit list under narration about the file format. Returns None on any
    failure so the caller falls back to the even spread rather than losing
    b-roll entirely.
    """
    cfg = self.cfg
    try:
        from .pageroll import capture_page, detect_regions
        from .vision import make_region_thumbs, select_regions

        png = os.path.join(cfg.broll_dir, "page.png")
        capture_page(url, png)
        regions = detect_regions(png, panel_aspect=panel_h / cfg.width)
        if len(regions) < 2:
            return None
        thumbs = make_region_thumbs(png, regions,
                                    os.path.join(cfg.work_dir, "regions"))
        script = self._load("script.json")["script"]
        caps = self._load("captions.json")
        # Sample the narration at even points as stand-in beats; each becomes
        # "what is being said around here".
        n = min(cfg.broll_max_clips, len(regions))
        cues = caps["cues"]
        beats = []
        for i in range(n):
            idx = int(len(cues) * (i + 0.5) / n)
            s0, e0, _ = cues[max(0, min(idx, len(cues) - 1))]
            text = " ".join(c[2] for c in cues[max(0, idx - 2):idx + 3])
            beats.append({"start": s0, "end": e0, "text": text})

        matches = select_regions(thumbs=thumbs, script=script, beats=beats,
                                 work_dir=cfg.work_dir,
                                 model=cfg.intelligence_model)
        if not matches:
            return None
        return [m["region"] for m in sorted(matches, key=lambda m: m["beat"])]
    except Exception as exc:                       # noqa: BLE001 — optional
        logger.warning("smart region selection failed (%s) — using even spread",
                       str(exc)[:160])
        return None


# ---------------------------------------------------------------- b-roll
async def fetch_broll(self: ShortsPipeline, queries: list[str], *,
                      url: str = "", force: bool = False) -> list[dict]:
    """Supply non-presenter footage via the configured provider.

    Default is page-roll: capture the actual source page and travel over it.
    Stock search is retained but off by default — see ShortsConfig.broll_provider
    for why.
    """
    cfg = self.cfg
    if self._done("broll.json") and not force:
        return self._load("broll.json")
    if not cfg.broll_enabled or cfg.broll_provider == "none":
        self._save("broll.json", [])
        return []

    # Content only ever occupies the top panel in a stacked layout, so render
    # at that height rather than full-frame and cropping resolution away.
    h = cfg.content_height if cfg.layout == "half_stacked" else cfg.height

    if cfg.broll_provider == "director":
        return await _direct_broll(self, url=url, height=h)

    if cfg.broll_provider == "pageroll":
        from .pageroll import build_rolls
        if not url:
            logger.warning("page-roll requested but the source has no URL — "
                           "skipping b-roll")
            self._save("broll.json", [])
            return []
        pick = _pick_regions(self, url, h) if cfg.smart_regions else None
        rolls = build_rolls(url, cfg.broll_dir, count=cfg.broll_max_clips,
                            duration=cfg.broll_clip_s, width=cfg.width,
                            height=cfg.height, fps=cfg.fps, half_height=h,
                            pick=pick)
        out = [{"path": r.path, "duration": r.duration, "kind": r.kind,
                "region": r.region, "source": r.source_url} for r in rolls]
        self._save("broll.json", out)
        return out

    return _fetch_stock(self, queries, height=h)



async def _direct_broll(self: ShortsPipeline, *, url: str,
                        height: int) -> list[dict]:
    """Plan and render a varied b-roll slate via the director.

    Unlike the page-roll provider, these clips carry their OWN start times:
    the director places each one on the beat it illustrates rather than
    wherever a gap happens to fall. The assembler therefore treats them as
    placed content, the same as designed graphics.
    """
    cfg = self.cfg
    from .broll_director import BrollDirector, DirectorError

    script = self._load("script.json")
    caps = self._load("captions.json")
    cues = caps["cues"]
    if not cues:
        self._save("broll.json", [])
        return []

    # Sample beats across the narration. Each beat carries the words spoken
    # around it, which is what the director reads to choose a type.
    #
    # Beat COUNT is derived from how long the narration actually is, not from
    # the clip cap. Using the cap meant beats were spread evenly across the
    # whole video however long it was: on a 56s narration, 5 beats put the
    # anchors 14s apart, so the director could not place a visual more often
    # than that even when it had something worth showing. Density is a function
    # of duration; the cap is a budget. Conflating them made the budget dictate
    # the pacing.
    narr_s = max(cues[-1][1] - cues[0][0], 1.0)
    n = int(round(narr_s / max(cfg.broll_cadence_s, 1.0)))
    n = max(3, min(n, cfg.broll_max_designed))
    logger.info("Sampling %d b-roll beats across %.1fs of narration "
                "(~one per %.1fs)", n, narr_s, narr_s / n)
    beats = []
    for i in range(n):
        idx = int(len(cues) * (i + 0.5) / n)
        idx = max(0, min(idx, len(cues) - 1))
        beats.append({
            "start": round(cues[idx][0], 2),
            "duration": cfg.broll_clip_s,
            "narration": " ".join(c[2] for c in cues[max(0, idx - 3):idx + 4]),
        })

    src_text = ""
    src_path = cfg.path("source.txt")
    if os.path.exists(src_path):
        src_text = Path(src_path).read_text()

    d = BrollDirector(
        intelligence=self.llm, work_dir=cfg.broll_dir,
        width=cfg.width, height=height, fps=cfg.fps,
        palette=(script.get("visual_identity") or {}).get("palette") or [],
        source_url=url, source_text=src_text,
        source_title=script.get("title", ""),
        allow_ai_video=cfg.ai_video_enabled,
        h3_budget=cfg.h3_max_per_video if cfg.h3_enabled else 0,
        fullscreen_kinds=cfg.fullscreen_kinds,
        frame_height=cfg.height)

    d.max_card_share = cfg.max_card_share
    d.h3_placeholder = cfg.placeholder_slow_stages
    d.h3_gen_size = cfg.h3_gen_size
    d.h3_steps = cfg.h3_steps

    # The mark that goes ON the graphics is the SUBJECT's, not the publisher's.
    # Getting this backwards is what put the TechCrunch logo on a story about X:
    # the publication reported it, X is what it is about. The publisher survives
    # only as an attribution line on quoted source text.
    try:
        from .sourcebrand import fetch_subject_brand, icon_data_uri
        subject = fetch_subject_brand(
            script.get("subject_domains") or [], cfg.broll_dir)
        d.subject_icon = icon_data_uri(subject.get("icon"))
        if subject.get("domain"):
            logger.info("Graphics will wear the %s mark", subject["domain"])

        # Typography follows the subject too, not just colour.
        #
        # The real brand face is nearly always proprietary and cannot be
        # embedded, so this matches its CATEGORY with a licensed one — a
        # geometric sans for a geometric brand, a didone for an editorial
        # one. The classification runs through the same model that writes the
        # script, because a font NAME carries almost no signal on its own:
        # "Anthropic Serif" is legible, "TwitterChirp" is not.
        try:
            from . import typeface as _tf

            async def _ask_font(prompt: str) -> str:
                r = await self.llm.messages.create(
                    model=cfg.intelligence_model, max_tokens=40,
                    messages=[{"role": "user", "content": prompt}])
                return r.content[0].text

            faces = await _tf.resolve(
                script.get("subject_domains") or [], ask=_ask_font)
            _install_faces(faces)
        except Exception as exc:                    # noqa: BLE001 — cosmetic
            logger.info("typeface unresolved (%s) — staying on the house face",
                        str(exc)[:100])
    except Exception as exc:                       # noqa: BLE001 — optional
        logger.info("no subject mark available: %s", str(exc)[:100])
    # A card built from the source's own mark, used as frame zero of any
    # generated clip. Verified on a real generation: the supplied image IS the
    # first frame and its colours carry through, so the scene inherits the
    # story's palette instead of defaulting to generic teal.
    if cfg.h3_enabled and cfg.h3_brand_first_frame and url:
        try:
            from .sourcebrand import fetch_subject_brand, build_brand_card
            brand = fetch_subject_brand(
                script.get("subject_domains") or [], cfg.broll_dir)
            d.h3_first_frame = build_brand_card(
                out_png=os.path.join(cfg.broll_dir, "brand_card.png"),
                icon=brand.get("icon"),
                palette=(script.get("visual_identity") or {}).get("palette") or [],
                size=cfg.h3_gen_size)
        except Exception as exc:                   # noqa: BLE001 — optional
            logger.warning("brand first frame unavailable (%s) — the generated "
                           "clip will start from noise", str(exc)[:120])

    try:
        slots = await d.plan(beats, max_slots=cfg.broll_max_designed,
                             max_per_kind=cfg.broll_max_per_kind)

        # Decide full-frame HERE, before anything renders.
        #
        # The budget used to be applied at assembly, long after the director
        # had already rendered every eligible kind at 1080x1920. When the
        # budget ran out the assembler logged "stays in the panel" and dropped
        # a 1920-tall clip into a ~998 panel, which cropped the top 470px off —
        # taking the title with it. The clip was flawless; it was measured for
        # a frame it was never given.
        #
        # A render size is downstream of a layout decision, so the decision has
        # to come first.
        total = sum(s.duration for s in slots) or 1.0
        budget = total * cfg.fullscreen_max_share
        used = 0.0
        for s in slots:
            eligible = s.kind in set(cfg.fullscreen_kinds)
            s.fullscreen = eligible and used + s.duration <= budget
            if s.fullscreen:
                used += s.duration
            elif eligible:
                logger.info("  %s renders at panel size — full-frame budget "
                            "spent (%.1fs of %.1fs)", s.kind, used, budget)

        slots = await d.render_all(slots, concurrency=cfg.design_concurrency)
    except DirectorError as exc:
        logger.warning("director failed (%s) — falling back to page-roll", exc)
        cfg.broll_provider = "pageroll"
        return await fetch_broll(self, [], url=url, force=True)

    out = [{"path": s.path, "duration": s.duration, "kind": s.kind,
            "start": s.start, "why": s.why, "error": s.error,
            "fullscreen": bool(getattr(s, "fullscreen", False))}
           for s in slots if s.path]
    self._save("broll.json", out)
    logger.info("Director b-roll: %d clips — %s", len(out),
                ", ".join(x["kind"] for x in out))
    return out


def _fetch_stock(self: ShortsPipeline, queries: list[str], *,
                 height: int) -> list[dict]:
    """Keyword stock search. Kept for sources with no capturable page."""
    cfg = self.cfg
    key = os.environ.get("PEXELS_API_KEY", "")
    if not key:
        logger.warning("PEXELS_API_KEY not set — skipping stock b-roll")
        self._save("broll.json", [])
        return []

    # Delegates to `stock`, which owns the Pexels contract. This function
    # keeps a different job: assembling a whole SLATE as a fallback when the
    # director cannot run at all, where `stock.fetch` serves one planned slot.
    # The endpoint, the auth header and the Cloudflare user-agent workaround
    # were duplicated here; one of them will always be the stale one.
    from .stock import search as _stock_search

    def search(q: str) -> dict:
        return {"videos": _stock_search(q, limit=5)}

    out: list[dict] = []
    for i, q in enumerate(queries[:cfg.broll_max_clips]):
        try:
            vids = search(q).get("videos", [])
        except Exception as exc:
            logger.warning("Pexels search failed for %r: %s", q, exc)
            continue
        if not vids:
            continue
        v = vids[0]
        files = sorted([f for f in v["video_files"] if f.get("height")],
                       key=lambda f: abs(f["height"] - cfg.height))
        if not files:
            continue
        raw = os.path.join(cfg.broll_dir, f"raw_{i}.mp4")
        req = urllib.request.Request(files[0]["link"], headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=120) as r, open(raw, "wb") as f:
            f.write(r.read())
        clip = os.path.join(cfg.broll_dir, f"broll_{i}.mp4")
        self._sh("ffmpeg", "-v", "error", "-y", "-t", str(cfg.broll_clip_s),
                 "-i", raw, "-vf",
                 f"scale={cfg.width}:{height}:force_original_aspect_ratio=increase,"
                 f"crop={cfg.width}:{height},fps={cfg.fps}",
                 "-an", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", clip)
        out.append({"query": q, "path": clip, "duration": self._dur(clip),
                    "kind": "stock", "author": v.get("user", {}).get("name", "")})
        logger.info("stock b-roll %d: %r", i, q)
    self._save("broll.json", out)
    return out


# -------------------------------------------------------------- assembly
def assemble(self: ShortsPipeline, *, force: bool = False) -> str:
    """Cut the timeline into spans and render each in its layout."""
    cfg = self.cfg
    final = cfg.path(f"{cfg.run_id}.mp4")
    if os.path.exists(final) and not force:
        return final

    from video_edit.layouts import LayoutSpec, composite

    caps = self._load("captions.json")
    designs = self._load("designs.json")
    broll = self._load("broll.json")
    script_meta = self._load("script.json")
    dur = self._load("timings.json")["duration"]
    words = caps["words"]

    av = cfg.path("avatar_1080.mp4")
    if not os.path.exists(av):
        self._sh("ffmpeg", "-v", "error", "-y", "-i", cfg.path("avatar_full.mp4"),
                 "-vf", f"scale={cfg.width}:{cfg.height}:flags=lanczos", "-an",
                 "-c:v", "libx264", "-crf", "17", "-pix_fmt", "yuv420p", av)

    placed: list[dict] = []
    design_paths = set()
    for d in designs:
        if not d.get("path"):
            continue
        anchor = d["anchor_word"].lower().strip(".,!?")
        # Anchor against ALIGNED words: they carry script spellings, so an
        # anchor like "Crepezzi" matches even when Whisper heard "Kropedzy".
        hit = next((w for w in words
                    if w["word"].lower().strip(".,!?:;") == anchor), None) \
            or next((w for w in words if anchor in w["word"].lower()), None)
        if hit is None:
            logger.warning("Design %r dropped — anchor %r not in narration",
                           d["slug"], anchor)
            continue
        L = self._dur(d["path"])
        placed.append({"t": max(2.5, hit["start"] - 0.25), "len": L,
                       "path": d["path"], "slug": d["slug"]})
        design_paths.add(d["path"])

    placed.sort(key=lambda x: x["t"])
    for i in range(1, len(placed)):
        prev = placed[i - 1]
        if placed[i]["t"] < prev["t"] + prev["len"] + 0.4:
            placed[i]["t"] = prev["t"] + prev["len"] + 0.4
    # A clip that runs past the end gets SLID EARLIER, not dropped. Dropping was
    # silent, and it threw away the most expensive item in the build: a
    # window_scene planned onto a late beat simply never appeared in the video,
    # with nothing in the log to say so.
    kept = []
    for q in placed:
        if q["t"] + q["len"] <= dur - 0.3:
            kept.append(q)
            continue
        latest = dur - 0.3 - q["len"]
        clash = any(not (latest + q["len"] <= a or latest >= z)
                    for a, z in [(x["t"], x["t"] + x["len"]) for x in kept])
        if latest > 0.5 and not clash:
            logger.info("  %s slid %.2fs -> %.2fs to fit before the end",
                        q["slug"], q["t"], latest)
            q["t"] = latest
            kept.append(q)
        else:
            logger.warning("  %s dropped: %.2fs + %.2fs runs past %.2fs and "
                           "there is no free slot earlier", q["slug"], q["t"],
                           q["len"], dur)
    placed = kept
    busy = [(p["t"], p["t"] + p["len"]) for p in placed]

    for b in broll:
        # Use the clip's OWN duration. Capping at cfg.broll_clip_s silently
        # truncated the types that need a build — a mechanism diagram rendered
        # at 4.5s was played for 2.6s, cutting the flow off before it resolved,
        # which is the whole content of that type.
        L = b["duration"]
        # A director clip knows which beat it illustrates; honour that start and
        # only slide it when it would collide. A page-roll clip has no opinion,
        # so it is placed in the first free slot.
        t = float(b.get("start", 3.0))
        t = max(2.5, t)
        guard = 0
        while t < dur - 1.0 and guard < 200 and not all(
                t + L <= a - 0.4 or t >= z + 0.4 for a, z in busy):
            t += 0.5
            guard += 1
        if t + L <= dur - 0.5:
            placed.append({"t": t, "len": L, "path": b["path"],
                           "slug": b.get("kind") or os.path.basename(b["path"]),
                           "full": bool(b.get("fullscreen"))})
            busy.append((t, t + L))

    # THE CALL TO ACTION gets its own card, placed where it is spoken.
    #
    # A keyword CTA that is only spoken is a CTA nobody completes: the viewer
    # hears "comment ALGORITHM", does not know how it is spelled, and scrolls.
    # The word has to be on screen while the line is said.
    cta_text = (script_meta.get("cta") or "").strip()
    if cta_text:
        cta_words = [w for w in _norm_words(cta_text)][:4]
        hit = _find_word_run(words, cta_words)
        if hit is None:
            logger.info("CTA %r not found in the narration — no card placed",
                        cta_text[:48])
        else:
            c_start, c_end = hit
            c_len = max(2.6, c_end - c_start + 1.1)
            try:
                from . import remotion_client
                cta_path = os.path.join(cfg.broll_dir, "cta.mp4")
                remotion_client.render(
                    kind="cta",
                    props={"action": cta_text,
                           "keyword": (script_meta.get("cta_keyword") or "").strip(),
                           "kicker": "want the link?"
                                     if script_meta.get("cta_keyword") else ""},
                    out_path=cta_path, duration_s=c_len,
                    width=cfg.width, height=height_for_panel(cfg), fps=cfg.fps,
                    palette=(script_meta.get("visual_identity") or {}).get("palette") or [])
                # The CTA outranks whatever else wanted this moment.
                placed = [q for q in placed
                          if q["t"] + q["len"] <= c_start or q["t"] >= c_start + c_len]
                placed.append({"t": max(0.0, c_start - 0.15), "len": c_len,
                               "path": cta_path, "slug": "cta"})
                # The CTA card SPEAKS. It sets the ask in its own typography —
                # "Comment astra and I will send you the full safety report" —
                # so a caption over it repeats the same words in a second
                # typeface, and the display tier repeats them larger still. A
                # frame carrying one sentence twice reads as a mistake, and it
                # lands on the one shot that has to convert.
                design_paths.add(cta_path)
                logger.info("CTA card at %.2fs (+%.2fs): %s", c_start, c_len,
                            cta_text[:60])
            except Exception as exc:              # noqa: BLE001 — optional
                logger.warning("CTA card failed: %s", str(exc)[:140])

    placed.sort(key=lambda x: x["t"])
    for p in placed:
        logger.info("  content %-26s %6.2fs +%.2fs", p["slug"], p["t"], p["len"])

    # Gap filling: the presenter must never occupy the whole frame. Any span
    # without a designed graphic gets source page-roll in the content panel,
    # cycling through the captured bands so consecutive gaps are different
    # parts of the page rather than the same header repeated.
    # Only clips that were NOT already placed may fill a gap. Every director
    # clip carries its own start time and is placed above, so feeding the same
    # list in here replayed designed graphics as filler — the viewer sees the
    # same stats card twice in one video, which reads as a rendering bug rather
    # than a callback. Page-roll clips have no start of their own and are the
    # legitimate filler.
    already = {p["path"] for p in placed}
    gap_fill = ([b["path"] for b in broll
                 if b.get("path") and b["path"] not in already]
                if cfg.fill_gaps_with_pageroll else [])
    gap_i = 0
    last_broll_end = -99.0

    spans, cursor = [], 0.0

    def add_gap(start: float, end: float) -> None:
        """Fill a gap between designed graphics.

        Page footage is spent sparingly. A gap gets it only if the gap is long
        enough to be worth a cut, enough time has passed since the last one,
        and there is unused footage left. Otherwise the presenter holds the
        content panel — a held shot of the person talking is not dead air, but
        five webpage cutaways in a row make the page the subject of the video.
        """
        nonlocal gap_i, last_broll_end
        length = end - start
        if length <= 0.25:
            return
        worth_it = (gap_fill
                    and gap_i < len(gap_fill)
                    and length >= cfg.min_gap_for_broll_s
                    and start - last_broll_end >= cfg.min_broll_spacing_s)
        if worth_it:
            clip_len = min(cfg.broll_clip_s, length)
            mid = start + (length - clip_len) / 2
            if mid > start + 0.2:
                _add_presenter(start, mid)
            spans.append({"mode": "content", "start": mid, "end": mid + clip_len,
                          "content": gap_fill[gap_i]})
            if end > mid + clip_len + 0.2:
                _add_presenter(mid + clip_len, end)
            gap_i += 1
            last_broll_end = mid + clip_len
        else:
            _add_presenter(start, end)

    def _add_presenter(start: float, end: float) -> None:
        """Emit presenter spans, subdividing anything that would hold too long.

        A presenter span shows the page drifting in the content panel. Drift
        alone is not enough over a long stretch: measured on the previous build,
        a single 10.32s presenter span read as one continuous shot, and neither
        reference short holds any shot beyond ~3s.

        Subdividing produces a genuine cut, because each chunk starts at a
        different depth in the page (the panel's start depth is derived from the
        span index). So a 10s hold becomes three ~3.4s views of three different
        parts of the source rather than one slow crawl — the cadence comes from
        material already captured, with no extra planning or render cost.

        This is deliberately the LAST resort for cadence. A designed graphic is
        better than another view of the page; this only covers the stretches the
        director left on the presenter.
        """
        length = end - start
        if length <= 0.25:
            return
        limit = max(cfg.max_static_hold_s, 1.0)
        n = max(1, math.ceil(length / limit))
        step = length / n
        if n > 1:
            logger.info("  splitting a %.2fs presenter hold into %d views "
                        "of %.2fs", length, n, step)
        for k in range(n):
            # Alternate: stacked, then full frame, then stacked.
            #
            # Every presenter beat full-frame would lose the panel that
            # carries the source material, and none of them full-frame caps
            # the cut rate at what half a frame can express. Alternating
            # gives every boundary a whole-frame change on one side of it.
            nonlocal_full = cfg.presenter_full_enabled and (len(spans) % 2 == 1)
            spans.append({"mode": "presenter_full" if nonlocal_full else "presenter",
                          "start": start + k * step,
                          "end": start + (k + 1) * step})

    # OPEN ON CONTENT, not on the presenter.
    #
    # Both reference shorts open on their strongest visual — Musk speaking, the
    # product hero shot — with the presenter secondary. Ours opened on whatever
    # frame the camera happened to be on at t=0, which in the last build was a
    # dark, downward-looking frame. If the first placement starts late, pull it
    # to the top of the video.
    if placed and placed[0]["t"] > 1.2:
        first = min(placed, key=lambda x: x["t"])
        shift = first["t"]
        first["t"] = 0.0
        logger.info("Opening on %s (pulled from %.2fs) so the video does not "
                    "start on the presenter", first["slug"], shift)
        placed.sort(key=lambda x: x["t"])
        busy = [(q["t"], q["t"] + q["len"]) for q in placed]

    # Cap how much of the video the presenter can be absent from. Full-frame
    # graphics are a change of scale, not a replacement for the face.
    full_budget = dur * cfg.fullscreen_max_share
    full_used = 0.0
    full_shown = 0
    for p in placed:
        add_gap(cursor, p["t"])
        as_full = bool(p.get("full")) and full_used + p["len"] <= full_budget
        if p.get("full") and not as_full:
            logger.info("  %s stays in the panel — full-frame budget spent "
                        "(%.1fs of %.1fs)", p["slug"], full_used, full_budget)
        if as_full:
            full_used += p["len"]
        # Alternate the two full-frame treatments rather than using one.
        #
        # Every full-frame graphic removing the presenter entirely meant the
        # video swung between exactly two compositions — presenter-in-the-
        # lower-half, and no presenter at all — which reads as a template
        # being filled in. Alternating in a round PIP keeps a person on screen
        # over the graphic and gives the edit a third shape.
        if as_full:
            mode = "content_full" if full_shown % 2 == 0 else "content_pip"
            full_shown += 1
        else:
            mode = "content"
        spans.append({"mode": mode,
                      "start": p["t"], "end": p["t"] + p["len"],
                      "content": p["path"]})
        cursor = p["t"] + p["len"]
    add_gap(cursor, dur)

    span_dir = cfg.path("spans")
    Path(span_dir).mkdir(exist_ok=True)

    # A single held frame of the source page for presenter-led spans.
    #
    # This must not depend on the b-roll provider having captured a page. It
    # previously did, and with the director (which does not always use pageroll)
    # no page.png existed, so every presenter span fell through to FULL FRAME —
    # silently violating the rule that the avatar is never full-screen. Capture
    # it here if nothing else has.
    still_panel = ""
    page_png = os.path.join(cfg.broll_dir, "page.png")
    # Read once, up front. This used to be read inside the "no page.png yet"
    # branch, so on a resumed run — where the capture already exists — the name
    # was never bound and the reader page below died on an unbound local.
    source_url = ""
    # Whether the page may be SHOWN. If fetching it did not yield the article's
    # text, a picture of that same page is not evidence either — it is whatever
    # blocked the fetch. Bloomberg returned a "PRESS & HOLD / SUBSCRIBE NOW"
    # bot check, and that interstitial went into a finished video as b-roll
    # while the narration talked about an IPO.
    page_is_usable = True
    meta_path = cfg.path("source_meta.json")
    if os.path.exists(meta_path):
        try:
            _meta = json.loads(Path(meta_path).read_text())
            source_url = _meta.get("url", "")
            page_is_usable = bool(_meta.get("fetched", True))
        except (json.JSONDecodeError, OSError):
            source_url = ""
    if not page_is_usable:
        logger.info("The source page did not yield its own text, so it will "
                    "not be shown either — no page capture, no page panel")
    if (cfg.fill_gaps_with_pageroll and page_is_usable
            and not os.path.exists(page_png)
            and source_url):
        try:
            from .pageroll import capture_page
            capture_page(source_url, page_png)
        except Exception as exc:                   # noqa: BLE001 — optional
            logger.warning("panel still capture failed: %s", str(exc)[:140])

    # The tall image the panel drifts over for presenter-led spans.
    #
    # A rendered READER page, not the publisher's page. The real capture put an
    # Oracle advert, a "Most Popular" rail and a podcast promo carrying an
    # unrelated stock headshot into the panel, recurring because the drift
    # revisits the same tall image. Removing that in the DOM proved unreliable:
    # on this TechCrunch page an embedded podcast transcript lives inside the
    # same wrapper as the article, directly above the headline, and two attempts
    # produced a clean capture of the WRONG article.
    #
    # The evidence types (highlight, annotate, macro) still use the real page —
    # there the point is that the claim is visible on the publisher's own site,
    # and each crops tightly onto a located phrase so furniture never enters
    # frame. This bed only has to be relevant, on-brand and legible.
    page_panel_src = ""
    # The reader page needs an ARTICLE behind it. Its whole premise is that the
    # camera drifts over a long page and settles on one region, which only
    # reads as "here is the part that matters" when there is a page to pick a
    # part OUT of. Given a 400-character newsletter blurb it renders the entire
    # source at once — four sentences of body copy filling the panel, which is
    # precisely the wall of small text this project has spent its whole life
    # removing. Below the floor the pull-quote bed handles the gaps instead:
    # one sentence, large, which is the right treatment for a short source.
    src_chars = 0
    try:
        src_chars = len(Path(cfg.path("source.txt")).read_text())
    except OSError:
        pass
    if cfg.fill_gaps_with_pageroll and src_chars < cfg.reader_page_min_chars:
        logger.info("Source is %d chars (floor %d) — skipping the reader page; "
                    "gaps get pull-quote beds instead",
                    src_chars, cfg.reader_page_min_chars)
    elif cfg.fill_gaps_with_pageroll:
        reader_png = os.path.join(cfg.broll_dir, "reader.png")
        if not os.path.exists(reader_png):
            src_txt = cfg.path("source.txt")
            try:
                from .pageroll import build_reader_png
                build_reader_png(
                    title=script_meta.get("title", "") or "",
                    text=Path(src_txt).read_text(),
                    out_png=reader_png,
                    kicker=(urllib.parse.urlparse(source_url).netloc
                            .replace("www.", "") if source_url else "SOURCE"),
                    palette=(script_meta.get("visual_identity") or {}
                             ).get("palette") or [])
            except Exception as exc:               # noqa: BLE001 — optional
                logger.warning("reader page failed (%s) — falling back to the "
                               "raw page capture", str(exc)[:140])
        if os.path.exists(reader_png):
            page_panel_src = reader_png
        elif page_is_usable and os.path.exists(page_png):
            page_panel_src = page_png

    # Paragraph rectangles for framing. Only available for the reader page —
    # the raw capture has no sidecar, and the panel falls back to plain drift.
    reader_paras: list[dict] = []
    if page_panel_src.endswith("reader.png"):
        from .pageroll import reader_paragraphs
        reader_paras = reader_paragraphs(page_panel_src,
                                         target_width=cfg.width)
        logger.info("Panel will frame %d source paragraphs in turn",
                    len(reader_paras))
    para_cursor = 0

    if cfg.fill_gaps_with_pageroll and page_is_usable and os.path.exists(page_png):
        still_panel = os.path.join(span_dir, "panel_still.png")
        ph = cfg.content_height if cfg.layout == "half_stacked" else cfg.height
        try:
            self._sh("ffmpeg", "-v", "error", "-y", "-i", page_png,
                     "-vf", (r"crop=iw:min(ih\," + f"iw*{ph}/{cfg.width}"
                             + r"):0:0," + f"scale={cfg.width}:{ph}"),
                     "-frames:v", "1",
                     still_panel)
        except ShortsError:
            still_panel = ""
    # The bed for presenter-led spans: ONE sentence from the source, rendered
    # as a designed pull-quote.
    #
    # It used to be a live crop of a rendered reader page — four paragraphs of
    # equal-weight body copy at once, clipped top and bottom. Nothing was
    # emphasised, so nothing was the focal point and there was nowhere for the
    # eye to land; the paragraph the panel was nominally framing was cut through
    # the middle of its first line. Same content, but a graphic instead of a
    # screenshot.
    bed_clips: list = []
    n_presenter = sum(1 for sp in spans if sp["mode"] == "presenter")
    if n_presenter and cfg.fill_gaps_with_pageroll:
        try:
            from .sources import pull_sentences
            from .pageroll import _strip_boilerplate
            from . import remotion_client

            from .sourcebrand import fetch_brand, icon_data_uri

            src_text = Path(cfg.path("source.txt")).read_text()
            clean = _strip_boilerplate(src_text, script_meta.get("title", ""))
            brand = fetch_brand(source_url, cfg.broll_dir)
            attribution = brand["domain"] or "source"
            icon_uri = icon_data_uri(brand.get("icon"))
            pulls = pull_sentences(clean, n_presenter)
            # A short source yields fewer pull-quotes than there are presenter
            # spans, and the surplus spans then had no panel content at all —
            # so they fell through to a FULL-FRAME avatar, which this layout
            # explicitly does not do. A 400-character blurb has four sentences
            # and can easily face six spans, so this is the normal case for
            # pasted input rather than an edge one.
            #
            # Cycling the pulls is the lesser evil: the treatment rotates
            # (quote / marked / statement) so a repeated sentence is at least
            # differently dressed, whereas breaking the layout rule is visible
            # instantly and looks like the panel failed to render.
            n_spans = len([x for x in spans if x["mode"] == "presenter"])
            if pulls and len(pulls) < n_spans:
                logger.info("Only %d pull-quote(s) for %d presenter span(s) — "
                            "cycling them so no span goes full-frame",
                            len(pulls), n_spans)
                pulls = [pulls[i % len(pulls)] for i in range(n_spans)]
            # Cycle the treatment: the bed appears once per presenter span, so a
            # single template repeated eight times reads as wallpaper.
            variants = ("quote", "marked", "statement")
            palette = (script_meta.get("visual_identity") or {}).get("palette") or []
            bed_dir = os.path.join(cfg.broll_dir, "bed")
            for k, pull in enumerate(pulls):
                span = [x for x in spans if x["mode"] == "presenter"][k]
                out_bed = os.path.join(bed_dir, f"bed_{k:02d}.mp4")
                try:
                    remotion_client.render(
                        kind="source_pull",
                        props={"sentence": pull["sentence"],
                               "attribution": attribution,
                               "emphasis": pull["emphasis"],
                               "icon": icon_uri,
                               "variant": variants[k % len(variants)]},
                        out_path=out_bed,
                        duration_s=max(2.0, span["end"] - span["start"]),
                        width=cfg.width, height=height_for_panel(cfg),
                        fps=cfg.fps, palette=palette)
                    bed_clips.append(out_bed)
                except Exception as exc:            # noqa: BLE001 — optional
                    logger.warning("bed clip %d failed: %s", k, str(exc)[:120])
            logger.info("Bed: %d source pull-quotes rendered", len(bed_clips))
        except Exception as exc:                    # noqa: BLE001 — optional
            logger.warning("pull-quote bed unavailable (%s) — falling back to "
                           "the page panel", str(exc)[:140])

    bed_i = 0
    pres_shot = 0
    parts = []
    for i, sp in enumerate(spans):
        L = sp["end"] - sp["start"]
        seg = os.path.join(span_dir, f"av_{i:02d}.mp4")

        # REFRAME the presenter on every span, so a split is an actual cut.
        #
        # Splitting a long presenter hold into three spans changed only the
        # panel above it: the bottom half stayed one continuous take, so scene
        # detection found no cut across the whole stretch and the measured
        # longest shot was 10.04s. A reference short of the same length holds
        # nothing longer than 3.84s and averages 1.43s. A split that produces
        # no visual change is not an edit.
        #
        # Cycling framings gives each span a real one. The sequence alternates
        # rather than escalating, because three progressively tighter shots in
        # a row read as one slow zoom; wide-close-medium-close reads as
        # coverage cut together. Numbers are the crop's share of frame width,
        # kept above 0.82 so the head never crops.
        _FRAMINGS = (
            (1.00, 0.00),      # as shot
            (0.86, -0.04),     # punch in, sitting slightly high
            (0.93, 0.02),      # medium
            (0.82, -0.02),     # closest
        )
        _is_pres = sp["mode"] in ("presenter", "presenter_full")
        fz, fy = _FRAMINGS[pres_shot % len(_FRAMINGS)] if _is_pres else (1.00, 0.0)
        if _is_pres:
            pres_shot += 1
        if fz >= 0.999:
            self._sh("ffmpeg", "-v", "error", "-y", "-ss", f"{sp['start']:.3f}",
                     "-t", f"{L:.3f}", "-i", av, "-an", "-c:v", "libx264",
                     "-crf", "17", "-pix_fmt", "yuv420p", seg)
        else:
            self._sh("ffmpeg", "-v", "error", "-y", "-ss", f"{sp['start']:.3f}",
                     "-t", f"{L:.3f}", "-i", av, "-an",
                     "-vf", (f"crop=iw*{fz}:ih*{fz}:(iw-iw*{fz})/2:"
                             f"(ih-ih*{fz})/2+ih*{fy},"
                             f"scale={cfg.width}:-2,"
                             f"crop={cfg.width}:ih"),
                     "-c:v", "libx264", "-crf", "17", "-pix_fmt", "yuv420p", seg)
        out = os.path.join(span_dir, f"sp_{i:02d}.mp4")
        if sp["mode"] == "presenter":
            # Presenter-led span: the content panel shows the source page,
            # drifting slowly rather than frozen.
            #
            # It used to be a single held frame, on the reasoning that a moving
            # panel competes with the person speaking. That is true for a
            # two-second span and false for a long one: measured on the previous
            # build, three presenter spans ran 4.5s, 5.1s and 7.0s with a frozen
            # screenshot on top, and scene detection found no cut across the
            # whole 7s. Neither reference short holds ANY shot that long. A
            # frozen frame does not read as calm, it reads as a stall.
            #
            # The drift is deliberately slower than the page-roll b-roll type —
            # this is a bed, not the subject — and consecutive presenter spans
            # start at different depths so they are not the same view twice.
            # No extra webpage is introduced: the panel was already the page.
            ct = os.path.join(span_dir, f"ct_{i:02d}.mp4")
            if bed_i < len(bed_clips):
                # A rendered pull-quote is already the panel's exact geometry
                # and its own animation, so it is looped/trimmed to the span and
                # used as-is rather than being cropped or drifted.
                self._sh("ffmpeg", "-v", "error", "-y", "-stream_loop", "-1",
                         "-i", bed_clips[bed_i], "-t", f"{L:.3f}", "-an",
                         "-c:v", "libx264", "-crf", "17", "-pix_fmt", "yuv420p",
                         ct)
                bed_i += 1
            elif page_panel_src:
                ph = cfg.content_height if cfg.layout == "half_stacked" else cfg.height
                # Frame ON a paragraph and highlight it, advancing to a
                # different paragraph each time.
                #
                # Three earlier versions drifted at an arbitrary depth: first a
                # frozen frame, then a slow travel, then alternating wide/tight
                # views. Each looked better than the last and none produced a
                # detectable cut, because consecutive views of the same column of
                # body text are near-identical whatever the offset. Framing a
                # specific paragraph fixes both halves of the problem — the view
                # is unmistakably new because the highlight moves with it, and
                # the eye is told which sentence to read instead of being asked
                # to scan a moving wall of text.
                # STRIDE through the article rather than walking it in order.
                #
                # Adjacent paragraphs sit adjacent in the column, so their crop
                # windows overlap by most of the panel height: consecutive views
                # shared ~80% of their pixels and read as one continuous shot,
                # leaving a 9.64s stretch with no visible change. Striding lands
                # each successive view in a different part of the piece, so the
                # frame genuinely turns over. The stride is coprime-ish with the
                # count so every paragraph is still visited before any repeats.
                if reader_paras:
                    n_par = len(reader_paras)
                    stride = max(2, n_par // 4)
                    while stride > 2 and math.gcd(stride, n_par) != 1:
                        stride -= 1
                    pidx = (para_cursor * stride) % n_par
                    para_cursor += 1
                else:
                    pidx = -1
                if pidx >= 0:
                    pr = reader_paras[pidx]
                    # Align to the paragraph's TOP edge with a small pad, rather
                    # than centring it. Centring meant the frame always opened on
                    # the tail of the previous paragraph, usually clipped through
                    # the middle of a line, which reads as a rendering fault. A
                    # paragraph gap at the top edge reads as a deliberate margin,
                    # and a long paragraph is then readable from its first word.
                    y0 = max(0, int(pr["y"] - 44))
                    travel = int(ph * 0.10)
                    speed = travel / max(L, 0.5)
                    y_expr = f"min(max(ih-{ph}\\,0)\\,{y0}+{speed:.2f}*t)"
                    # The highlight: an accent bar down the left of the
                    # paragraph, wiping in over the first third of the span, plus
                    # a faint tint behind it. Drawn AFTER the crop so the
                    # coordinates are panel-relative.
                    hy = max(0, pr["y"] - y0)
                    wipe = max(0.35, L / 3.0)
                    accent = _panel_accent(script_meta)
                    boxes = (
                        f",drawbox=x=0:y={hy}:w=10:"
                        f"h='min({pr['h']}\\,{pr['h']}*t/{wipe:.2f})':"
                        f"color={accent}@0.95:t=fill"
                        f",drawbox=x=18:y={hy}:w=iw-18:h={pr['h']}:"
                        f"color={accent}@0.10:t=fill"
                    )
                else:
                    y0 = int(ph * 0.55) * (1 + (i % 3))
                    speed = int(ph * 0.30) / max(L, 0.5)
                    y_expr = f"min(max(ih-{ph}\\,0)\\,{y0}+{speed:.2f}*t)"
                    boxes = ""
                self._sh("ffmpeg", "-v", "error", "-y", "-loop", "1",
                         "-framerate", str(cfg.fps), "-t", f"{L:.3f}",
                         "-i", page_panel_src,
                         "-vf", (f"scale={cfg.width}:-2:flags=lanczos,"
                                 f"crop={cfg.width}:min(ih\\,{ph}):0:'{y_expr}',"
                                 f"scale={cfg.width}:{ph}{boxes},"
                                 f"format=yuv420p"),
                         "-frames:v", str(max(2, int(L * cfg.fps))),
                         "-c:v", "libx264", "-crf", "18",
                         "-pix_fmt", "yuv420p", ct)
            if not os.path.exists(ct) and still_panel:
                # Drift unavailable (no full-page capture) — a held frame is
                # still far better than a full-frame presenter.
                self._sh("ffmpeg", "-v", "error", "-y", "-loop", "1",
                         "-framerate", str(cfg.fps), "-t", f"{L:.3f}",
                         "-i", still_panel, "-c:v", "libx264", "-crf", "18",
                         "-pix_fmt", "yuv420p", ct)
            if os.path.exists(ct):
                composite(content=ct,
                          avatar=seg, output=out, layout=cfg.layout,
                          spec=LayoutSpec(name=cfg.layout, width=cfg.width,
                                          height=cfg.height),
                          work_dir=span_dir)
            else:
                # No panel still available: the presenter fills the frame. This
                # breaks the never-full-screen rule, so it is logged rather
                # than passing quietly.
                logger.warning("span %d has no content panel — presenter will "
                               "be full-frame", i)
                os.replace(seg, out)
        elif sp["mode"] == "content_full":
            # The graphic owns the whole 1080x1920 frame; the presenter is not
            # composited at all for its duration.
            self._sh("ffmpeg", "-v", "error", "-y", "-stream_loop", "-1",
                     "-i", sp["content"], "-t", f"{L:.3f}", "-an",
                     "-vf", (f"scale={cfg.width}:{cfg.height}:"
                             f"force_original_aspect_ratio=increase,"
                             f"crop={cfg.width}:{cfg.height}"),
                     "-r", str(cfg.fps), "-c:v", "libx264", "-crf", "17",
                     "-pix_fmt", "yuv420p", out)
        elif sp["mode"] == "presenter_full":
            # The presenter, full frame, cut between framings.
            #
            # This is the single change that moves the cut rate, and the
            # measurement says why. In the stacked layout the presenter
            # reframes were happening — the bottom half registered 8 cuts —
            # but each altered about 40% of the frame, so the whole frame
            # scored below any cut threshold and the video measured 10 cuts
            # against a reference's 40. A cut that changes half the picture
            # does not read as a cut. The reference changes all of it, every
            # time, and that is where its 1.43s average shot comes from.
            #
            # `seg` already carries this span's framing from the reframe
            # above, so it only needs filling to the full frame.
            self._sh("ffmpeg", "-v", "error", "-y", "-i", seg, "-an",
                     "-vf", (f"scale={cfg.width}:{cfg.height}:"
                             f"force_original_aspect_ratio=increase,"
                             f"crop={cfg.width}:{cfg.height}"),
                     "-r", str(cfg.fps), "-c:v", "libx264", "-crf", "17",
                     "-pix_fmt", "yuv420p", out)

        elif sp["mode"] == "content_pip":
            # Full-frame graphic with the presenter as a round picture-in-
            # picture in a corner.
            #
            # Between the two existing modes there was nothing: either the
            # presenter took the lower half of every frame, or they vanished
            # entirely for the length of a full-frame graphic. Both are true
            # of the whole span, so the video alternated between two fixed
            # compositions and read as a template. The PIP keeps the presence
            # of a person on screen while giving the graphic the whole frame,
            # and it is the shape short-form viewers already read as "someone
            # is talking you through this".
            #
            # The corner alternates by span index so consecutive PIPs do not
            # sit in the same place, and it hugs the side rather than the
            # centre because the captions live along the bottom middle.
            d = int(cfg.width * 0.30)                 # PIP diameter
            m = int(cfg.width * 0.045)                # margin from the edges
            left = (i % 2 == 0)
            x = m if left else cfg.width - d - m
            y = int(cfg.height * 0.60)
            circle = os.path.join(span_dir, f"pip_{i:02d}.png")
            self._sh("ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                     "-i", f"color=black@0:s={d}x{d},format=rgba",
                     "-vf", (f"geq=r=0:g=0:b=0:a='if(lte(hypot(X-{d/2},"
                             f"Y-{d/2}),{d/2}),255,0)'"),
                     "-frames:v", "1", circle)
            bg = os.path.join(span_dir, f"cf_{i:02d}.mp4")
            self._sh("ffmpeg", "-v", "error", "-y", "-stream_loop", "-1",
                     "-i", sp["content"], "-t", f"{L:.3f}", "-an",
                     "-vf", (f"scale={cfg.width}:{cfg.height}:"
                             f"force_original_aspect_ratio=increase,"
                             f"crop={cfg.width}:{cfg.height}"),
                     "-r", str(cfg.fps), "-c:v", "libx264", "-crf", "17",
                     "-pix_fmt", "yuv420p", bg)
            self._sh(
                "ffmpeg", "-v", "error", "-y", "-i", bg, "-i", seg,
                "-i", circle,
                "-filter_complex",
                # Square-crop the presenter about the head and shoulders.
                #
                # Keyed off WIDTH, not height: the presenter frame is 1080x1920,
                # so a square of 0.62*height is 1190px — wider than the source —
                # and ffmpeg rejects the filter graph outright ("Failed to
                # configure input pad"), taking the whole run with it. In a
                # vertical frame the short side is the only safe basis for a
                # square.
                f"[1:v]crop=iw*0.78:iw*0.78:(iw-iw*0.78)/2:ih*0.06,"
                f"scale={d}:{d}[p];"
                f"[p][2:v]alphamerge[pa];"
                f"[0:v][pa]overlay={x}:{y}:shortest=1[o]",
                "-map", "[o]", "-t", f"{L:.3f}", "-an",
                "-c:v", "libx264", "-crf", "17", "-pix_fmt", "yuv420p", out)

        elif sp["mode"] == "full":
            os.replace(seg, out)
        else:
            ct = os.path.join(span_dir, f"ct_{i:02d}.mp4")
            # Loop if shorter than the span, trim if longer. No rescale here —
            # content is already produced at the panel's dimensions.
            self._sh("ffmpeg", "-v", "error", "-y", "-stream_loop", "-1",
                     "-i", sp["content"], "-t", f"{L:.3f}", "-an",
                     "-c:v", "libx264", "-crf", "17", "-pix_fmt", "yuv420p", ct)
            composite(content=ct, avatar=seg, output=out, layout=cfg.layout,
                      spec=LayoutSpec(name=cfg.layout, width=cfg.width,
                                      height=cfg.height),
                      work_dir=span_dir)
        parts.append(out)

    listing = cfg.path("spans.txt")
    Path(listing).write_text("".join(f"file '{p}'\n" for p in parts))
    self._sh("ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
             "-i", listing, "-r", str(cfg.fps), "-c:v", "libx264", "-crf", "17",
             "-pix_fmt", "yuv420p", "-an", cfg.path("v_layout.mp4"))

    # Captions are suppressed under designed graphics: the graphic carries its
    # own typography and two competing texts is the slop pattern.
    dspans = [(p["t"], p["t"] + p["len"]) for p in placed
              if p["path"] in design_paths]
    cues = [(s, e, t) for s, e, t in caps["cues"]
            if not any(not (e <= a or s >= z) for a, z in dspans)]

    from .branding import CAPTIONS
    # A caption sits just under the panel seam, which is correct while the
    # presenter holds the lower half — and lands in the MIDDLE of a graphic
    # that owns the whole frame. Full-frame spans push their captions to the
    # lower third instead.
    full_spans = [(sp["start"], sp["end"]) for sp in spans
                  if sp["mode"] in ("content_full", "content_pip",
                                    "presenter_full")]

    def caption_y(start: float, end: float) -> float:
        if any(not (end <= a or start >= z) for a, z in full_spans):
            return 0.82
        return cfg.caption_y()

    # TWO caption tiers, split by what the beat is doing.
    #
    # The hook and the call to action get display type; everything between
    # them gets the pill. Those two moments are the ones that decide whether
    # a short works — the hook buys the next three seconds, the CTA is the
    # entire point of posting — and a subtitle is the wrong instrument for
    # either. The middle is where a viewer is being informed, and there a
    # pill is better: legible, out of the way, no frame cost.
    from .branding import DISPLAY
    t_first = cues[0][0] if cues else 0.0
    t_last = cues[-1][1] if cues else 0.0
    hook_until = t_first + cfg.display_hook_s
    cta_from = t_last - cfg.display_cta_s

    # Anything that sets its OWN large type. A pull-quote bed is a sentence at
    # display size; a designed graphic is a headline. Display captions over
    # either put two large texts on one frame, often saying the same thing —
    # the CTA card reads "Comment astra and I will send you the full safety
    # report" and the caption repeated "send you the full safety report"
    # across it, larger. The pill tier is fine there because it is small and
    # subordinate by construction; the display tier is not.
    typed_spans = list(dspans)
    for i2, sp2 in enumerate(spans):
        if sp2["mode"] in ("content", "content_full", "content_pip"):
            typed_spans.append((sp2["start"], sp2["end"]))

    def _over_typography(st: float, en: float) -> bool:
        return any(not (en <= a or st >= z) for a, z in typed_spans)

    def is_display(st: float, en: float) -> bool:
        if _over_typography(st, en):
            return False
        return en <= hook_until or st >= cta_from

    disp = [c for c in cues if is_display(c[0], c[1])]
    pill = [c for c in cues if not is_display(c[0], c[1])]
    # The subject's own accent, so display type is branded rather than
    # generic. Falls back to a warm coral, which reads on both a light and a
    # dark ground — the two extremes a story palette can land on.
    accent = _story_accent(
        (script_meta.get("visual_identity") or {}).get("palette")) or "#FF6B4A"

    # Alternate the face cue by cue, and drop the pill on the serif ones.
    #
    # A pill behind a serif italic fights it — the reference sets its serif
    # cues bare and pills only the sans ones, which is what makes the two read
    # as deliberately different rather than as one style rendering wrong.
    df = []
    for j, (s0, e0, t0) in enumerate(pill):
        df.append(CAPTIONS.drawtext(t0, s0, e0, y_frac=caption_y(s0, e0),
                                    alt=(j % 2 == 1)))
    # Split the display runs so the hook and the CTA stack independently:
    # concatenating them would carry a line from the opening into the close.
    hook_cues = [c for c in disp if c[1] <= hook_until]
    cta_cues = [c for c in disp if c[0] >= cta_from]
    for run in (hook_cues, cta_cues):
        df += DISPLAY.stack(run, cfg.width, cfg.height, accent=accent)
    if disp:
        logger.info("Captions: %d display + %d pill", len(disp), len(pill))
    self._sh("ffmpeg", "-v", "error", "-y", "-i", cfg.path("v_layout.mp4"),
             "-vf", ",".join(df), "-c:v", "libx264", "-crf", "17",
             "-pix_fmt", "yuv420p", "-an", cfg.path("v_caps.mp4"))
    logger.info("Captions: %d/%d shown", len(cues), len(caps["cues"]))

    self._sh("ffmpeg", "-v", "error", "-y", "-i", cfg.path("v_caps.mp4"),
             "-i", cfg.path("vo_master.wav"), "-map", "0:v", "-map", "1:a",
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", final)
    logger.info("FINAL %s (%.2fs)", final, self._dur(final))
    return final



# ------------------------------------------------------------- thumbnail
def make_thumbnail(self: ShortsPipeline, script: dict, *,
                   force: bool = False) -> str:
    """Render the channel-standard cover frame.

    A cover is not the video's first frame. The first frame of a talking head
    is whatever the camera caught — the previous video opened on a dark,
    downward-looking frame, which is a poor thing to represent it in a feed.
    """
    cfg = self.cfg
    out = cfg.path("thumbnail.jpg")
    if os.path.exists(out) and not force:
        return out

    from .branding import extract_best_frame, make_thumbnail as _render

    src = cfg.path("avatar_1080.mp4")
    if not os.path.exists(src):
        src = cfg.path("avatar_full.mp4")
    frame = extract_best_frame(src, cfg.path("thumb_frame.png"), at_s=6.0)

    kicker = {"github_repo": "GitHub · Deep Dive",
              "article": "AI News",
              "text": "Explainer"}.get(script.get("source_kind", ""), "AI · Tech")
    # Borrow the story's accent so the cover ties to its graphics, while the
    # template itself stays constant.
    #
    # Picked by SATURATION, not by position. Taking palette[2] assumed a fixed
    # ordering that does not hold: for this story it was #0D1117, a near-black,
    # which the renderer then had to reject — leaving the cover on the channel
    # default and losing the tie to the story entirely. The most saturated
    # mid-luminance entry is the one a designer would have called the accent.
    accent = _story_accent((script.get("visual_identity") or {}).get("palette"))

    # The publication's own mark on the cover: it signals the claim is reported
    # rather than opinion, and it borrows the source's recognition in a feed.
    icon, domain = None, ""
    meta_path = cfg.path("source_meta.json")
    if os.path.exists(meta_path):
        try:
            url = json.loads(Path(meta_path).read_text()).get("url", "")
            if url:
                from .sourcebrand import fetch_brand
                b = fetch_brand(url, cfg.broll_dir)
                icon, domain = b.get("icon"), b.get("domain", "")
        except Exception as exc:                   # noqa: BLE001 — cosmetic
            logger.info("no source badge for the cover: %s", str(exc)[:100])

    # Set in the feed's own grammar rather than the channel's old template.
    #
    # Measured against a grid of the owner's best posts: editorial serif in
    # caps at the TOP with an italic line beneath, warm filmic grade, and the
    # presenter pushed into the lower two-thirds so the type has room that is
    # not someone's face. The previous cover set a bold sans across the
    # bottom, which is the YouTube idiom and not this feed's.
    from .cover import build as _cover
    # Written by the script, not scavenged. Falling back to the CTA put
    # "Comment astra and I will send you the" under the headline — an
    # instruction where the grid always has a consequence. Better to ship no
    # second line than the wrong one.
    sub = (script.get("cover_sub") or "").strip()[:40]
    return _cover(frame=frame, out_path=out, headline=script["title"],
                  kicker=kicker, sub=sub,
                  accent=accent or "#E8E2D4",
                  width=cfg.width, height=cfg.height,
                  icon=icon, domain=domain)


# Attach as methods.
ShortsPipeline.render_avatar = render_avatar
ShortsPipeline.render_designs = render_designs
ShortsPipeline.fetch_broll = fetch_broll
ShortsPipeline.assemble = assemble
ShortsPipeline.make_thumbnail = make_thumbnail


def _panel_accent(script: dict) -> str:
    """The story's accent as an ffmpeg colour, skipping near-black and white.

    A palette's first entries are usually the background and body colours, and
    highlighting text in the same near-black as the background draws a bar
    nobody can see.
    """
    pal = (script.get("visual_identity") or {}).get("palette") or []
    for c in reversed(pal):
        if isinstance(c, str) and c.startswith("#") and len(c) == 7:
            r, g, b = (int(c[k:k + 2], 16) for k in (1, 3, 5))
            if 60 < (r + g + b) / 3 < 230:
                return "0x" + c[1:]
    return "0x22D3EE"


def _resume_source(cfg: ShortsConfig):
    """Rebuild the Source from disk for a --resume run with no --source.

    The CLI documents --source as optional when resuming, and write_script
    persists source.txt and source_meta.json for exactly this purpose, but run()
    still passed the missing spec straight into load_source and died on
    ``'NoneType' object has no attribute 'strip'`` before touching a stage.
    Re-fetching instead would defeat the point: resume exists so a crashed run
    does not repeat expensive work, and it must not depend on the source URL
    still being reachable and unchanged.

    Returns None when the run dir has no persisted source, so a first run with a
    genuinely missing --source still reaches load_source and its clearer error.
    """
    from .sources import Source

    meta_path, text_path = cfg.path("source_meta.json"), cfg.path("source.txt")
    if not (os.path.exists(meta_path) and os.path.exists(text_path)):
        return None
    try:
        meta = json.loads(Path(meta_path).read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("cannot resume source (%s) — will reload", exc)
        return None
    src = Source(kind=meta.get("kind") or "article",
                 title=meta.get("title") or "",
                 text=Path(text_path).read_text(),
                 url=meta.get("url") or "")
    logger.info("Resuming from the persisted source: %r", src.title[:70])
    return src


async def run(cfg: ShortsConfig, source_spec: str, *,
              source_kind: str | None = None) -> str:
    """Run the whole pipeline for one source. Returns the finished MP4 path."""
    from .sources import load_source, research
    pipe = ShortsPipeline(cfg)
    src = _resume_source(cfg) if not source_spec else None
    if src is None:
        if source_kind == "research":
            # A bare topic, not a document: go and find out what happened.
            # Runs through the same claude CLI the rest of the pipeline uses,
            # which already has web access and is already authenticated.
            async def _ask(prompt: str) -> str:
                r = await pipe.llm.messages.create(
                    model=cfg.intelligence_model, max_tokens=4000,
                    messages=[{"role": "user", "content": prompt}])
                return r.content[0].text
            src = await research(source_spec, _ask)
        else:
            src = load_source(source_spec, kind=source_kind)
    script = await pipe.write_script(src)

    pipe.generate_voice(script["script"])
    pipe.transcribe_and_align(script["script"])
    pipe.plan_segments()

    # Designs are CPU/Chrome-bound and the avatar is GPU-bound, so they overlap.
    # Page-roll capture is quick and the assembler needs it to fill gaps, so
    # it runs before the long renders rather than after.
    await pipe.fetch_broll(script.get("broll_queries", []), url=src.url)

    designs_task = asyncio.create_task(pipe.render_designs(script))
    await asyncio.to_thread(pipe.render_avatar)
    await designs_task

    out = pipe.assemble()
    cover_path = pipe.make_thumbnail(script)
    # Put the cover ON THE FRONT of the video.
    #
    # Instagram and TikTok choose a cover from the opening frames, so a
    # designed cover that lives only as a sidecar JPG is a cover nobody sees —
    # the platform picks whatever the camera happened to be doing at t=0
    # instead. The hold is short by design: long enough to be selected and to
    # read as a title card, short enough not to be a stall.
    if cfg.prepend_cover and cover_path and os.path.exists(cover_path):
        try:
            from .cover import prepend as _prepend
            with_cover = cfg.path(f"{cfg.run_id}_cover.mp4")
            _prepend(out, cover_path, with_cover,
                     hold_s=cfg.cover_hold_s, fps=cfg.fps)
            os.replace(with_cover, out)
        except Exception as exc:                   # noqa: BLE001 — optional
            logger.warning("could not prepend the cover (%s) — the video "
                           "ships without it", str(exc)[:140])
    return out


def _norm_words(text: str) -> list:
    """Comparison keys for matching a phrase against aligned narration."""
    import re
    return [re.sub(r"[^a-z0-9]", "", w.lower())
            for w in text.split() if re.sub(r"[^a-z0-9]", "", w.lower())]


def _find_word_run(words: list, needle: list):
    """Locate a run of words in the aligned narration; returns (start, end) secs.

    Matched against ALIGNED words, which carry the script's spellings — the CTA
    keyword is exactly the kind of token ASR mangles, and matching the raw
    transcript would miss it precisely when it matters most.
    """
    if not needle or not words:
        return None
    keys = _norm_words(" ".join(w["word"] for w in words))
    n = len(needle)
    for i in range(0, max(0, len(keys) - n + 1)):
        if keys[i:i + n] == needle:
            return (words[i]["start"], words[min(i + n - 1, len(words) - 1)]["end"])
    return None


def _story_accent(palette) -> Optional[str]:
    """The most saturated mid-luminance colour in a palette, or None.

    Backgrounds and body colours cluster at the extremes of luminance and near
    zero saturation; an accent is the entry that is neither. Choosing by
    position instead picked a near-black on a real story.
    """
    best, best_sat = None, 0.0
    for c in (palette or []):
        if not (isinstance(c, str) and len(c) == 7 and c.startswith("#")):
            continue
        try:
            r, g, b = (int(c[i:i + 2], 16) / 255 for i in (1, 3, 5))
        except ValueError:
            continue
        hi, lo = max(r, g, b), min(r, g, b)
        luma = 0.299 * r + 0.587 * g + 0.114 * b
        if not (0.24 < luma < 0.88):
            continue
        sat = 0.0 if hi == 0 else (hi - lo) / hi
        if sat > best_sat:
            best, best_sat = c, sat
    return best


def _install_faces(faces: dict) -> None:
    """Put the resolved faces where Remotion and ffmpeg will find them.

    Remotion serves `/fonts/Sourced.ttf` under a stable @font-face name, so a
    per-story face is a file copy rather than a rebuild. The caption styles
    read the same paths directly.
    """
    import shutil
    pub = Path("/home/vishalan/remotion-broll/public/fonts")
    if not pub.is_dir():
        return
    for role, name in (("italic_bold", "Sourced.ttf"), ("bold", "SourcedText.ttf")):
        src = faces.get(role) or faces.get("bold")
        if src and Path(src).is_file():
            shutil.copy(src, pub / name)
    logger.info("Typography: %s (%s) installed for this story",
                faces.get("family"), faces.get("category"))
