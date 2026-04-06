# CommonCreed Posting Stack — Synology + Portainer Deployment

This directory contains the Docker Compose stack for the CommonCreed posting
layer: **Postiz** (self-hosted OSS, AGPL-3.0) backed by **Postgres** and
**Redis**, designed to run on a Synology DS1520+ via Portainer.

This is **Unit 1** of the end-to-end pipeline plan — Postiz only. The
CommonCreed sidecar service (Gmail trigger, topic scoring, Telegram approval
loop, dashboard) lands in Unit 2 and is already stubbed in
`docker-compose.yml` as a commented placeholder block.

---

## 1. Prerequisites

- **Synology DSM 7.0 or newer** on the DS1520+ (or any other Synology
  x86_64 model — the stack is portable).
- **Portainer CE** installed on the Synology and reachable on the LAN.
  If you don't already run Portainer, install it via Container Manager:
  search for `portainer/portainer-ce` and deploy it on port 9000/9443.
- **Container Manager** package installed from Synology Package Center
  (this provides the underlying Docker engine on DSM 7+).
- **At least 8 GB of RAM available** on the NAS. The DS1520+ ships with
  8 GB stock; if you've upgraded to 18 GB, even better — pipeline subprocess
  peaks become a non-event.
- **A LAN hostname** for the NAS, e.g. `your-nas.local` or a static IP.
  Postiz needs a stable URL for OAuth callbacks to work.
- **Outbound HTTPS** from the NAS — required for Postiz to reach Instagram,
  YouTube, and any other social platform OAuth endpoints.

---

## 2. NAS folder setup

The stack uses **named Docker volumes** by default (managed by Portainer
under `/volume1/@docker/volumes/`). If you prefer explicit bind mounts so
backups and inspection are easier, create the following layout on the NAS
first.

Recommended layout:

```
/volume1/docker/commoncreed/
├── .env                    # copied from .env.example, filled in
├── postgres_data/          # Postgres data dir
├── postiz_uploads/         # Postiz media library
├── postiz_config/          # Postiz config + state
├── commoncreed_output/     # Generated videos / thumbnails (Unit 2)
└── sidecar_db/             # SQLite for the sidecar (Unit 2)
```

Create the folders from the Synology terminal (SSH in as an admin user):

```bash
sudo mkdir -p /volume1/docker/commoncreed/{postgres_data,postiz_uploads,postiz_config,commoncreed_output,sidecar_db}
sudo chown -R 1026:100 /volume1/docker/commoncreed   # synology default docker uid:gid
sudo chmod -R 750 /volume1/docker/commoncreed
sudo chmod 600 /volume1/docker/commoncreed/.env       # after you create it
```

The UID `1026` and GID `100` are Synology's default for the Docker package
user. If yours differs (check with `id`), use your actual values.

If you'd rather skip bind mounts and use named volumes (the default in this
compose file), you can skip this section entirely. Portainer will manage
the volumes for you.

---

## 3. Deploy the stack via Portainer

1. **Copy the `.env` file**

   On your laptop, copy `.env.example` to `.env` and fill in EVERY value.
   Pay special attention to:

   - `POSTGRES_PASSWORD` — generate a long random string.
   - `POSTIZ_JWT_SECRET` — generate with `openssl rand -hex 48`.
   - `POSTIZ_MAIN_URL` / `POSTIZ_FRONTEND_URL` — set to the hostname you'll
     reach Postiz at, e.g. `http://your-nas.local:5000`.
   - `DATABASE_URL` — must match the `POSTGRES_*` values above.
   - `POSTIZ_DISABLE_REGISTRATION=false` for the first deploy so you can
     create your admin user. Flip to `true` after that and redeploy.

   Then upload `.env` to `/volume1/docker/commoncreed/.env` on the NAS
   (e.g. via File Station, SCP, or the Portainer file editor).

2. **Open Portainer → Stacks → Add stack**

3. **Name the stack** `commoncreed`.

4. **Choose "Web editor"** and paste the contents of `docker-compose.yml`
   from this directory. Alternatively, use the "Repository" mode and
   point Portainer at this Git repo's `deploy/portainer/` path if you
   manage your stacks via GitOps.

5. **Load environment variables**: scroll down to the "Environment
   variables" section, click "Load variables from .env file", and select
   the `.env` you just placed on the NAS. Verify each variable is loaded
   and that no placeholder values (`changeme-...`) remain.

6. **Click "Deploy the stack"**. First deploy will pull the Postiz, Postgres,
   and Redis images — expect 2–5 minutes depending on your bandwidth.

---

## 4. First-run verification

Once the stack is deployed, in Portainer:

