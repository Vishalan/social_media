---
date: 2026-04-21
topic: vesper-server-bringup
owner: vishalan
status: active
---

# Vesper Server Bringup

Sequence for taking the Ubuntu server at `192.168.29.237` (RTX 3090,
24 GB VRAM) from "laptop code is ready" to "first Vesper short
published." Partners with:

- `vesper-launch-runbook.md` — laptop-side pre-flight checklist
- `vesper-incident-response.md` — failure-mode triage for after go-live
- Automation: `python3 -m vesper_pipeline.doctor` (hermetic) +
  `python3 -m vesper_pipeline.probe` (networked)

Estimated time end-to-end on a fresh box: **4-6 hours**. Model
downloads are the long pole.

## S0 — prerequisites (box state)

- [ ] Ubuntu 22.04+ with NVIDIA drivers supporting the 3090.
      Verify: `nvidia-smi` shows 24 GB on the 3090.
- [ ] Docker + docker-compose installed.
- [ ] `git clone` the repo into `/home/vishalan/social_media`.
- [ ] Portainer stack referenced at `deploy/portainer/docker-compose.yml`
      is deployed (Postiz + Redis + chatterbox + sidecar). Confirm with:
      `docker compose ps` from the deploy dir.

## S1 — ComfyUI install

The ComfyUI sidecar hosts both Flux (local primary for stills) and
the parallax graph. One install, two workflow files.

- [ ] Pick an install path: `/opt/vesper/ComfyUI`. Run:
      ```bash
      git clone https://github.com/comfyanonymous/ComfyUI /opt/vesper/ComfyUI
      cd /opt/vesper/ComfyUI
      python3 -m venv venv && source venv/bin/activate
      pip install -r requirements.txt
      ```

- [ ] Launch once to confirm it starts:
      `python main.py --listen 0.0.0.0 --port 8188`
      Expect `ComfyUI` banner + `/system_stats` responds.
      Kill it with Ctrl-C.

- [ ] Install node packs (each via `ComfyUI-Manager` or git-clone into
      `custom_nodes/`):
        - **Flux**: upstream ComfyUI supports Flux natively as of
          late 2024 — no extra nodes needed for `flux1-dev`.
        - **Depth Anything V2**: `https://github.com/Fannovel16/comfyui_controlnet_aux`
          or a V2-specific pack. Confirm a `DepthAnythingV2Preprocessor`
          node appears in the UI.
        - **DepthFlow parallax**: `https://github.com/BrokenSource/DepthFlow`
          has a ComfyUI integration; alternatively install it as a
          Python package and use a custom node. The graph's
          `DepthFlowParallaxRender` node must accept
          `image, depth, motion_mode, duration_s, fps, seed`.
        - **Video output**: VideoHelperSuite
          (`https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite`)
          provides `VHS_VideoCombine` used in `depth_parallax.json`.

- [ ] Download Flux model weights into `models/unet/` + `models/vae/`
      + `models/clip/`:
        - `flux1-dev.safetensors` (~11 GB) or `flux1-schnell.safetensors` (~23 GB)
        - `ae.safetensors` (Flux VAE)
        - `t5xxl_fp8_e4m3fn.safetensors`
        - `clip_l.safetensors`
      After all four, `ls -lh models/unet` should confirm sizes.

- [ ] Download Depth Anything V2 checkpoint:
      `depth_anything_v2_vitl.pth` into the pack's expected dir
      (typically `models/depthanything/`).

- [ ] Start ComfyUI as a systemd service or Docker container so it
      survives reboots. Example systemd unit at
      `/etc/systemd/system/comfyui-vesper.service`:
      ```ini
      [Unit]
      Description=Vesper ComfyUI
      After=network-online.target docker.service
      [Service]
      WorkingDirectory=/opt/vesper/ComfyUI
      ExecStart=/opt/vesper/ComfyUI/venv/bin/python main.py --listen 0.0.0.0 --port 8188
      Restart=on-failure
      User=vishalan
      [Install]
      WantedBy=multi-user.target
      ```
      Then: `sudo systemctl enable --now comfyui-vesper`.

- [ ] Port 8188 reachable from the laptop:
      `curl http://192.168.29.237:8188/system_stats | head -c 200`
      must return JSON.

## S2 — install the Vesper workflow JSONs

