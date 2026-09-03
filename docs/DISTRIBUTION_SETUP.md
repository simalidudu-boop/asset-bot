# Distribution engine — setup

15 channels, one queue. Built from the Grain Works patterns
(`docs/DISTRIBUTION_V2.md`).

## How it works

- `publish.py` **enqueues** an asset for every configured channel. No network
  I/O — a dead channel can never stall or fail a publish run.
- `run_content.py` (every 3h) **drains** the queue: bounded, with persisted
  exponential backoff, so a crashed run never double-posts or loses work.
- Queue lives at `state/dist_queue.jsonl`.

## Safety model

| Mechanism | Behaviour |
|---|---|
| Missing credentials | channel **skipped silently**, never failed |
| `DIST_POSTING_MODE` | defaults to **DRAFT** — queues but never posts |
| `DIST_MODE_<CHANNEL>` | per-channel override, e.g. `DIST_MODE_DEVTO=LIVE` |
| Permanent errors (400/401/403/404/409/410/422) | **never retried** |
| Retryable (429/5xx/network) | 5 attempts, backoff 1→2→4→8 min |
| Adapter raises | caught, treated as retryable, run continues |

**Nothing posts until you set `DIST_POSTING_MODE=LIVE`.** Add keys freely and
watch the queue first.

## Operator CLI

```bash
cd engine
python3 dist_core.py status        # queue + which channels are armed
python3 dist_core.py drain 10      # drain up to 10 jobs
python3 dist_core.py retry-failed  # reset failed jobs to pending
```

## Channels and their secrets

