---
title: Postiz Delete Post Research Spike
date: 2026-04-09
status: blocking-gate-for-unit-17-of-plan-2026-04-08-001
---

# Postiz Delete Post Research Spike

## Verdict

**Hybrid: Outcome A + Outcome B are both required.**

Postiz DOES expose a public `DELETE /api/public/v1/posts/:id` endpoint, but code
inspection of the running `commoncreed_postiz` container shows it is a
**soft-delete only**: it sets `Post.deletedAt` in Postgres and terminates any
running Temporal workflow for the post group. It does **not** call the Instagram
Graph API or the YouTube Data API to remove the published asset from the
platform. If we rely on the Postiz endpoint alone, a creator who invokes opt-out
would see their post disappear from Postiz's dashboard but stay live on IG /
YouTube — failing the Unit 17 24-hour-removal guarantee.

The good news: all the raw material we need for a direct per-platform delete is
already sitting in the Postiz Postgres database that the sidecar already reads.
Tokens are stored **plaintext** (no encryption-at-rest wrapper in the
`createOrUpdateIntegration` write path), and the per-post platform IDs are
stored on `Post.releaseId` as soon as Postiz publishes.

Unit 17 therefore needs TWO calls per opt-out:

1. Direct platform delete (IG Graph `DELETE`, YouTube `videos.delete`) to
   actually remove the content from the public platform.
2. Postiz `DELETE /api/public/v1/posts/:id` to clean up the Postiz dashboard
   row and cancel any still-pending workflow.

## Chosen mechanism

### Part 1 — Direct platform removal (the load-bearing call)

**Instagram**

- HTTP: `DELETE https://graph.facebook.com/v20.0/{ig_media_id}?access_token={token}`
- `ig_media_id` source: the Postiz DB row `Post.releaseId` for the post whose
  `integrationId` references the IG Integration. Postiz writes this value from
  the `media_publish` response in
  `libraries/nestjs-libraries/src/integrations/social/instagram.provider.js`
  (`const { id: mediaId } = … media_publish?creation_id=…`).
- `token` source: `Integration.token` column for the row where
  `providerIdentifier = 'instagram'` and `profile = 'commoncreed'`. Plaintext,
  no decryption needed. This is exactly the column the existing sidecar helper
  `PostizClient._read_tokens_from_postgres` (sidecar/postiz_client.py lines
  411-445) already queries — Unit 17 can reuse it verbatim.
- Response: `{"success": true}` on 200; 400 with `OAuthException` on a stale
  token. Unit 17 should treat a 400 with `error.code == 190` (token expired) as
  "token expired → ask owner to reconnect IG in Postiz", not as a retry case.

**YouTube**

- Mechanism: `youtube.videos.delete(id=<video_id>)` via
  `google-api-python-client` (preferred) OR raw HTTP
  `DELETE https://www.googleapis.com/youtube/v3/videos?id={video_id}` with
  header `Authorization: Bearer {access_token}`.
- `video_id` source: again `Post.releaseId` for the row whose
  `integrationId` references the YouTube Integration. Postiz writes it from the
  `youtubeClient.videos.insert(...)` response in
  `libraries/nestjs-libraries/src/integrations/social/youtube.provider.js:237`.
- `token` / `refreshToken` source: `Integration.token` and
  `Integration.refreshToken` for the row where `providerIdentifier = 'youtube'`.
  Plaintext. `Integration.tokenExpiration` gives the current expiry — if it's
  past, Unit 17 must refresh first via the standard Google OAuth refresh
  endpoint using `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` from the Postiz
  env (same values the sidecar .env already carries).
- Response: HTTP 204 on success. 404 means already deleted (treat as success
  for the opt-out guarantee). 401/403 → refresh token then retry once.

### Part 2 — Postiz dashboard cleanup

- HTTP: `DELETE {POSTIZ_BASE_URL}/api/public/v1/posts/{post_id}`
- Auth header: `Authorization: <api_key>` (raw API key, NO `Bearer` prefix —
  confirmed from `apps/backend/src/services/auth/public.auth.middleware.js`).
  This matches the convention already used by `PostizClient._request_json`.