The repo ships stub templates at `comfyui_workflows/flux_still.json`
and `comfyui_workflows/depth_parallax.json`. Both have a `_meta`
block listing the substitution tokens and flagging which node
`class_type` strings need to match YOUR installed node pack (node
names drift between packs, e.g. `DepthAnythingV2Preprocessor` vs
`ControlNetPreprocessor_DepthAnythingV2`).

- [ ] For each workflow:
        1. Open it in a text editor on the server.
        2. Confirm every `class_type` matches a node that appears in
           your running ComfyUI's `/object_info` endpoint:
           `curl http://localhost:8188/object_info | jq 'keys' | grep -i depth`.
        3. Adjust `model_name` / `ckpt_name` to the exact filename you
           downloaded in S1.
        4. Smoke-test directly against ComfyUI via a manual
           `POST /prompt` with the token substitution already done.
           ```bash
           curl -X POST http://localhost:8188/prompt -d @test_flux_prompt.json
           ```

- [ ] The pipeline consults these workflow files by their repo path,
      so no install step beyond ensuring they sit under
      `/home/vishalan/social_media/comfyui_workflows/` on the server.

## S3 — chatterbox ref file

- [ ] Owner records 3 candidate Archivist whisper clips (8-15 s each,
      44.1 or 48 kHz mono WAV). Blind-rate them against two reference
      2026 horror channels; pick one.
- [ ] Copy winning `.wav` to the bind-mount path the chatterbox
      compose service uses. Per `deploy/portainer/docker-compose.yml`,
      this is typically `/home/vishalan/social_media/assets/vesper/refs/archivist.wav`.
      Set mode 0600: `chmod 600 assets/vesper/refs/archivist.wav`
      (Security Posture S3 — biometric, gitignored).
- [ ] Restart chatterbox to pick up the new mount if it was already
      running: `docker compose restart chatterbox`.
- [ ] Verify from the laptop:
      `curl http://192.168.29.237:7777/refs/list | jq`
      must include `archivist.wav`.

## S4 — Vesper SFX + overlay pack sourcing

- [ ] Source CC0-licensed `.wav`s for the Vesper SFX pack under
      `assets/vesper/sfx/`:
        - `cut_*.wav` (heavy cuts between hero shots; 2 variants min)
        - `punch_*.wav` (sub-bass thumps for hero-beat entries; 2 variants)
        - `reveal_*.wav` (risers/reverb-tails for keyword punches; 2-3)
        - `tick_*.wav` (background ticks for quiet beats; 1-2)
      Register map lives in `channels/vesper.py::_register_sfx_pack`.
      Missing files cause SFX mix to silently no-op (WARN in pipeline
      log) — the short will still publish with raw voice.

- [ ] Source four overlay `.mp4`s under `assets/vesper/overlays/`:
      `grain.mp4`, `dust.mp4`, `flicker.mp4`, `fog.mp4`. Each 30-60 s
      looping source video, 1080x1920 (9:16), CC0. Length >= longest
      expected short (90 s v1) so the overlay loops at most once.

- [ ] The overlay pack is the ONLY pre-launch asset whose absence
      degrades the short visibly (no grain → synthetic-looking).
      Missing SFX / voice ref degrade audio quality; missing overlay
      degrades visual quality.

## S5 — env file

- [ ] Copy `.env.example` → `.env` on BOTH server and laptop. Fill:

      ```
      ANTHROPIC_API_KEY=sk-ant-...
      REDIS_URL=redis://192.168.29.237:6379/0
      COMFYUI_URL=http://192.168.29.237:8188
      CHATTERBOX_ENDPOINT=http://192.168.29.237:7777
      CHATTERBOX_REFERENCE_AUDIO=/app/refs/archivist.wav
      POSTIZ_URL=http://192.168.29.237:3000
      POSTIZ_API_KEY=<your postiz token>
      TELEGRAM_BOT_TOKEN=<bot token>
      TELEGRAM_OWNER_USER_ID=<your id>
      FAL_API_KEY=<optional, for Flux fallback>
      ```
- [ ] `chmod 600 .env` (never cat/head/grep per auto-memory).

## S6 — Postiz profile + integrations

- [ ] Postiz UI → create `vesper` profile.
- [ ] Under that profile, connect IG + YT + TikTok accounts for
      `@vesper.tv` (or your claimed handle). AI-disclosure toggle
      already fires per-publish via the pipeline, but enable it at
      the profile level too (belt-and-braces).
