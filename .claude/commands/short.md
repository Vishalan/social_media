---
description: Build a vertical short from a link, pasted text, or a topic to research
argument-hint: <url | pasted text | topic to research> [--research] [--avatar] [--id name]
allowed-tools: Bash, Read
---

Build one vertical short end to end on the GPU server and return the result.

## Input

`$ARGUMENTS` is whatever the user pasted. Work out which of three it is:

- **A URL, alone or with prose under it.** The common case — a newsletter
  blurb with the link above it. Pass BOTH through unchanged; the pipeline
  keeps the URL for attribution and falls back to the prose when the page
  is paywalled. Do not strip either half.
- **Prose with no URL.** Source text; pass as-is.
- **A bare topic** (a short phrase, no URL, no article body) — or anything
  the user marked `--research`. Add `--kind research` so the pipeline
  searches the web before writing.

Flags the user may include:

- `--avatar` — render the lip-synced presenter. Adds roughly 35 minutes.
  WITHOUT it the lower half is a black hold, which is the fast path for
  iterating on voice and b-roll.
- `--id <name>` — names the run directory. Default: a short slug of the
  subject plus the date.

## Running it

Write the input to a file rather than passing it as an argument: it
contains newlines, quotes and URLs with query strings, and shell quoting
mangles all three.

```bash
cat > /tmp/short_input.txt <<'INPUT'
<the user's input verbatim>
INPUT
scp -q /tmp/short_input.txt vishalan@100.72.251.52:/tmp/short_input.txt

ssh vishalan@100.72.251.52 'cd /home/vishalan/pipe/scripts && \
  nohup python3 -m shorts --source-file /tmp/short_input.txt \
  --id <RUN_ID> --layout half_stacked [--kind research] [--avatar render] \
  > /tmp/<RUN_ID>.log 2>&1 & echo started'
```

Then poll until the MP4 exists or the process dies — never sleep in a
foreground command:

```bash
until ssh vishalan@100.72.251.52 'test -f /home/vishalan/shorts/<RUN_ID>/<RUN_ID>.mp4'; do
  ssh vishalan@100.72.251.52 'pgrep -f "[s]horts --source-file" >/dev/null' || { echo FAILED; break; }
  sleep 45
done
```

Expect 8-12 minutes with the avatar held, 40-50 with it rendered and
generated footage in the slate.

## Reporting back

1. Fetch the MP4. If it is over 30 MB, send a compressed copy
   (`-crf 26`) and say the master is on the server — do not skip the send.
2. Pull a frame strip and LOOK at it before reporting. Several defects in
   this pipeline's history were invisible in the logs and obvious in a
   single frame: a paywall interstitial used as b-roll, a headline
   rendered in the background colour, code running off the panel edge.
3. Report the scene share from `broll.json` — what fraction of clips are
   footage or scenes rather than typographic cards. This is the number the
   owner cares about most.
4. State anything that failed or was skipped. A clip dropped for lack of
   GPU memory is logged as a warning and the video ships one shot short,
   so silence is not evidence that everything rendered.

Never post anywhere. Publishing is always a separate, explicit request.