- Navigate to **Containers**. You should see three containers:
  - `commoncreed_postgres` — status `running (healthy)`
  - `commoncreed_redis` — status `running (healthy)`
  - `commoncreed_postiz` — status `running (healthy)` (allow ~90 s for
    Postiz's initial DB migration on first boot)
- Click into `commoncreed_postiz` → **Logs**. Look for "ready" / "listening
  on 5000" / no stack traces.
- In a browser on the LAN, visit `http://your-nas.local:5000`. You should
  see the Postiz login screen.
- Register your admin user. Then SSH back into the NAS and edit
  `/volume1/docker/commoncreed/.env` to set `POSTIZ_DISABLE_REGISTRATION=true`,
  and redeploy the stack from Portainer ("Update the stack" → "Re-pull
  images and redeploy" off, just "Update").

---

## 5. Connect the social accounts (manual OAuth bootstrap)

This is a one-time per-account dance. Postiz handles the OAuth flow for
each platform; you just need to be logged into the right account in the
same browser.

### 5a. `@commoncreed` Instagram (Business)

**Prerequisite:** `@commoncreed` must be an Instagram **Business** or
**Creator** account, AND it must be linked to a Facebook Page that you
admin. The Instagram Graph API (which Postiz uses for posting) requires
this linkage — there is no way around it. If you only have a personal IG
account, convert it to Business in the Instagram app under
Settings → Account → Switch to professional account, then link it to a
Facebook Page from the same screen.

Steps:

1. In the same browser where you're logged into Postiz, also log into
   Facebook as the user who admins the FB Page linked to `@commoncreed`.
2. In Postiz → **Channels** → **Add channel** → **Instagram**.
3. Postiz redirects to Facebook's OAuth screen. Approve the requested
   permissions (`instagram_basic`, `instagram_content_publish`,
   `pages_show_list`, `pages_read_engagement`).
4. Pick the FB Page linked to `@commoncreed`. Postiz pulls the IG
   Business account through that Page.
5. Confirm the channel appears in Postiz Channels with `@commoncreed` as
   the account name.

### 5b. `@vishalan.ai` Instagram (Business)

Same as above, but logged into the Facebook user that admins the FB Page
linked to `@vishalan.ai`. If both IG accounts share a single FB account
admin, you can do this immediately after 5a from the same browser session.

Note: Instagram Collab tagging (R11) requires both `@commoncreed` and
`@vishalan.ai` to be connected via Postiz so the sidecar (Unit 2) can
look up `@vishalan.ai`'s IG user ID for the Collab API call.

### 5c. `@common_creed` YouTube channel

**Prerequisite:** A Google Cloud project with the **YouTube Data API v3**
enabled, and an OAuth client ID configured with `http://your-nas.local:5000`
(or whatever your `POSTIZ_FRONTEND_URL` is) as an authorized redirect URI.
If you've never done this:

1. Visit https://console.cloud.google.com → create a project.
2. APIs & Services → Library → enable **YouTube Data API v3**.
3. APIs & Services → Credentials → Create Credentials → OAuth client ID
   → Web application. Add your Postiz frontend URL plus
   `/integrations/social/youtube` (or whatever Postiz logs in its setup
   docs for the redirect URI — Postiz will tell you on the connect screen)
   as an authorized redirect URI.
4. Copy the client ID and client secret into Postiz's YouTube channel
   settings (Postiz prompts for them on first YouTube connect).

Then in Postiz → **Channels** → **Add channel** → **YouTube**:

1. Click connect → Postiz redirects to Google.
2. Pick the Google account that owns the `@common_creed` YouTube channel.
3. Approve the YouTube upload + manage scope.
4. If your Google account manages multiple channels, pick `@common_creed`
   from the brand-account picker.
5. Confirm the channel appears in Postiz Channels with `@common_creed`.

### 5d. `@vishalangharat` YouTube channel

Repeat 5c, picking `@vishalangharat` at the brand-account selector. You
can reuse the same OAuth client ID — Google will let you grant the same
client access to a second channel.

Once all four channels show up under Postiz → Channels, this section is
done.

---

## 6. Reverse proxy notes

Postiz needs a stable hostname for OAuth callbacks and so the LAN browser
can reach it consistently. You have two options on Synology — pick **one**.

### Option A: Synology native reverse proxy (recommended for Unit 1)

This is the path of least resistance. DSM ships with a built-in reverse
proxy that integrates with the Synology firewall and certificate manager.

1. **Control Panel → Login Portal → Advanced → Reverse Proxy → Create**.
2. **Source**:
   - Protocol: `HTTP` (or HTTPS if you've already minted a cert in DSM)
   - Hostname: `postiz.your-nas.local` (or whatever LAN hostname you want)
   - Port: `80`
3. **Destination**:
   - Protocol: `HTTP`
   - Hostname: `localhost`
   - Port: `5000`
4. **Custom Header** tab → enable WebSocket (`Upgrade` and `Connection`
   headers). Postiz uses WebSocket for live UI updates; without this the
   UI works but feels broken.
5. Save and visit `http://postiz.your-nas.local` from the LAN.

After this works, update `.env`:

```
POSTIZ_MAIN_URL=http://postiz.your-nas.local
POSTIZ_FRONTEND_URL=http://postiz.your-nas.local
```

and redeploy the stack.

**Cookie domain note**: Postiz sets its session cookie scoped to the
hostname you load it from. If you connect from `http://192.168.1.10:5000`
once and `http://postiz.your-nas.local` another time, you'll get two
separate sessions and OAuth callbacks may break. **Pick one canonical
hostname and use it everywhere**, including your `POSTIZ_*_URL` env vars.

### Option B: Caddy in a sidecar container (deferred)

If you outgrow the DSM reverse proxy (e.g. you want automatic Let's Encrypt
certs over Tailscale, or path-based routing for the Unit 2 sidecar at
`/commoncreed`), the standard upgrade path is to add a Caddy container to
this stack with a `Caddyfile` that fronts both Postiz and the sidecar.
**Deferred to a future follow-up** — Option A is sufficient for Unit 1.

---

## 7. Post-install sanity check

For each of the four connected accounts, post a test text-only message
from the Postiz UI:

1. Postiz → **New post**.
2. Pick one channel (e.g. `@commoncreed`).
3. Type `CommonCreed deployment test — please ignore.` and pick "Post now".
4. Verify the post lands on the actual social account within 1–2 minutes.
5. Delete the test post from the platform's native UI.
6. Repeat for `@vishalan.ai`, `@common_creed`, and `@vishalangharat`.

If all four post successfully, the OAuth bootstrap is complete and Unit 1
is verified.

---

## 8. NAS reboot test

This validates that the stack survives a power cycle without manual
intervention — a hard requirement for an unattended pipeline.

1. From Portainer, **stop** the `commoncreed` stack.
2. **Reboot the NAS** (Control Panel → Hardware & Power → Restart, or
   `sudo reboot` from SSH).
3. Wait for DSM to come back up and Portainer to be reachable.
4. The stack's `restart: unless-stopped` policy should bring all three
   containers back automatically. Verify in Portainer → Containers that
   `commoncreed_postgres`, `commoncreed_redis`, and `commoncreed_postiz`
   are all running and healthy without you starting them manually.
5. Open the Postiz UI and verify all four social channels still appear
   under Channels and are still marked as connected (no re-OAuth needed).
6. Optionally repeat the test post from section 7 for one channel to
   confirm the tokens still work.

If any container fails to restart, check Portainer logs and
`docker inspect` for the failed container. The most common cause is a
typo in `.env` after editing — revert the change and redeploy.

---

## 9. Rollback / wipe and restart

If something goes irrecoverably wrong and you want to start over:

1. Portainer → Stacks → `commoncreed` → **Stop this stack**.
2. Portainer → Stacks → `commoncreed` → **Delete this stack** (this
   removes the containers but NOT the named volumes by default).
3. To also wipe the data volumes (DESTRUCTIVE — removes Postgres data,
   Postiz uploads, all OAuth tokens):

   ```bash
   docker volume rm commoncreed_postgres_data \
                    commoncreed_postiz_uploads \
                    commoncreed_postiz_config \
                    commoncreed_output \
                    commoncreed_sidecar_db
   ```

   If you used bind mounts under `/volume1/docker/commoncreed/`, delete
   the contents of those directories instead (keep the directories
   themselves).
4. Redeploy the stack from section 3.

You will need to re-do the OAuth bootstrap (section 5) after wiping
volumes — the tokens are stored in Postgres.

---

## 10. Portability note

The same `docker-compose.yml` runs on Mac, Linux, or any other Docker host
without modification. The only things that change between hosts:

- **Bind mount paths**: if you switched the named volumes to bind mounts
  under `/volume1/docker/commoncreed/` for the Synology deploy, change
  those paths to a host-appropriate location on your other machine
  (e.g. `~/docker/commoncreed/` on macOS). Or just use named volumes
  everywhere — the default in this file already does that, so most users
  won't need to touch anything.
- **`.env` file location**: Portainer's "Load from .env file" expects an
  uploaded path; on a vanilla `docker compose up` host, the `.env` just
  needs to live next to the `docker-compose.yml` file.
- **`POSTIZ_MAIN_URL` / `POSTIZ_FRONTEND_URL`**: update these to match
  whatever hostname/IP/port you reach Postiz at on the new host.
- **Reverse proxy**: section 6 is Synology-specific. On a generic Linux
  host you'd use Caddy / Nginx / Traefik directly.

Everything else — image versions, network, volumes, env var names, service
dependencies — is the same across hosts. That's the point.
