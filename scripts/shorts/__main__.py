"""CLI for the shorts pipeline.

    python -m shorts --source https://github.com/owner/repo --id repo-reel
    python -m shorts --source https://example.com/article --id my-short
    python -m shorts --source-file notes.txt --kind text --id from-notes
    python -m shorts --id my-short --layout half_stacked --resume

Requires on the rendering host: the commoncreed_latentsync and
commoncreed_chatterbox services, the claude CLI with the hyperframes plugin and
CLAUDE_CODE_OAUTH_TOKEN, Node >= 22, Chrome and FFmpeg. PEXELS_API_KEY is
optional — stock b-roll is skipped without it rather than failing the run.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shorts.config import ShortsConfig          # noqa: E402
from shorts import stages                        # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(prog="shorts", description=__doc__)
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--source", help="URL, owner/repo, or raw text")
    src.add_argument("--source-file", help="file containing the source text")
    ap.add_argument("--kind", choices=["article", "github_repo", "text"],
                    help="force the source kind (inferred otherwise)")
    ap.add_argument("--id", default="short", help="run id; names the work dir")
    ap.add_argument("--work-root", default="/home/vishalan/shorts")
    ap.add_argument("--layout", default="pip_circle",
                    choices=["pip_circle", "half_stacked", "full"])
    ap.add_argument("--designs", type=int, default=4, help="max design graphics")
    ap.add_argument("--no-broll", action="store_true", help="skip stock footage")
    ap.add_argument("--words", type=int, default=190,
                    help="minimum script words (190 ~= 60s)")
    ap.add_argument("--resume", action="store_true",
                    help="reuse completed stages in the work dir")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    cfg = ShortsConfig(
        run_id=args.id,
        work_root=args.work_root,
        layout=args.layout,
        max_designs=args.designs,
        broll_enabled=not args.no_broll,
        target_words_min=args.words,
        target_words_max=args.words + 20,
    )

    spec = args.source
    if args.source_file:
        spec = Path(args.source_file).read_text()
    if not spec and not args.resume:
        ap.error("--source or --source-file is required unless --resume")

    if not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        logging.warning(
            "CLAUDE_CODE_OAUTH_TOKEN is not set — claude -p will fail unless "
            "this user has an interactive login.")

    try:
        out = asyncio.run(stages.run(cfg, spec, source_kind=args.kind))
    except Exception as exc:                       # noqa: BLE001 — CLI boundary
        logging.error("pipeline failed: %s", exc)
        return 1

    print(f"\nFINISHED: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