- `post_id` is the Postiz `Post.id` (cuid) — different from the platform
  releaseId. Unit 17 gets this either from the `publish_post` return payload at
  the time of posting (store it alongside `releaseId`) or by querying
  `GET /api/public/v1/posts?...`.
- Handler behaviour (from
  `apps/backend/src/public-api/routes/v1/public.integrations.controller.js`
  lines 91-98 + `posts.service.js:425-450` + `posts.repository.js:271-290`):
  looks up the Post's `group`, calls
  `_postRepository.deletePost(orgId, group)` which runs
  `prisma.post.updateMany({where:{organizationId, group}, data:{deletedAt: new Date()}})`,
  then terminates any running Temporal workflow for that post.
- Response: `{error: true}` — yes, literally the string `error:true` even on
  success. This is a Postiz quirk, not a real error. Unit 17 must NOT treat
  this as a failure. The authoritative signal is HTTP 200 with any JSON body.

## Evidence

All evidence gathered via Portainer exec (no DELETE requests were issued to
live Postiz; read-only grep/sed of the compiled backend and Prisma schema).

### 1. Public DELETE endpoint exists

Container `commoncreed_postiz` (id `a2d7f25f800a`, state `running`) on endpoint
3 of Portainer at 192.168.29.211.

From `/app/apps/backend/dist/apps/backend/src/public-api/routes/v1/public.integrations.controller.js`:

```
line 91:  async deletePost(org, id) {
line 92:      Sentry.metrics.count('public_api-request', 1);
line 93:      const getPostById = await this._postsService.getPost(org.id, id);
line 94:      return this._postsService.deletePost(org.id, getPostById.group);
line 96:  deletePostByGroup(org, group) {
line 98:      return this._postsService.deletePost(org.id, group);

line 293: (0, common_1.Delete)('/posts/:id'),
line 301: (0, common_1.Delete)('/posts/group/:group'),
```

So two delete routes exist under the public API base path `/api/public/v1`:
`DELETE /posts/:id` and `DELETE /posts/group/:group`.

### 2. Auth header shape

From `/app/apps/backend/dist/apps/backend/src/services/auth/public.auth.middleware.js`:

```js
const auth = (req.headers.authorization || req.headers.Authorization);
if (!auth) { res.status(401).json({ msg: 'No API Key found' }); return; }
if (auth.startsWith('pos_')) { /* OAuth token path */ }
else { const org = await this._organizationService.getOrgByApiKey(auth); ... }
```

Raw header value, no `Bearer` prefix. Exactly matches the existing
`PostizClient._request_json` which sets `headers = {"Authorization": self.api_key}`.

### 3. Postiz delete is a soft delete only — does NOT hit the platform

From `apps/backend/dist/libraries/nestjs-libraries/src/database/prisma/posts/posts.service.js:425`:

```js
async deletePost(orgId, group) {
    const post = await this._postRepository.deletePost(orgId, group);
    if (post?.id) {
        try {
            const workflows = this._temporalService.client.getRawClient()?.workflow.list({
                query: `postId="${post.id}" AND ExecutionStatus="Running"`,
            });
            for await (const executionInfo of workflows) {
                try {
                    const workflow = await this._temporalService.client.getWorkflowHandle(executionInfo.workflowId);
                    if (workflow && (await workflow.describe()).status.name !== 'TERMINATED') {
                        await workflow.terminate();
                    }
                } catch (err) { }
            }
        } catch (err) { }
    }
    return { error: true };
}
```

And the repository method from
`libraries/nestjs-libraries/src/database/prisma/posts/posts.repository.js:271`:

```js
async deletePost(orgId, group) {
    await this._post.model.post.updateMany({
        where: { organizationId: orgId, group },
        data: { deletedAt: new Date() },
    });
    return this._post.model.post.findFirst({
        where: { organizationId: orgId, group, parentPostId: null },
        select: { id: true },
    });
}
```