| Channel | Secrets | Notes |
|---|---|---|
| `devto` | `DEVTO_API_KEY` | Settings → Extensions. Sets `canonical_url` always. |
| `hashnode` | `HASHNODE_PAT`, `HASHNODE_PUBLICATION_ID` | GraphQL; sets `originalArticleURL`. |
| `telegram` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL_ID` | @BotFather. Text+image+video+PDF. |
| `bluesky` | `BSKY_HANDLE`, `BSKY_APP_PASSWORD` | AT Protocol; app password, not your login. |
| `discord` | `DISCORD_PROMO_WEBHOOKS` | Comma-separated webhook URLs. |
| `gumroad` | `GUMROAD_ACCESS_TOKEN` | Second storefront. |
| `itch` | `ITCH_API_KEY`, `ITCH_USERNAME` | Flat form fields, not Rails-nested. |
| `sellix` | `SELLIX_API_KEY` | Free storefront. |
| `fetchapp` | `FETCHAPP_KEY`, `FETCHAPP_TOKEN` | XML + HTTP Basic. |
| `webflow` | `WEBFLOW_TOKEN`, `WEBFLOW_COLLECTION_ID` | CMS items for SEO. |
| `systemeio` | `SYSTEMEIO_API_KEY` | **Free email list** — the only channel we own. |
| `archive` | `IA_ACCESS_KEY`, `IA_SECRET_KEY` | archive.org/account/s3.php. Permanent backlink. |
| `filepost` | `FILEPOST_API_KEY` | CDN mirror so links don't depend on GH Releases. |
| `buffer` | `BUFFER_ACCESS_TOKEN`, `BUFFER_CHANNEL_IDS` | **X / LinkedIn / Pinterest / Mastodon, legally.** |

Buffer is the important one: it is a *sanctioned* client of X, LinkedIn and
Pinterest, so routing through it gets that reach without us being the party
breaking their automation terms.

**Reddit is deliberately absent.** Self-service API access closed under the
Responsible Builder Policy; commercial use needs a ~$12k/yr agreement, and
their terms explicitly forbid "substantially similar content across
subreddits". Draft-for-human only.

## Recommended rollout

1. Add `DEVTO_API_KEY` + `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHANNEL_ID`.
2. Leave `DIST_POSTING_MODE` unset (DRAFT). Run, then `dist_core.py status`.
3. Flip one channel live: `DIST_MODE_DEVTO=LIVE`. Verify the post.
4. Add channels one key at a time. Go global LIVE when happy.

## Verified behaviour (2026-09-02)

Tested against the live dev.to API and with fault injection:

- real `401` → classified **permanent**, not retried
- real `429` → classified **retryable**, backoff scheduled
- adapter raising an exception → contained, run continued
- DRAFT → queued, nothing posted
- re-enqueue of the same asset+channel → **0 added** (idempotent)
- `max_jobs` cap respected; corrupt queue line skipped, rest survived

## Live key test — 2026-09-03

Six channels tested with real credentials.

| Channel | Result | Detail |
|---|---|---|
| **filepost** | ✅ **WORKING** | Returned a real CDN URL serving **1,038,586 bytes** |
| **systemeio** | ⚠️ auth OK, **plan-capped** | `422 "Please upgrade your plan to create more tags"` — key is valid, free tier tag limit reached |
| **sellapp** | ⚠️ auth OK, **store not provisioned** | See below |
| **webflow** | ⚠️ token valid, **scopes missing** | `403 missing scopes 'cms:write'` (and `cms:read`) |
| **fetchapp** | ❌ **server-side 500** | 500 *with no auth at all* → not our key |
| **sellix** | ❓ **unreachable from sandbox** | `dev.sellix.io`, `sellix.io`, `www.sellix.io` all fail DNS. Untested, not broken |

### sell.app — a false 201

`POST /api/v2/products` returns **201 with a product id**, but:

- `GET /api/v2/products/{id}` → **404 "No query results for model [Listing]"**
- `GET /api/v2/products` → **empty**, with or without `X-STORE-ID`
- the storefront URL → **404**

So the create silently does not persist. The store (`store_id 82606`) most
likely needs finishing/verifying in the sell.app dashboard before the API can
create real listings.

Field notes learned the hard way:
- the field is **`deliverables_type`** (`serials|service|dynamic`), **not
  `type`** — `type` is *always* "invalid" whatever you pass
- `visibility` is required, `description` needs ≥5 chars
- `variants` passed at create time are ignored

**The adapter now VERIFIES with a GET after create** and reports failure rather
than a false success. This is the fourth false-200 in this project (after Whop
`banner_image`, `labels`, and app `base_url`) — never trust a write response
without reading it back.

### What you need to do

| Channel | Action |
|---|---|
| systemeio | upgrade plan, or reuse an existing tag instead of creating one |
| webflow | create a **NEW** token with `cms:read`+`cms:write` — scopes are fixed at creation and cannot be edited (2nd token also had none) |
| sellapp | finish store setup/verification in the dashboard |
| fetchapp | their API is 500-ing; retry later (adapter already treats 5xx as retryable) |
| sellix | test from a normal network — sandbox DNS cannot resolve it |


## Webflow — scopes are set at token creation (2026-09-03)

The second token (`ws-9a20...adba`) had **zero scopes**, same as the first.
Probed endpoint by endpoint:

| Endpoint | Missing scope |
|---|---|
| `/v2/sites` | `sites:read` |
| `/v2/collections/{id}` | `cms:read` |
| `/v2/collections/{id}/items` (POST) | `cms:write` |
| `/v2/token/authorized_by` | `authorized_user:read` |

Per Webflow's docs, scopes are **registered when the token is created** and
cannot be granted afterwards. Connecting the site to GitHub does not affect
Data API scopes — that is Webflow's code-sync feature, a different system.

**Fix:** Site settings → **Apps & integrations** → **API access** → generate a
new Site token, and tick **CMS read + CMS write** on the creation screen before
generating. Then set `WEBFLOW_TOKEN`.

Also still needed: `WEBFLOW_COLLECTION_ID` must be a **Collection** id. The
current value `6a9329e5d333ba445a5f158e` cannot be validated until the token
can read — verify it with `GET /v2/sites/{site_id}/collections` once scoped.


## Update — 2026-09-03 (second pass)

### Webflow ✅ WORKING

The third token was a **Site** token (the first two were *Workspace* tokens —
`ws-` prefix — which is why CMS was never on the permissions list).

Verified live:
- `GET /v2/sites` → **200**, site `6a93284914fb1d22303a116c` "Grain Works"
- `WEBFLOW_COLLECTION_ID=6a9329e5d333ba445a5f158e` → **valid**, the
  "Grain Works" collection
- Created item `6a9995aa4005faf541c0c556`, confirmed by independent read,
  then deleted (204)

The adapter's guessed field names (`summary`, `link`, `image`) were **wrong**.
Real slugs: `project-summary`, `project-details`, `main-project-image`,
`client`, `client-logo`, `services-rendered`, `featured-project`, `color`.

It now reads the collection schema once, caches it, and **drops any field the
collection does not define** — so pointing it at a different collection can
never 400 the request.

### Systeme.io ✅ WORKING (reuses tags)

Now lists tags first and reuses an exact match, then `SYSTEMEIO_TAG`, then the
first tag on the account — only creating one as a last resort. Avoids the free
plan's "upgrade your plan to create more tags" cap entirely.
Verified: `reused tag 'asset:zero-click-content-machine'`.

### FetchApp ❌ their API is down

Every v3 endpoint returns **500 with a zero-byte body**, including with no
auth at all. `www.fetchapp.com` returns 200, so the marketing site is up and
the API is not. Nothing to fix on our side; the adapter treats 5xx as
retryable, so it will heal itself when they recover.

### Sell.app — REMOVED

Adapter, registry line and workflow secret deleted. Products created via API
returned 201 but never persisted.


## Canonical pack pages + live channel test — 2026-09-03

### /p/:slug shipped

Whop product pages declare `canonical` = the **store root**, not themselves —
verified on both products. That tells Google not to index the product page, so
syndicating with a Whop `canonical_url` throws the ranking signal away.

The Worker now serves a **thin canonical page per pack**:

- `/p/:slug` — self-canonicalising, `Product` + `FAQPage` JSON-LD, OG tags,
  CTA linking **straight to Whop checkout**
- `/p` index, `/sitemap.xml`, `/robots.txt`

It is deliberately **not in the buy path** — no friction is added for buyers.
Its only job is to be the honest `canonical_url` target for syndication.
All adapters now point there via `canonical_url()` (override with
`PACK_PAGE_BASE`).

### Live results — 6 channels posted

| Channel | Result |
|---|---|
| **dev.to** | ✅ live, canonical correctly points at `/p/zero-click-content-machine` |
| **bluesky** | ✅ live, post verified in the public feed |
| **discord** | ✅ posted to the webhook |
| **webflow** | ✅ CMS item created |
| **systeme.io** | ✅ reused existing tag |
| **filepost** | ✅ CDN mirror |
| itch | ❌ 403 Cloudflare challenge — bot-protected, needs the butler API |
| fetchapp | ⏳ still 500 (their outage) — retrying |
| payhip | ❌ needs a file upload — see below |

### Payhip

Auth header is **`payhip-api-key`** (a Bearer token 401s). Form-encoded plus
`product_type=digital` clears the 400, but the API then answers
`{"success": false, "message": null}` — creation appears to require an
uploaded file. Marked permanent so it does not burn retries.

### Buffer — authenticates, but 0 channels

Token is valid (`account.id 69fb59be6b533428adb722b7`) but
`account.channels` is **empty**, and the provided channel id
`69fb5a1a5c4c051afa1829dc` is not on the account. Connect X / LinkedIn /
Pinterest inside Buffer first, then re-read the ids.

### Hugging Face

Token valid (user `SharkSkin`). No adapter yet — HF Datasets/Spaces would be a
good free host for the pack files. Not wired.

## Round 3 — 2026-09-03

### Buffer ✅ WORKING — I was wrong before

My earlier "0 channels" claim was a **bad query**, not a bad account. `channels`
requires an `input` argument; without it the API returned an empty list.
Correct query:

```graphql
{ channels(input: {organizationId: "<org>"}) { id service isDisconnected } }
```

Result: **1 connected channel — `69fb5a1a5c4c051afa1829dc` (twitter)**, exactly
the id supplied. Only 1 of 3 though: LinkedIn and Pinterest are not connected.

`CreatePostInput` schema (introspected — public docs are wrong):
- **`channelId` is SINGULAR** and required. No `channelIds`. One post per
  channel, so the adapter loops.
- `mode`: `addToQueue|customScheduled|shareNext|shareNow`
- `schedulingType`: `automatic|notification`
- `needsApproval` and `assets` are required
- `assets` = `[AssetInput]` = `{image:{url}}` — **not** `{type, source}`

Verified: post `6a99b51418474247f7574ec4` scheduled with image attached.

### Hugging Face ✅ WORKING

Creates a dataset repo per pack and commits a README.
Live: <https://huggingface.co/datasets/SharkSkin/assetbot-zero-click-content-machine>

**Gotcha:** the `/upload/{rev}/{path}` endpoint is **retired — 410**. Must use
the NDJSON `/commit/{rev}` endpoint (header line + base64 file line).

### itch.io ❌ cannot publish via API

`GET /api/1/{key}/my-games` → **200** (key is valid), but `itch.io/game/new`
returns a **Cloudflare bot challenge**. itch's HTTP API is **read-only**;
publishing requires the `butler` CLI, which needs a binary download and a
pre-existing game page. Not viable inside the queue worker.

### Payhip ❌ read-only for products

Auth header is **`payhip-api-key`** (Bearer 401s) and reads work fine. Creation
returns `{"success": false, "message": null}` for **every** shape tried:
JSON, form-encoded, +`product_type=digital`, and multipart with a file.
Marked permanent.

### Tumblr ❌ credentials rejected

OAuth 1.0a HMAC-SHA1 signer implemented and wired. The blog
`affiliatemonk.tumblr.com` **exists** (public API confirms), but signed
requests fail: even `GET /v2/user/info` returns **401 code 1009 "Unable to
authorize"**. Since that call needs only a valid signature + token pair, the
supplied token/secret is expired or from a different app than the consumer key.
**Regenerate the OAuth tokens at api.tumblr.com/console.**

### Blogger — adapter built, needs SMTP

Mail2Post address `simalidudu.goatranger@blogger.com` is wired. Posting by
email needs an SMTP relay, so set `BLOGGER_SMTP_HOST/USER/PASS` (a Gmail app
password works). Without them the channel is skipped silently.

**Why these were missed earlier:** Blogger and Tumblr were supplied in the
grain-works config dump rather than as explicit keys, and I did not carry them
across. That was an oversight — both are now first-class channels.

## KV quota incident — 2026-09-03

**Cloudflare warned at 90% of the Workers KV free tier. Cause was our own
dashboard, and it is fixed.**

Actual usage: **900 writes / 1,000 daily limit** (reads were 2,972, nowhere
near their much larger cap). So it was a *write* problem.

Root cause: `/api/summary` appends a daily rollup point to the `history` key
and wrote it **unconditionally on every call**. The dashboard auto-refreshed
every 60s, so a single idle browser tab generated **~1,440 KV writes/day** —
rewriting identical data, since the rollup only changes when the pipeline runs.

Two fixes:

1. **Write only when the rollup actually changed** (compare against the stored
   point). Handful of writes/day instead of one per poll.
2. **Dashboard poll 60s → 5 min**, cutting the request rate 5x as well.

Verified live after deploy: 6 consecutive `/api/summary` calls produced
**0 KV writes** (previously 6).

Quota resets 00:00 UTC. Nothing was lost — writes beyond the cap would have
429'd, but the cron locks and dashboard reads keep working regardless.

## itch.io — no create API, butler only

Confirmed exhaustively (2026-09-03): `POST`/`PUT` against `game/new`, `games`
and `my-games` all return **405/404 "method not supported"**, and the HTML form
at `itch.io/game/new` sits behind a **Cloudflare bot challenge**. The key is
valid (`/me` → 200, user `simalidudu-boop`) but `/my-games` is **empty** — there
is no page to publish to.

The adapter now shells out to **butler** and pushes to an existing page:

```
ITCH_TARGET=simalidudu-boop/ai-prompt-packs:downloads
```

**One-time manual step:** create the page at <https://itch.io/game/new>
(classification "assets" / "tools"). After that, butler pushes every future
build automatically. Without `ITCH_TARGET` or the butler binary the channel is
skipped silently.

## Payhip — REMOVED

Adapter, registry entry and workflow secrets deleted. Product creation returned
`{"success": false, "message": null}` for every payload shape tried (JSON,
form-encoded, `+product_type`, multipart with file). The API is read-only for
products on this plan.

## Buffer — rechecked, still 1 of 3

Re-queried with the correct schema:

```
CONNECTED CHANNELS: 1
   69fb5a1a5c4c051afa1829dc  twitter  disconnected=False locked=False  [OK]
   twitter   -> CONNECTED
   linkedin  -> NOT CONNECTED
   pinterest -> NOT CONNECTED
