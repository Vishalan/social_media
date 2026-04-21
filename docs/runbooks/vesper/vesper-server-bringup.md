---
date: 2026-04-21
topic: vesper-server-bringup
owner: vishalan
status: active
---

# Vesper Server Bringup (Reuse-First)

Vesper's server footprint **piggybacks on the existing CommonCreed
stack** at `192.168.29.237`. Don't stand up parallel infrastructure.
Reuse:

- **Redis** — `commoncreed_redis`. Serves both Postiz BullMQ AND
  Vesper's GPU mutex (key `gpu:plane:mutex` — namespaced, won't
  collide with BullMQ keys).
- **Postiz** — `commoncreed_postiz`. The `vesper` profile is a
  first-class concept; routing is per-profile, not per-instance.
- **chatterbox** — `commoncreed_chatterbox`. Same container, same
  3090. Vesper just adds its own reference clip into the existing
  `/opt/commoncreed/assets/` bind mount under a `vesper/` subdir.

The **only new service** on the server is ComfyUI (for Flux stills
+ parallax + eventual I2V). It's shipped as a compose OVERLAY
(`docker-compose.vesper.yml`) so `docker-compose.yml` stays
untouched.

Every step below has a **CommonCreed impact** line calling out what
changes (or doesn't) for the existing pipeline. Read those lines —
they're the rollback guide too.

---

## S0 — verify the existing stack

Before doing anything, confirm CommonCreed is healthy. If it's sick
now, Vesper bringup will just pile onto the problem.

```bash
ssh 192.168.29.237
cd /home/vishalan/social_media/deploy/portainer
docker compose ps
```

Expected services up + healthy (or at least `running`):
- commoncreed_postgres
- commoncreed_redis
- commoncreed_temporal_postgres
- commoncreed_temporal_elasticsearch
- commoncreed_temporal
- commoncreed_postiz
- commoncreed_sidecar
- commoncreed_chatterbox
- commoncreed_remotion (may be idle-gated)

If anything's unhealthy, fix that first using CommonCreed's
runbooks — don't proceed.

**CommonCreed impact:** None. Pure read.

---

## S1 — Vesper's Archivist voice reference

Drop the Archivist `.wav` into the existing chatterbox ref mount.
No compose change needed.

```bash
# On the server — ssh 192.168.29.237
sudo mkdir -p /opt/commoncreed/assets/vesper
sudo chown $USER:$USER /opt/commoncreed/assets/vesper
# scp the recorded clip from your laptop:
# scp ~/path/to/archivist.wav 192.168.29.237:/opt/commoncreed/assets/vesper/
chmod 600 /opt/commoncreed/assets/vesper/archivist.wav
```

Verify inside the chatterbox container:

```bash
docker exec commoncreed_chatterbox ls /app/refs/vesper/
# → archivist.wav
```

Set the laptop env:

```
CHATTERBOX_REFERENCE_AUDIO=/app/refs/vesper/archivist.wav
```

(Note the subdir path — Vesper's ref lives under `vesper/` so
CommonCreed's existing refs under `/app/refs/*.wav` stay
untouched.)

Verify the ref is visible via the `/refs/list` endpoint:

```bash
curl http://192.168.29.237:7777/refs/list | jq
```

Must show `archivist.wav` in the `vesper/` subdir listing (or
flat-listed, depending on how `list_refs()` walks).

**CommonCreed impact:** None. The bind mount already exists; adding
a new file to a subdirectory doesn't restart the container and
doesn't touch CommonCreed's existing `voice_ref.wav`.

---

## S2 — add ComfyUI via the compose overlay

ComfyUI is the only new server service. The `docker-compose.vesper.yml`
overlay adds it without touching the main compose file.

```bash
cd /home/vishalan/social_media/deploy/portainer
git pull origin feat/vesper-v1   # pulls the overlay file onto the server
docker compose \
    -f docker-compose.yml \
    -f docker-compose.vesper.yml \
    up -d commoncreed_comfyui
```

Wait for the image pull + first start (~5-10 minutes).

```bash
docker compose ps commoncreed_comfyui
curl http://192.168.29.237:8188/system_stats
```

**CommonCreed impact:**
- Adds ~4 GB idle memory pressure on the host. Temporal + Postgres
  use ~1.5 GB combined, leaving plenty of headroom on a 16 GB+ box.
- Adds a second GPU consumer on the 3090. Concurrent VRAM usage is
  ruled out by the Redis mutex (shipped in this PR). The mutex
  priority queue is chatterbox > parallax > Flux > I2V — CommonCreed
  chatterbox always wins against a Vesper Flux request at the same
  instant.
- No existing container restarts or is reconfigured. Rollback:
  `docker compose -f docker-compose.yml -f docker-compose.vesper.yml rm -fsv commoncreed_comfyui`.

---

## S3 — install ComfyUI model weights + node packs

The default `yanwk/comfyui-boot` image is bare ComfyUI. Install the
Vesper-required models + node packs via the container's ComfyUI
Manager UI (or by docker-exec + wget).

```bash
# Exec into the container
docker exec -it commoncreed_comfyui bash

# Inside container:
cd /root/ComfyUI

# Flux weights (adjust filenames for schnell vs dev vs pro)
wget -P models/unet https://huggingface.co/black-forest-labs/FLUX.1-dev/resolve/main/flux1-dev.safetensors
wget -P models/vae  https://huggingface.co/black-forest-labs/FLUX.1-dev/resolve/main/ae.safetensors
wget -P models/clip https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp8_e4m3fn.safetensors
wget -P models/clip https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors

# Depth Anything V2 checkpoint
mkdir -p models/depthanything
wget -P models/depthanything https://huggingface.co/depth-anything/Depth-Anything-V2-Large/resolve/main/depth_anything_v2_vitl.pth

# Custom node packs — install via ComfyUI Manager UI (browser) OR:
cd custom_nodes
git clone https://github.com/Fannovel16/comfyui_controlnet_aux
git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite
# DepthFlow: either pip install in the container's venv OR install
# a ComfyUI wrapper — pick whichever your installed DAV2 pack pairs with.
exit

docker restart commoncreed_comfyui
```

Verify node availability:

```bash
curl http://192.168.29.237:8188/object_info | \
    jq 'keys[] | select(contains("Depth") or contains("Flux") or contains("VHS"))'
```

Expected: entries for `DepthAnythingV2Preprocessor`,
`VHS_VideoCombine` (and your installed DAV2 + DepthFlow nodes by
their pack-specific names).

**CommonCreed impact:** None. Models land in a Vesper-scoped named
volume (`commoncreed_comfyui_models`); no CommonCreed models are
touched.

---

## S4 — validate the Vesper workflow JSONs

The repo ships stub templates at `comfyui_workflows/flux_still.json`
and `comfyui_workflows/depth_parallax.json`. Stub templates need
one-time adjustment because node `class_type` strings drift between
packs.

```bash
cd /home/vishalan/social_media/comfyui_workflows

# For each JSON: confirm every class_type matches a key in
# /object_info above. Common mismatches:
#   DepthAnythingV2Preprocessor vs DepthAnything_V2 vs similar
#   DepthFlowParallaxRender vs your pack's actual name
# Fix filenames too — flux1-dev.safetensors, ae.safetensors, etc.
# must match what you downloaded.
```

Smoke-test each workflow directly against ComfyUI (substitute tokens
manually for the test):

```bash
cp flux_still.json /tmp/test_flux.json
# Replace {{prompt}}, {{width}} etc. with literal values, then:
curl -X POST http://192.168.29.237:8188/prompt \
    -H "Content-Type: application/json" \
    -d "{\"prompt\": $(cat /tmp/test_flux.json)}"
# Watch /history or /view for the output PNG.
```

**CommonCreed impact:** None. The workflow files live in the repo's
`comfyui_workflows/` directory; Vesper's JSONs don't collide with
CommonCreed's `short_video_wan21.json`, `broll_generator.json`,
`thumbnail_generator.json`, `echomimic_v3_avatar.json`.

---

## S5 — Postiz Vesper profile

Postiz is already running. Add a new profile — do NOT delete or
modify the `commoncreed` profile.

- Postiz UI (`http://192.168.29.237:5100`, or whatever
  `POSTIZ_HOST_PORT` is) → Profiles → Add `vesper`.
- Connect IG + YouTube + TikTok accounts for `@vesper.tv` under that
  profile.
- Enable AI-content disclosure at the profile level (redundant with
  the per-publish flag; belt-and-braces).

Verify:

```bash
curl -H "Authorization: $POSTIZ_API_KEY" \
     http://192.168.29.237:5100/api/public/v1/integrations | \
     jq '.[] | select(.profile=="vesper") | {id, identifier}'
```

Expected: three rows for `instagram`, `youtube`, `tiktok` under the
`vesper` profile.

**CommonCreed impact:** None. Per-profile isolation is Postiz's
native model — CommonCreed posts still route via `commoncreed`
profile. Shared rate budget (30 req/hr org-wide) is enforced via
`PostizRateLedger` which both pipelines already consult.

---

## S6 — Vesper SFX + overlay assets (on the laptop)

These are git-ignored binary assets, not shipped in the repo. They
live under `assets/vesper/` on the laptop only — the pipeline runs
laptop-side, so the server never sees them.

- [ ] Source CC0 `.wav`s into `assets/vesper/sfx/` (see
      `channels/vesper.py::_register_sfx_pack` for filename
      expectations):
        - `cut_light_*.wav`, `cut_heavy_*.wav` (transition whooshes)
        - `punch_light_*.wav`, `punch_heavy_*.wav` (hero thumps)
        - `reveal_light_*.wav`, `reveal_heavy_*.wav` (risers for punches)
        - `tick_light_*.wav`, `tick_heavy_*.wav` (subtle accents)

- [ ] Source four overlay `.mp4`s into `assets/vesper/overlays/`:
      `grain.mp4`, `dust.mp4`, `flicker.mp4`, `fog.mp4`. Each 30-60
      s 1080x1920 CC0. Length ≥ longest expected short.

- [ ] Drop `CormorantGaramond-Bold.ttf` into `assets/fonts/`.

**CommonCreed impact:** None. These are Vesper-scoped paths; adding
files under `assets/vesper/` doesn't affect `assets/sfx/` or
`assets/fonts/*.ttf` CommonCreed relies on.

---

## S7 — env file (laptop + server)

```
# Required for Vesper
ANTHROPIC_API_KEY=sk-ant-...                     # shared with CommonCreed — do not rotate
REDIS_URL=redis://192.168.29.237:6379/0          # same instance — different db # if desired
COMFYUI_URL=http://192.168.29.237:8188           # NEW (Vesper-only)
CHATTERBOX_ENDPOINT=http://192.168.29.237:7777   # SHARED with CommonCreed
CHATTERBOX_REFERENCE_AUDIO=/app/refs/vesper/archivist.wav  # NEW subdir path
POSTIZ_URL=http://192.168.29.237:5100            # SHARED
POSTIZ_API_KEY=...                               # SHARED token
TELEGRAM_BOT_TOKEN=...                           # may reuse CommonCreed bot
TELEGRAM_OWNER_USER_ID=...                       # same owner
FAL_API_KEY=...                                  # optional Flux fallback
```

`chmod 600 .env` on both sides. Never `cat`/`grep` the file
(auto-memory rule).

**CommonCreed impact:** None, if you keep `ANTHROPIC_API_KEY`,
`POSTIZ_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_OWNER_USER_ID`
unchanged. Adding new keys (`COMFYUI_URL`, `CHATTERBOX_REFERENCE_AUDIO`
with the Vesper subdir path) doesn't affect CommonCreed's reads.

---

## S8 — laptop-side automated verification

From the laptop, repo root:

```bash
cd scripts
python3 -m vesper_pipeline.doctor     # hermetic — filesystem only
python3 -m vesper_pipeline.probe      # networked — hits every server
```

Both must exit 0. Investigate warnings (optional to fix) and fail
items (must fix before S9).

**CommonCreed impact:** None — doctor + probe only perform reads.

---

## S9 — single-short smoke test

```bash
cd /Users/vishalan/Documents/Projects/social_media
VESPER_MAX_SHORTS_PER_RUN=1 bash deploy/run_vesper_pipeline.sh
```

Tail the log in another terminal:

```bash
tail -f logs/vesper_pipeline_$(date +%Y-%m-%d).log
```

Expected timeline (first run is slower than steady-state —
chatterbox model load, Flux KV-cache warmup):

1. topic_signal (~15 s)
2. draft_story (~20 s)
3. voice_preflight (<1 s)
4. voice_generate (60-180 s)
5. transcribe_voice (5-15 s)
6. plan_timeline (~5 s)
7. mix_sfx (1-3 s, or no-op if pack empty)
8. generate_stills (150-300 s — 15 beats × ~10-20 s on 3090)
9. animate_still_beats (50-100 s — parallax only in v1; I2V deferred)
10. assemble_video (30-60 s)
11. render_thumbnail (<1 s)
12. request_approval — wait on owner tap in Telegram
13. publish (5-20 s)
14. log_analytics (<1 s)

**Approve from Telegram** and confirm the short lands on all three
platforms.

**CommonCreed impact:** **This is the moment of truth.** The Vesper
run uses the shared chatterbox GPU. If CommonCreed happens to be
running concurrently (unlikely at the staggered 08:00 / 09:30 times
but possible during manual tests), the mutex will serialize them.
Run this smoke test at a time CommonCreed is idle to get clean
timing data.

If the run fails, DO NOT immediately retry on auto-schedule. Match
against `vesper-incident-response.md` first. Common S9 failures:

- **ComfyUI node class_type mismatch** → edit workflow JSON per S2.
- **Postiz 403 for vesper profile** → S5 wiring incomplete.
- **Telegram 400** → `TELEGRAM_OWNER_USER_ID` must be numeric.
- **GpuMutexAcquireTimeout** → CommonCreed had the GPU plane for
  longer than the 10-min acquire budget. Re-run when idle.

---

## S10 — enable LaunchAgents (laptop)

Only after S9 is green.

```bash
cp deploy/com.vesper.pipeline.plist ~/Library/LaunchAgents/
cp deploy/com.vesper.sqlite_backup.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.vesper.pipeline.plist
launchctl load -w ~/Library/LaunchAgents/com.vesper.sqlite_backup.plist
launchctl list | grep com.vesper    # two rows, PID=- (idle)
```

Pipeline fires at 09:30 local; backup at 04:30. CommonCreed's 08:00
schedule is 90 min before Vesper — by design (Key Decision #12). If
a run overlaps, the Redis mutex handles it.

**CommonCreed impact:** None. Separate LaunchAgent units; no shared
state.

---

## Rollback cheatsheet

If anything goes wrong:

| Action | Command | CommonCreed impact |
|---|---|---|
| Disable Vesper daily run | `launchctl unload ~/Library/LaunchAgents/com.vesper.pipeline.plist` | None |
| Remove ComfyUI container | `cd deploy/portainer && docker compose -f docker-compose.yml -f docker-compose.vesper.yml rm -fsv commoncreed_comfyui` | None |
| Remove Vesper Postiz profile | Postiz UI → delete `vesper` profile | None — posts under `commoncreed` keep working |
| Remove Vesper ref clip | `rm /opt/commoncreed/assets/vesper/archivist.wav` (don't touch the `vesper/` dir unless confident) | None |
| Nuke Vesper model weights | `docker volume rm commoncreed_comfyui_models` | None — CommonCreed models live elsewhere |

Stopping Vesper never requires modifying `docker-compose.yml`,
restarting existing CommonCreed services, or touching CommonCreed
data.

---

## Failure-mode pointers

| Failure | Runbook |
|---|---|
| ComfyUI stops responding mid-run | vesper-gpu-contention.md |
| Postiz rate budget exhausted | vesper-rate-budget-breach.md |
| DMCA notice arrives | vesper-dmca-response.md |
| Chatterbox ref missing | vesper-incident-response.md |
| Any other first-day pipeline failure | vesper-incident-response.md |
