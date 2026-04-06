# CommonCreed Local Docker Dev Guide

Run the full CommonCreed stack (Postiz + Postgres + Redis + sidecar) on your Mac or Linux dev machine using the same `docker-compose.yml` that deploys to Synology/Portainer. Use this to iterate before pushing anything to the NAS.

**Target audience**: developers running on macOS (Docker Desktop) or Linux (Docker Engine). If you're deploying to Synology, read `README.md` in this directory instead.

---

## 1. Prerequisites

- **Docker Desktop 4.30+** (macOS) or **Docker Engine 24+** with `docker compose` plugin (Linux)
- **8 GB RAM minimum** allocated to Docker (Docker Desktop → Settings → Resources)
- **Python 3.9+** on the host (for running unit tests outside the container)
- **`git`** with this repo checked out
- **Ports 5000 and 5050 free** on the host (Postiz on 5000, sidecar on 5050)
- **Outbound HTTPS** — the containers need to reach Anthropic, Google, fal.ai, Pexels, ElevenLabs, and Telegram APIs

Verify:
```bash
docker --version              # >= 24.0
docker compose version        # >= 2.27
python3 --version             # >= 3.9
```

---

## 2. Clone + checkout the branch

```bash
git clone git@github.com:Vishalan/social_media.git
cd social_media
git checkout feat/end-to-end-pipeline   # or whatever branch has Plan 002
```

---

## 3. Create the `.env` file

The stack reads configuration from a single `.env` file at the **repo root** (not in `deploy/portainer/`). This matches the Synology deployment's mount path convention.

```bash
cp deploy/portainer/.env.example .env
```

Open `.env` and fill in the values. **Every line that starts with `changeme-` must be replaced.** Quick reference for what each key is for:

| Key | Source | Required for |
|---|---|---|
| `POSTGRES_PASSWORD` | generate a long random string | Postiz backing store |
| `POSTIZ_JWT_SECRET` | generate a 64-char random string | Postiz session signing |
| `POSTIZ_API_KEY` | **leave as placeholder until after first Postiz startup** | sidecar → Postiz calls |
| `ANTHROPIC_API_KEY` | https://console.anthropic.com/settings/keys | script + topic + caption gen |
| `ELEVENLABS_API_KEY` | https://elevenlabs.io/app/settings/api-keys | voice gen |
| `VEED_API_KEY` | https://fal.ai/dashboard/keys | avatar gen (VEED Fabric via fal.ai) |
| `FAL_API_KEY` | same as above (fal.ai account) | same endpoint |
| `PEXELS_API_KEY` | https://www.pexels.com/api/new | b-roll + thumbnail backgrounds |
| `TELEGRAM_BOT_TOKEN` | `@BotFather` on Telegram → `/newbot` | approval bot |
| `TELEGRAM_CHAT_ID` | send any message to your bot, then `curl https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id` | where approval previews land |
| `SIDECAR_ADMIN_PASSWORD` | generate any long password | dashboard login |
| `GMAIL_OAUTH_PATH` | `/secrets/gmail_oauth.json` (container path) | Gmail trigger — set up in step 6 |
| `POSTIZ_BASE_URL` | `http://postiz:5000` (internal Docker DNS — do not change) | sidecar → Postiz |

Generate strong random values:
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

**Do not commit `.env`.** It's gitignored — verify with `git check-ignore -v .env`.

---

## 4. First boot — bring up Postiz + Postgres + Redis

Start the non-sidecar services first so you can OAuth-connect social accounts before the sidecar tries to talk to Postiz:

```bash
cd deploy/portainer
docker compose up -d postgres redis postiz
```

Watch the logs:
```bash
docker compose logs -f postiz
```

Wait for the line `Postiz is ready`. On first boot this takes 30-60 seconds (Postiz runs DB migrations). If it hangs longer than 2 minutes, check:
```bash
docker compose ps          # all three should be "healthy"
docker compose logs postgres    # for DB issues
```

Open http://localhost:5000 in a browser. You should see the Postiz login screen.

---

## 5. Bootstrap Postiz (one-time manual step)

### 5.1 Create the admin user

