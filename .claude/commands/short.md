---
description: Build a vertical short from a link, pasted text, or a topic to research
argument-hint: <url | pasted text | topic> [--research] [--avatar] [--wait]
allowed-tools: Bash, Read
---

Build one vertical short and report the result.

The pipeline lives entirely on the GPU server as `ccshort`. Do not
reimplement any of it here — no python invocation, no flag translation, no
polling loop of your own. This command's whole job is to hand the input
over and interpret what comes back, so that the same run can be started
from a phone, a laptop or a cron entry and behave identically.

## Starting it

`$ARGUMENTS` is whatever the user pasted — a URL, a URL with prose under
it, or a bare topic. Pass it through UNCHANGED, over stdin, so newlines and
query strings survive:

```bash
printf '%s' '<the user input verbatim>' | ssh vishalan@100.72.251.52 ccshort [flags]
```

Flags map one to one: `--research` when the input is a topic rather than a
document, `--avatar` when the user wants the lip-synced presenter (adds
~35 min; without it the lower half is a black hold, which is the fast path
for iterating). `--id NAME` to name the run.

`ccshort` detaches and returns immediately with a run id, a log path and
the eventual output path. The job is not tied to the SSH session — it
survives the connection dropping, so never hold one open waiting.

## Following it

```bash
ssh vishalan@100.72.251.52 ccstatus <run-id>
```

Poll that until it reports done or stopped. Never sleep in a foreground
command; loop with a check. Expect 8-15 minutes held, 40-50 with the
avatar.

## Reporting back

1. Fetch the MP4 and send it. Over 30 MB, send a compressed copy
   (`-crf 26`) and say the master is on the server — do not skip the send.
2. Pull a frame strip and LOOK at it before reporting. Several defects in
   this pipeline's history were invisible in the logs and obvious in one
   frame: a paywall interstitial used as b-roll, a headline rendered in the
   background colour, code running off the panel edge.
3. Report the card share `ccstatus` prints. Under 20% is the target.
4. State anything that failed or was skipped. A clip dropped for want of
   GPU memory is a warning, not an error — the video ships one shot short
   and nothing announces it, so silence is not evidence that all is well.

Never post anywhere. Publishing is always a separate, explicit request.
