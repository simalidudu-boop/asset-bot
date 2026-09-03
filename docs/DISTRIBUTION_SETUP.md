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
| `sellapp` | `SELLAPP_API_KEY` | Free storefront. |
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
| webflow | regenerate the token with **`cms:read` + `cms:write`** scopes |
| sellapp | finish store setup/verification in the dashboard |
| fetchapp | their API is 500-ing; retry later (adapter already treats 5xx as retryable) |
| sellix | test from a normal network — sandbox DNS cannot resolve it |