1. Register the first user via the Postiz UI (Register link). This becomes your admin.
2. **Once the admin exists**, edit `.env` and set `POSTIZ_DISABLE_REGISTRATION=true`, then restart Postiz:
   ```bash
   docker compose up -d postiz
   ```
   This closes the open-registration hole.

### 5.2 Get a Postiz API key

1. In the Postiz UI, navigate to Settings → API Keys (or similar)
2. Create a new API key with full posting permissions
3. Copy the key into your `.env` as `POSTIZ_API_KEY=...`

### 5.3 Connect social accounts

For each account CommonCreed will post from:

**Instagram** (requires a Facebook Business account and a connected Instagram Business profile):
1. Postiz UI → Integrations → Instagram → Connect
2. Authorize through Facebook
3. Repeat for `@commoncreed` and `@vishalan.ai`

**YouTube** (requires a Google account with YouTube Data API enabled):
1. Postiz UI → Integrations → YouTube → Connect
2. Authorize through Google
3. Repeat for `@common_creed` and `@vishalangharat`

After connecting all four accounts, **post a test message from Postiz UI** to each to verify they work end-to-end.

---

## 6. Set up Gmail OAuth for the daily trigger

The sidecar's daily trigger reads newsletters from `reachcommoncreed@gmail.com` via the Gmail API. This needs a one-time OAuth flow.

### 6.1 Create a Google Cloud project + enable Gmail API

1. https://console.cloud.google.com/ → create project `commoncreed-pipeline`
2. APIs & Services → Library → enable **Gmail API**
3. APIs & Services → OAuth consent screen → External → fill in app name, user support email, developer email → add scope `https://www.googleapis.com/auth/gmail.readonly` → add `reachcommoncreed@gmail.com` as a test user
4. APIs & Services → Credentials → Create Credentials → OAuth client ID → Desktop app → download the client secret JSON

### 6.2 Run the OAuth flow

On your host (outside Docker):

```bash
python3 -m pip install --user google-auth-oauthlib google-auth google-api-python-client
```

```bash
python3 <<'PY'
from google_auth_oauthlib.flow import InstalledAppFlow
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
flow = InstalledAppFlow.from_client_secrets_file('client_secret.json', SCOPES)
creds = flow.run_local_server(port=0)
with open('gmail_oauth.json', 'w') as f:
    f.write(creds.to_json())
print("Saved gmail_oauth.json")
PY
```

This opens a browser, asks you to sign in as `reachcommoncreed@gmail.com`, and saves the token JSON.

### 6.3 Mount the token into the sidecar

```bash
mkdir -p secrets
mv gmail_oauth.json secrets/gmail_oauth.json
chmod 600 secrets/gmail_oauth.json
```

Edit `deploy/portainer/docker-compose.yml` to add a volume mount on the `commoncreed_sidecar` service (if not already present):

```yaml
    volumes:
      - ../../secrets/gmail_oauth.json:/secrets/gmail_oauth.json:ro
```

**For local dev only.** The Synology deployment uses a different path; this is a dev override.

---

## 7. Build + start the sidecar

```bash
cd deploy/portainer
docker compose up -d --build commoncreed_sidecar
```

The first build takes 3-5 minutes (it pulls Python 3.11 slim, ffmpeg, Chromium deps, and installs 15+ Python packages). Subsequent builds are cached.

Watch the logs:
```bash
docker compose logs -f commoncreed_sidecar
```

Wait for the line `Uvicorn running on http://0.0.0.0:5050`.

---

## 8. Verify the stack is healthy

### 8.1 Sidecar health endpoint

```bash
curl http://localhost:5050/health | python3 -m json.tool
```

Expected:
```json
{
  "ok": true,
  "pipeline_code_visible": true,
  "env_readable": true,
  "db_writable": true,
  "docker_socket_accessible": true,
  "version": "0.1.0"
}
```

If any flag is `false`, the response will be HTTP 503. Debug:

| Flag false | Fix |
|---|---|
| `pipeline_code_visible` | Check `scripts/` mounted at `/app/scripts` in compose |
| `env_readable` | Check `.env` mounted at `/env/.env` in compose |
| `db_writable` | Check `sidecar_db` volume; container user needs write perms |
| `docker_socket_accessible` | Check `/var/run/docker.sock` bind mount (macOS: `/var/run/docker.sock.raw` on some Docker Desktop versions) |

### 8.2 Log in to the dashboard

