"""Avatar, design, b-roll and assembly stages.

Split from pipeline.py to keep each file readable; these are mixin methods
attached to ShortsPipeline at import time.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .config import ShortsConfig
from .pipeline import ShortsError, ShortsPipeline

logger = logging.getLogger(__name__)

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


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
def fetch_broll(self: ShortsPipeline, queries: list[str], *,
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

    if cfg.broll_provider == "pageroll":
        from .pageroll import build_rolls, capture_page, detect_regions
        if not url:
            logger.warning("page-roll requested but the source has no URL — "
                           "skipping b-roll")
            self._save("broll.json", [])
            return []

        pick = None
        if cfg.smart_regions:
            pick = _pick_regions(self, url, h)
        rolls = build_rolls(url, cfg.broll_dir, count=cfg.broll_max_clips,
                            duration=cfg.broll_clip_s, width=cfg.width,
                            height=cfg.height, fps=cfg.fps, half_height=h,
                            pick=pick)
        out = [{"path": r.path, "duration": r.duration, "kind": r.kind,
                "region": r.region, "source": r.source_url} for r in rolls]
        self._save("broll.json", out)
        return out

    return _fetch_stock(self, queries, height=h)


def _fetch_stock(self: ShortsPipeline, queries: list[str], *,
                 height: int) -> list[dict]:
    """Keyword stock search. Kept for sources with no capturable page."""
    cfg = self.cfg
    key = os.environ.get("PEXELS_API_KEY", "")
    if not key:
        logger.warning("PEXELS_API_KEY not set — skipping stock b-roll")
        self._save("broll.json", [])
        return []

    def search(q: str) -> dict:
        u = ("https://api.pexels.com/videos/search?" + urllib.parse.urlencode(
            {"query": q, "per_page": 5, "orientation": "portrait",
             "size": "medium"}))
        # Cloudflare returns 403 "error code: 1010" to default library agents.
        req = urllib.request.Request(u, headers={
            "Authorization": key, "User-Agent": _UA,
            "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)

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
    placed = [p for p in placed if p["t"] + p["len"] <= dur - 0.3]
    busy = [(p["t"], p["t"] + p["len"]) for p in placed]

    for b in broll:
        L = min(cfg.broll_clip_s, b["duration"])
        t = 3.0
        while t < dur - 3.0 and not all(t + L <= a - 0.5 or t >= z + 0.5
                                        for a, z in busy):
            t += 0.5
        if t < dur - 3.0:
            placed.append({"t": t, "len": L, "path": b["path"],
                           "slug": os.path.basename(b["path"])})
            busy.append((t, t + L))

    placed.sort(key=lambda x: x["t"])
    for p in placed:
        logger.info("  content %-26s %6.2fs +%.2fs", p["slug"], p["t"], p["len"])

    # Gap filling: the presenter must never occupy the whole frame. Any span
    # without a designed graphic gets source page-roll in the content panel,
    # cycling through the captured bands so consecutive gaps are different
    # parts of the page rather than the same header repeated.
    gap_fill = [b["path"] for b in broll] if cfg.fill_gaps_with_pageroll else []
    gap_i = 0

    spans, cursor = [], 0.0

    def add_gap(start: float, end: float) -> None:
        nonlocal gap_i
        if end - start <= 0.25:
            return
        if gap_fill:
            spans.append({"mode": "content", "start": start, "end": end,
                          "content": gap_fill[gap_i % len(gap_fill)]})
            gap_i += 1
        else:
            # Only reachable when capture failed outright.
            spans.append({"mode": "full", "start": start, "end": end})

    for p in placed:
        add_gap(cursor, p["t"])
        spans.append({"mode": "content", "start": p["t"],
                      "end": p["t"] + p["len"], "content": p["path"]})
        cursor = p["t"] + p["len"]
    add_gap(cursor, dur)

    span_dir = cfg.path("spans")
    Path(span_dir).mkdir(exist_ok=True)
    parts = []
    for i, sp in enumerate(spans):
        L = sp["end"] - sp["start"]
        seg = os.path.join(span_dir, f"av_{i:02d}.mp4")
        self._sh("ffmpeg", "-v", "error", "-y", "-ss", f"{sp['start']:.3f}",
                 "-t", f"{L:.3f}", "-i", av, "-an", "-c:v", "libx264",
                 "-crf", "17", "-pix_fmt", "yuv420p", seg)
        out = os.path.join(span_dir, f"sp_{i:02d}.mp4")
        if sp["mode"] == "full":
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
    df = [CAPTIONS.drawtext(t, s, e, y_frac=cfg.caption_y())
          for s, e, t in cues]
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
    accent = None
    vi = script.get("visual_identity") or {}
    if vi.get("palette") and len(vi["palette"]) > 2:
        # Borrow the story's accent so the cover ties to its graphics, while
        # the template itself stays constant.
        accent = vi["palette"][2]

    return _render(title=script["title"], kicker=kicker, avatar_frame=frame,
                   out_path=out, accent=accent)


# Attach as methods.
ShortsPipeline.render_avatar = render_avatar
ShortsPipeline.render_designs = render_designs
ShortsPipeline.fetch_broll = fetch_broll
ShortsPipeline.assemble = assemble
ShortsPipeline.make_thumbnail = make_thumbnail


async def run(cfg: ShortsConfig, source_spec: str, *,
              source_kind: str | None = None) -> str:
    """Run the whole pipeline for one source. Returns the finished MP4 path."""
    from .sources import load_source
    pipe = ShortsPipeline(cfg)
    src = load_source(source_spec, kind=source_kind)
    script = await pipe.write_script(src)

    pipe.generate_voice(script["script"])
    pipe.transcribe_and_align(script["script"])
    pipe.plan_segments()

    # Designs are CPU/Chrome-bound and the avatar is GPU-bound, so they overlap.
    # Page-roll capture is quick and the assembler needs it to fill gaps, so
    # it runs before the long renders rather than after.
    pipe.fetch_broll(script.get("broll_queries", []), url=src.url)

    designs_task = asyncio.create_task(pipe.render_designs(script))
    await asyncio.to_thread(pipe.render_avatar)
    await designs_task

    out = pipe.assemble()
    pipe.make_thumbnail(script)
    return out