```

X posting works today. LinkedIn and Pinterest must be connected inside the
Buffer dashboard (Channels → Connect); no new API key is needed — the adapter
loops over whatever ids are in `BUFFER_CHANNEL_IDS`.

## Retry round — 2026-09-03 (evening)

### Buffer — 3 channels connected, X + LinkedIn posting ✅

All three now show connected: twitter `69fb5a1a...`, linkedin `6a99b789...`,
pinterest `6a99b7c6...`.

First 3-channel attempt posted only **2**, and the adapter wrongly reported a
clean `ok=True`. Two real bugs found:

**1. Whop CDN images 403 to third parties.** Buffer replied *"Image could not
be read from its URL"*. `img-v2-prod.whop.com` returns **403** to outside
fetchers, so `gallery_images` is unusable for syndication. Added
`public_image()`, which prefers the **GitHub Release** copy (public, 200) and
never returns a Whop URL. `release_images` is now stored in the manifest and
written by `publish.py` going forward.
Re-test: **2/2 posted with images attached.**

**2. Pinterest requires a board.** *"Pinterest posts require a board to be
selected."* Buffer's API does **not** expose board ids (no `PinterestChannel`
type, `ServiceData` has no queryable subfields), so supply one:

```
BUFFER_PINTEREST_BOARD=<boardServiceId>
# or per-channel: BUFFER_PINTEREST_BOARDS=<channelId>:<boardId>,...
```

Get the id from the board URL in Pinterest. The adapter then sends
`metadata.pinterest.boardServiceId`.

**3. Partial success is no longer hidden** — posting to 2 of 3 channels now
reports which failed instead of a clean success.

### itch.io ✅ WORKING via butler

The page now exists (`ai-skills`, id 4970002), which was the missing piece.
butler v15.31.0 downloaded from `broth.itch.zone`, and the adapter shells out
to it.

**Verified independently** — not just the exit code:

```
butler status simalidudu-boop/ai-skills
| downloads | #19088428 | #1943163 | 1 |
```

API confirms upload `ai-skills-downloads.zip`, 190,723 bytes, build 1943163.

Config: `ITCH_TARGET=simalidudu-boop/ai-skills:downloads` and `BUTLER_PATH`
(or butler on PATH). CI must download the butler binary before the run.

## Round 4 — 2026-09-03 (Mastodon, Zenodo, IndexNow, RSS)

**20 channels registered. 13 verified live.**

| Channel | Result |
|---|---|
| **mastodon** | ✅ [live public post](https://mastodon.social/@ai_prompts_skills/117208701730161945) — token is instance-specific (mastodon.social only) |
| **zenodo** | ✅ draft deposition 22286545. Stays a DRAFT unless `ZENODO_PUBLISH=1` — a published DOI is **irreversible** |
| **indexnow** | ✅ accepted; key file served at `/16e37…txt` (protocol requires it) |
| **RSS** | ✅ `/rss.xml` + `/feed.xml`, valid XML, both packs |

### YouTube — BLOCKED, needs OAuth not IDs

A channel ID and user ID cannot upload. `videos.insert` returns
**401 "Expected OAuth 2 access token"**. Uploading requires a full OAuth2
flow with `https://www.googleapis.com/auth/youtube.upload`:

1. Google Cloud Console → new project → enable **YouTube Data API v3**
2. OAuth consent screen (External, add yourself as a test user)
3. Credentials → OAuth client ID → **Desktop app**
4. Run the consent flow once, keep the **refresh token**
5. Set `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`

Channel: `UChT6JgRbKyEY2r_Umyi2cxQ` ("What The Hell?"). We already generate
slideshow videos, so the adapter is worth building once those three exist.

### Email — where the addresses come from

**We do not scrape any addresses, and nothing here invents them.** The list
has exactly **1 contact** (`simalidudu@gmail.com`, self-registered 2026-08-26)
and it is **unsubscribed**, so the broadcast correctly reports
`no mailable contacts`.

The intended source is opt-in only: a buyer downloads the free pack, gives an
email, and Systeme.io stores it. That capture form does not exist yet, which
is why the list is empty.

Also: systeme.io's free API has **no transactional send endpoint** — it can
tag contacts and manage them, but campaigns are triggered in their UI. The
adapter reports the mailable count rather than pretending to send.

## YouTube without Google Cloud — the Apps Script bridge

**You do not need a Cloud Console project or a credit card.** Grain Works
avoids it, and we now do the same.

Apps Script ships a built-in **"YouTube Data API v3" Advanced Service** that
runs as the *script owner's* Google account. No Cloud project, no OAuth
consent screen, no OAuth client, no refresh token, no billing.