Open http://localhost:5050 — you'll be redirected to `/login`. Enter any username (e.g., `admin`) and the `SIDECAR_ADMIN_PASSWORD` from `.env`.

You should land on the Summary page showing mock data for runs/cost/approvals.

### 8.3 Run the sidecar test suite

From the host (not inside the container):
```bash
python3 -m pytest sidecar/tests/ -q
```

Expected: **161 passed** (as of Plan 002 completion).

### 8.4 Run the existing pipeline tests

```bash
python3 -m pytest scripts/thumbnail_gen/tests/ scripts/video_edit/tests/ scripts/posting/tests/ -q
```

Expected: **50 passed**.

---

## 9. End-to-end smoke test (no API cost)

This runs the existing pipeline in **reuse mode**, which replays cached audio + avatar clips from a previous successful run without burning VEED/ElevenLabs credits.

### 9.1 Prerequisites

You need cached assets from a previous full run. If you don't have them, skip to section 10 for the full-cost run.

### 9.2 Trigger the pipeline via the sidecar

Option A — let the scheduler pick it up (slower):

Wait until the next minute past `:00` or `:30`. The sidecar's `process_pending_runs` job polls every 30s. You can insert a fake pending row:

```bash
docker compose exec commoncreed_sidecar python3 -c "
from sidecar.db import init_db, insert_pipeline_run
from sidecar.config import load_settings
s = load_settings()
conn = init_db(str(s.SIDECAR_DB_PATH))
run_id = insert_pipeline_run(
    conn,
    topic_title='Google launches Veo 3.1 Lite for faster AI video',
    topic_url='https://blog.google/technology/google-deepmind/veo-3-1-lite/',
    topic_score=9.5,
    selection_rationale='Test run via local dev guide',
    source_newsletter_date='2026-04-06',
)
print(f'inserted run_id={run_id}')
"
```

Then watch `docker compose logs -f commoncreed_sidecar` for the scheduler to pick it up.

Option B — invoke directly (faster for dev):

```bash
docker compose exec commoncreed_sidecar python3 -c "
import asyncio
from sidecar.jobs.run_pipeline import process_pending_runs
print(asyncio.run(process_pending_runs()))
"
```

### 9.3 Verify

- `curl http://localhost:5050/runs` → new row with status `generated`
- Telegram should receive an approval preview
- Dashboard `/runs/<id>` shows the video + thumbnail + captions

---

## 10. Full-cost end-to-end test (~$1.96 per video)

**Only run this when you're ready to spend real money.** Uses live VEED avatar gen, live ElevenLabs voice, live Sonnet script, and actually posts to IG/YT if you approve.

### 10.1 Trigger daily_trigger manually

```bash
docker compose exec commoncreed_sidecar python3 -c "
import asyncio
from sidecar.jobs.daily_trigger import run_daily_trigger
print(asyncio.run(run_daily_trigger()))
"
```

This reads today's TLDR AI email, scores topics, inserts 2 pending_generation rows. The APScheduler then picks them up within 30s.

### 10.2 Watch the flow

```bash
docker compose logs -f commoncreed_sidecar
```

You'll see:
1. Gmail fetch
2. Sonnet topic extraction + scoring
3. First pipeline subprocess starts (scripts/smoke_e2e.py in reuse=0 mode)
4. ~3-5 min later: thumbnail + video ready, caption_gen, Telegram preview
5. Second pipeline subprocess starts
6. ~3-5 min later: second preview

Expected total time: ~10 min. Expected total cost: ~$4 ($2/video × 2).

### 10.3 Approve or reject via Telegram

Tap the inline buttons. Approve triggers the publish flow (Postiz → IG Collab verify → post lands on IG and YT). Reject marks the run rejected with no posting.

If you do nothing, at `scheduled_slot - 30min` (e.g., 08:30 for the 09:00 slot) the auto-approve cutoff fires and publishes automatically.

---

## 11. Common operations

### Stop the whole stack
```bash
docker compose stop
```

### Restart one service
```bash
docker compose restart commoncreed_sidecar
```

### Rebuild sidecar after code change
```bash
docker compose up -d --build commoncreed_sidecar
```