No calls into any provider (`instagram.provider`, `youtube.provider`). No
`fetch('https://graph.facebook.com/...DELETE...')`. No `videos.delete`.
The method only mutates Postgres and terminates Temporal workflows (which
matters only for scheduled posts that haven't fired yet). **A post that has
already been published to IG/YT is left on the platform untouched.**

### 4. Post schema has the platform ids we need

From `/app/libraries/nestjs-libraries/src/database/prisma/schema.prisma`:

```prisma
model Post {
  id             String   @id @default(cuid())
  state          State    @default(QUEUE)
  organizationId String
  integrationId  String
  releaseId      String?
  releaseURL     String?
  ...
}
```

And from the IG provider (`instagram.provider.js` lines 426-466), the post path
returns `{ id: mediaId }` from `media_publish`, which Postiz then stores into
`Post.releaseId` via `posts.service.js::updateReleaseId(orgId, postId, releaseId)`.

The YouTube provider (`youtube.provider.js:237`) does the same with
`youtubeClient.videos.insert(...)`.

### 5. Integration tokens are plaintext

From `schema.prisma`:

```prisma
model Integration {
  id                  String   @id @default(cuid())
  internalId          String
  providerIdentifier  String
  type                String
  token               String        // <-- plaintext
  tokenExpiration     DateTime?
  refreshToken        String?       // <-- plaintext
  profile             String?
  ...
}
```

From `integration.repository.js:186` (`createOrUpdateIntegration`), the upsert
writes `token` and `refreshToken` straight into the row with no
`AuthService.fixedEncryption(...)` wrapper (unlike e.g. the third-party
controller which DOES use `fixedEncryption` for its third-party API keys).
`grep -rn fixedEncryption` against
`libraries/nestjs-libraries/src/database/prisma/integrations/` returned zero
matches. So no decryption key needed — the sidecar can SELECT them directly,
as `PostizClient._read_tokens_from_postgres` already does for Instagram (lines
425-440 of `sidecar/postiz_client.py`).

## What Unit 17 should do

Implement a new `PostizClient.delete_post(...)` that takes the sidecar's own
record of the post (the publish log row, which after Unit 7 holds
`postiz_post_id`, `ig_media_id`, `yt_video_id`, `ig_integration_id`,
`yt_integration_id`) and performs three operations, in this order:

1. **Direct Instagram delete.** SELECT `token` FROM `Integration` WHERE
   `id = ig_integration_id` (reuse the existing psycopg2 path in
   `_read_tokens_from_postgres` but parameterise by integration id). Issue
   `DELETE https://graph.facebook.com/v20.0/{ig_media_id}?access_token={token}`
   with a 10-second timeout. Treat HTTP 200 as success, 400 `code 190` as
   "token expired, surface to owner", any other 4xx as permanent failure,
   5xx as retryable (2 attempts, 1s + 2s backoff — the same schedule the
   existing client uses).

2. **Direct YouTube delete.** SELECT `token`, `refreshToken`,
   `tokenExpiration` FROM `Integration` WHERE `id = yt_integration_id`. If
   expired, refresh via `https://oauth2.googleapis.com/token` using
   `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` from env. Then call
   `googleapiclient.discovery.build('youtube','v3',credentials=creds)
   .videos().delete(id=yt_video_id).execute()`. Treat 204 or 404 as success.
   401/403 after a fresh refresh → permanent failure (surface to owner).

3. **Postiz dashboard cleanup (best-effort).** `DELETE
   {POSTIZ_BASE_URL}/api/public/v1/posts/{postiz_post_id}` using the existing
   `_request_json` helper. A non-2xx here should NOT fail the overall delete:
   the platform removal (steps 1+2) is the load-bearing guarantee; Postiz
   dashboard cleanup is just housekeeping so the publish queue view stays
   accurate.

Also: when Unit 7's `publish_post` receives the Postiz response, it MUST
capture and persist `postiz_post_id` into the sidecar's publish log alongside
`ig_media_id` and `yt_video_id` — otherwise Unit 17 won't have the id needed
for step 3. The Postiz `POST /posts` response returns an array of created
posts; each carries its own `id`. The sidecar schema change (adding a
`postiz_post_id` column) is a prerequisite for Unit 17 and should be added to
Unit 7's scope in the plan, or called out as its own micro-unit preceding 17.

Do not send any test DELETE against live posts while implementing — dry-run
against a disposable staged post first, or test the IG/YT calls against a
self-hosted test account.
