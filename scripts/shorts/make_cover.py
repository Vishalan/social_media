"""Build one cover, end to end, from footage and a headline.

    python3 scripts/shorts/make_cover.py \
        --source assets/input_media/IMG_1774_4.mp4 \
        --source assets/logos/owner-portrait.jpg \
        --scene "A young man sits at a wooden desk in a study, holding up a
                 printed sheet toward the camera, bookshelves behind him" \
        --headline "The AI model that can hide its own thoughts" \
        --kicker "deployment safety" --sub "and it knows we are watching" \
        --domain openai.com --out output/cover.jpg --sweep --refine

Runs on the GPU box: it talks to ComfyUI on localhost and needs insightface.

Four stages, each of which can be skipped or inspected on its own — the point
of keeping them separate is that when a cover comes out wrong you can tell
which stage was responsible instead of re-running the whole thing blind.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shorts import portrait
from shorts import cover_scene

logger = logging.getLogger("make_cover")

DEFAULT_SOURCES = [
    "assets/input_media/IMG_1774_4.mp4",
    "assets/logos/owner-portrait.jpg",
    "assets/logos/owner-portrait-9x16.jpg",
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", action="append", default=[],
                    help="video or still to draw face references from "
                         "(repeatable; defaults to the owner's footage+stills)")
    ap.add_argument("--scene", required=True, help="what the photograph shows")
    ap.add_argument("--headline", required=True)
    ap.add_argument("--kicker", default="")
    ap.add_argument("--sub", default="")
    ap.add_argument("--domain", default="")
    ap.add_argument("--out", required=True, help="final typeset cover")
    ap.add_argument("--refs", type=int, default=4,
                    help="how many face references to average (default 4)")
    ap.add_argument("--id-weight", type=float, default=1.05)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--sweep", action="store_true",
                    help="try several id_weights and keep the closest likeness "
                         "(restarts ComfyUI between trials)")
    ap.add_argument("--refine", action="store_true",
                    help="re-sample the face at full resolution afterwards")
    ap.add_argument("--denoise", type=float, default=0.40,
                    help="face pass strength; higher redraws more (default .40)")
    ap.add_argument("--keep-photo", action="store_true",
                    help="also keep the untypeset photograph")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    out = Path(args.out)
    work = out.parent / f"{out.stem}_work"
    work.mkdir(parents=True, exist_ok=True)

    # 1. references ---------------------------------------------------------
    refs = portrait.gather_references(args.source or DEFAULT_SOURCES,
                                      str(work / "refs"), want=args.refs)
    logger.info("Using %d reference(s)", len(refs))

    # 2. the photograph -----------------------------------------------------
    photo = str(work / "photo.jpg")
    report: dict = {}
    if args.sweep:
        report = portrait.best_of(scene=args.scene, faces=refs, out_path=photo)
    else:
        portrait.generate(scene=args.scene, faces=refs, out_path=photo,
                          id_weight=args.id_weight, seed=args.seed)
        identity = portrait.reference_identity(refs)
        report = {"path": photo, **portrait.measure(photo, identity)}

    # 3. the face pass ------------------------------------------------------
    if args.refine:
        refined = str(work / "photo_refined.jpg")
        portrait.refine_face(image=photo, faces=refs, out_path=refined,
                             denoise=args.denoise, id_weight=args.id_weight)
        identity = portrait.reference_identity(refs)
        before = report.get("score", report.get("cosine"))
        after = portrait.measure(refined, identity)
        logger.info("Face pass: cosine %.3f -> %.3f (face %dpx)",
                    before or 0.0, after["cosine"], after["face_px"])
        # Keep it only if it actually helped. A face pass can drift the
        # likeness as easily as sharpen it, and shipping the worse of two
        # images because it cost more compute is not a trade.
        if after["cosine"] >= (before or 0.0):
            photo = refined
            report = {"path": refined, **after}
        else:
            logger.info("Face pass made it worse — keeping the base render")

    # 4. the type -----------------------------------------------------------
    cover_scene.typeset(photo=photo, out_path=str(out), headline=args.headline,
                        sub=args.sub, kicker=args.kicker, domain=args.domain)
    if not args.keep_photo:
        logger.info("Photograph kept at %s", photo)

    print(json.dumps({"cover": str(out), **report}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
