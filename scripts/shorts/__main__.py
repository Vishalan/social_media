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

from shorts.config import ShortsConfig, resolve_endpoints  # noqa: E402
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
    ap.add_argument("--kind",
                    choices=["article", "github_repo", "text", "research"],
                    help="force the source kind (inferred otherwise). "
                         "'research' treats --source as a TOPIC and searches "
                         "the web for current reporting before writing.")
    ap.add_argument("--id", default="short", help="run id; names the work dir")
    ap.add_argument("--work-root", default="/home/vishalan/shorts")
    ap.add_argument("--layout", default="pip_circle",
                    choices=["pip_circle", "half_stacked", "full"])
    # 0 by default: designed graphics now come from the director's Remotion
    # compositions, not from the legacy HyperFrames brief stage. This flag
    # defaulting to 4 silently overrode the config and kept that stage alive
    # after it was turned off, costing ~10 minutes per graphic for output
    # that was then unused.
    ap.add_argument("--designs", type=int, default=0,
                    help="legacy HyperFrames design graphics (0 = off)")
    ap.add_argument("--no-broll", action="store_true", help="skip stock footage")
    # No default. Passing one here silently overrode the config: --words
    # defaulted to 190 and main() set target_words_min/max from it, so the
    # 150-165 ceiling in ShortsConfig never applied at runtime and the
    # over-length trim pass had nothing to trim. Same trap as --designs.
    ap.add_argument("--words", type=int, default=None,
                    help="override the config's minimum script words")
    ap.add_argument("--resume", action="store_true",
                    help="reuse completed stages in the work dir")
    ap.add_argument("--h3", action="store_true",
                    help="allow one generated MiniMax H3 hero clip (~6.5 min)")
    ap.add_argument("--avatar", choices=["render", "hold"], default=None,
                    help="'hold' skips LatentSync and uses a black panel — "
                         "~3 min iterations instead of ~35")
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
    )
    # Only override the word target when the flag was actually given, so the
    # config stays the single source of truth for pacing.
    if args.h3:
        cfg.h3_enabled = True
    if args.avatar:
        cfg.avatar_mode = args.avatar
    if args.words is not None:
        cfg.target_words_min = args.words
        cfg.target_words_max = args.words + 15

    # Do this before any stage runs: the container IPs are not stable across
    # restarts, and a stale one fails the run 40s in with "connection refused"
    # from a service that is actually healthy.
    resolve_endpoints(cfg)

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