Or for hot reload during heavy dev, mount the sidecar code as a volume (dev-only override — don't commit):

```yaml
# docker-compose.override.yml (gitignored)
services:
  commoncreed_sidecar:
    volumes:
      - ../../sidecar:/app/sidecar
    command: ["uvicorn", "sidecar.app:app", "--host", "0.0.0.0", "--port", "5050", "--reload"]
```

### View the SQLite DB
```bash
docker compose exec commoncreed_sidecar sqlite3 /app/db/sidecar.db ".tables"
docker compose exec commoncreed_sidecar sqlite3 /app/db/sidecar.db "SELECT id, status, topic_title FROM pipeline_runs ORDER BY created_at DESC LIMIT 10"
```

### Tail Postiz logs
```bash
docker compose logs -f postiz
```

### Wipe everything and start fresh
```bash
docker compose down -v   # -v removes volumes. You lose Postiz accounts, sidecar DB, everything.
```

---

## 12. Troubleshooting

### Sidecar container keeps restarting

Check `docker compose logs commoncreed_sidecar`. Common causes:
- Missing required env vars — sidecar raises on startup if `ANTHROPIC_API_KEY` or `SIDECAR_ADMIN_PASSWORD` is unset
- `.env` mount path wrong — check volume mount in compose
- Port 5050 already taken on host — `lsof -i :5050`

### Postiz login page shows blank screen

- Check browser console for CORS errors
- Verify `POSTIZ_MAIN_URL` in `.env` matches the URL you're visiting (`http://localhost:5000` for local dev)

### Telegram bot silent

- Verify `TELEGRAM_BOT_TOKEN` is correct: `curl https://api.telegram.org/bot<TOKEN>/getMe`
- Verify `TELEGRAM_CHAT_ID` — send a message to your bot, then `curl https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id`
- Check sidecar logs: `docker compose logs commoncreed_sidecar | grep -i telegram`

### Pipeline subprocess fails with "ModuleNotFoundError: No module named 'scripts'"

The subprocess runs with `cwd=scripts/`. If you see this, something is trying to import `scripts.X` from within the subprocess. Fix the dual-import pattern (see `scripts/thumbnail_gen/step.py` for the canonical try-except).

### "Gmail trigger: no newsletter within 24h" every morning

- Verify the OAuth token is valid: tokens expire if unused for 6+ months
- Re-run section 6 to mint a fresh token
- Verify the sender filter: `sidecar/config.py` has `TLDR_SENDER` default; override in `.env` if needed

### APScheduler jobs not firing

```bash
docker compose exec commoncreed_sidecar python3 -c "
from sidecar.app import app
sched = getattr(app.state, 'scheduler', None)
if sched is None:
    print('scheduler is None — startup failed, check logs')
else:
    for j in sched.get_jobs():
        print(j)
"
```

If scheduler is None, the SQLite jobstore construction probably failed. Check `docker compose logs commoncreed_sidecar | grep -i schedul`.

---

## 13. Next steps

- **Deploy to Synology**: follow `README.md` in this directory. The same `docker-compose.yml` works with path-only adjustments.
- **Customize the topic scorer**: edit `sidecar/topic_selector.py` to tune the Sonnet prompt
- **Tune the retention policy**: `sidecar/config.py → RETENTION_DAYS` (default 14)
- **Test the duplicate guard**: re-run the daily trigger on the same day and verify the second attempt blocks

---

## 14. Safety checklist before production

- [ ] `.env` file is NOT committed (`git check-ignore -v .env`)
- [ ] `POSTIZ_DISABLE_REGISTRATION=true` after admin user created
- [ ] `SIDECAR_ADMIN_PASSWORD` is not the default placeholder
- [ ] All 4 social accounts connected and test-posted
- [ ] Gmail OAuth token fresh and saved to `secrets/gmail_oauth.json`
- [ ] Telegram bot tested (send a manual preview via the sidecar)
- [ ] Full-cost smoke test (section 10) passes end-to-end with both platforms actually posting
- [ ] Weekly cost report mock-tested (`docker compose exec commoncreed_sidecar python3 -c "import asyncio; from sidecar.jobs.cost_report import send_weekly_cost_report; print(asyncio.run(send_weekly_cost_report()))"`)
- [ ] Dashboard accessible only on LAN (if exposing beyond localhost, add reverse proxy + HTTPS)
