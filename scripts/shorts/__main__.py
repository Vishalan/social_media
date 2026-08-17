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

# Where a .env may live, in order of precedence. The repo root sits two levels
# up from this file; /opt/commoncreed is the deployed location on the server.
_ENV_CANDIDATES = (
    Path(__file__).resolve().parent.parent.parent / ".env",
    Path("/opt/commoncreed/.env"),
    Path.home() / ".commoncreed.env",
)


def load_env_file(explicit: str = "") -> str:
    """Load KEY=VALUE pairs from a .env into the environment.

    The pipeline reads its secrets from os.environ, and nothing was populating
    it: CLAUDE_CODE_OAUTH_TOKEN had to be exported by hand for every run, and a
    .env sitting in the repo was silently ignored.

    Existing environment variables WIN over the file, so an explicit export in
    the shell still overrides a stale .env rather than being quietly replaced.

    Values are never logged — only key names and the file path. A token that
    reaches a log reaches every log reader.
    """
    paths = [Path(explicit)] if explicit else list(_ENV_CANDIDATES)
    for path in paths:
        try:
            if not path.is_file():
                continue
            raw = path.read_text()
        except (OSError, UnicodeDecodeError):
            continue

        loaded, skipped = [], 0
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            if key.startswith("export "):
                key = key[7:].strip()
            if not key:
                continue
            val = val.strip()
            # Strip one layer of matching quotes, as a shell would.
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                val = val[1:-1]
            if key in os.environ and os.environ[key]:
                skipped += 1
                continue
            os.environ[key] = val
            loaded.append(key)
        if loaded or skipped:
            logging.info("Loaded %d key(s) from %s%s: %s", len(loaded), path,
                         f" ({skipped} already set in the environment)"
                         if skipped else "", ", ".join(sorted(loaded)) or "none")
            return str(path)
    return ""


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
    ap.add_argument("--env-file", default="",
                    help="path to a .env; otherwise the repo root, "
                         "/opt/commoncreed/.env and ~/.commoncreed.env are tried")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    load_env_file(args.env_file)

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