- [ ] Probe from the laptop:
      ```bash
      curl -H "Authorization: $POSTIZ_API_KEY" \
           http://192.168.29.237:3000/api/public/v1/integrations | jq \
           '.[] | select(.profile=="vesper") | {id, identifier, profile}'
      ```
      Expect three rows: `instagram`, `youtube`, `tiktok`.

## S7 — laptop-side automated verification

From the laptop (repo root):

- [ ] `cd scripts && python3 -m vesper_pipeline.doctor`
      Must exit 0 (warnings allowed; no blocking failures).

- [ ] `cd scripts && python3 -m vesper_pipeline.probe`
      Must exit 0. Every required probe reports `[ok]`; fal.ai may
      `[skip]` without breaking.

If either exits 2, fix the reported items and re-run before S8.

## S8 — single-short smoke test

- [ ] On the laptop:
      ```bash
      VESPER_MAX_SHORTS_PER_RUN=1 bash deploy/run_vesper_pipeline.sh
      ```

- [ ] Follow the pipeline log:
      `tail -f logs/vesper_pipeline_$(date +%Y-%m-%d).log`

- [ ] Expected timeline:
        1. `topic_signal` — Reddit fetch completes in ~10-20 s.
        2. `draft_story` — Archivist writer completes in ~15-30 s.
        3. `voice_preflight` — chatterbox health + refs list: <1 s.
        4. `voice_generate` — chatterbox TTS: 60-180 s for a 200-word
           script depending on VRAM contention.
        5. `transcribe_voice` — faster-whisper local: 5-15 s.
        6. `plan_timeline` — Haiku call: ~5 s.
        7. `mix_sfx` — ffmpeg: 1-3 s (no-op if pack empty).
        8. `generate_stills` — Flux local × ~15 beats: 150-300 s
           (~10-20 s/image on 3090).
        9. `animate_still_beats` — parallax × ~5 beats: 50-100 s.
           Hero I2V beats skipped in v1 (Unit 10 deferred — no
           workflow yet).
        10. `assemble_video` — MoviePy concat + audio + overlay +
            zoom + captions: 30-60 s.
        11. `render_thumbnail` — PIL: <1 s.
        12. `request_approval` — Telegram preview card delivered; wait
            on owner tap.
        13. `publish` — Postiz × 3 platforms: 5-20 s.
        14. `log_analytics` — SQLite insert: <1 s.

- [ ] Approve via Telegram. Confirm the short appears on all three
      platforms. Record the job UUID for future `/takedown` if needed.

- [ ] If something fails, match against `vesper-incident-response.md`.
      First-run failures most commonly trip:
        - **ComfyUI class_type mismatch** — edit the workflow JSON to
          match your installed node names. Restart ComfyUI (model
          cache invalidates).
        - **Postiz integration ID not found** — the profile/identifier
          combination in `list_integrations()` must match what the
          pipeline requests. Check Postiz UI for exact profile name.
        - **Telegram 400 invalid chat** — confirm
          `TELEGRAM_OWNER_USER_ID` is your NUMERIC id (use @userinfobot).

## S9 — enable LaunchAgent + backup job

Once S8 is green:

- [ ] Load both LaunchAgents from the laptop:
      ```bash
      cp deploy/com.vesper.pipeline.plist ~/Library/LaunchAgents/
      cp deploy/com.vesper.sqlite_backup.plist ~/Library/LaunchAgents/
      launchctl load -w ~/Library/LaunchAgents/com.vesper.pipeline.plist
      launchctl load -w ~/Library/LaunchAgents/com.vesper.sqlite_backup.plist
      ```

- [ ] Confirm:
      ```bash
      launchctl list | grep com.vesper
      ```
      Two rows with PID `-`.

- [ ] Let the next-scheduled run fire naturally (09:30 local for
      the pipeline, 04:30 for the backup). Tail logs the next morning
      and match against `vesper-daily-ops-runbook.md` criteria.

## Failure-mode pointers

Map each server-side failure back to the right runbook:

| Failure | Runbook |
|---|---|
| ComfyUI stops responding mid-run | vesper-gpu-contention.md |
| Postiz rate budget exhausted | vesper-rate-budget-breach.md |
| DMCA notice arrives | vesper-dmca-response.md |
| Chatterbox ref missing | vesper-incident-response.md |
| Any other first-day pipeline failure | vesper-incident-response.md "Unknown failure" branch |