`appsscript/youtube-bridge.gs` wraps that in a tiny web app:

- `GET /exec?secret=…` → health check (channel name, video count)
- `POST /exec` `{secret, videoUrl, title, description, tags, privacy}` →
  downloads the MP4 and calls `YouTube.Videos.insert`

Setup (~5 min, once):

1. script.google.com → New project → paste the file
2. Services (+) → add **YouTube Data API v3** (identifier must be `YouTube`)
3. Project Settings → Script Properties → `SHARED_SECRET = <random string>`
4. Deploy → New deployment → **Web app**, execute as *Me*, access *Anyone*
5. Run `authorizeOnce` once and accept the Google consent screen
6. Set `YOUTUBE_BRIDGE_URL` (the /exec URL) and `YOUTUBE_BRIDGE_SECRET`

Security: Apps Script requires "Anyone" access for machine callers, so the
endpoint is public — every request must carry the shared secret, and requests
without it are rejected before anything uploads.

We already generate slideshow videos (`the-content-research-engine` has one
waiting), so this channel activates as soon as the bridge URL is set.

## Mastodon — the token limit is real, the reach limit is not

A Mastodon token is issued **by one instance** and only authenticates there
(verified: the token 401s on mstdn.social and fosstodon.org). That cannot be
worked around — it is how the protocol authenticates.

**But it does not cap reach.** The fediverse federates: the post is a public
ActivityPub `Note` addressed `to: Public`, resolvable by any server:

```
uri: https://mastodon.social/ap/users/…/statuses/117208701730161945
activitypub fetch -> 200, type: Note, to: [Public]
```

So users on *any* instance can follow, boost and see it. One account is a
distribution point, not a walled garden.

If you still want more accounts, the adapter now cross-posts:

```
MASTODON_EXTRA="https://fosstodon.org|token1,https://mstdn.social|token2"
```

Each needs its own token from that instance. Honestly: **one account plus
federation is usually the better play** — several thin accounts posting
identical text is the sockpuppet pattern that gets flagged.

### Robustness fix

`http()` raised `ValueError: unknown url type: ''` when an endpoint env var was
blank (hit while testing YouTube with no bridge URL). It now returns a clean
`invalid url` failure instead of an exception escaping the adapter.
