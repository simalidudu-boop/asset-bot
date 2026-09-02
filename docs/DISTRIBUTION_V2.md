# Distribution v2 — pointers taken from Grain Works Factory v3.3.0

Source: `grain-works.txt` (8,956 lines, Google Apps Script). A production
autonomous factory in the same shape as ours — different niche (Notion
templates for designers), same problem. Several of its distribution decisions
are better than my v1 plan and are adopted below.

---

## The five ideas worth stealing

### 1. Buffer as the legal proxy into hostile platforms — solves my RED tier

My v1 plan said X / LinkedIn / Pinterest were RED: don't automate, ban risk.
Grain Works routes them **through Buffer's GraphQL API** instead:

- `https://api.buffer.com`, mutation `CreatePost($input: CreatePostInput!)`
- Per-persona channel ids: `buffer_channel_x`, `buffer_channel_linkedin`,
  `buffer_channel_pinterest`, `buffer_channel_mastodon`

This is the key insight I missed. Buffer is a **sanctioned** client of those
platforms — it holds the partnership, handles OAuth, and its posts are
first-class API traffic, not bot traffic. You get X/LinkedIn/Pinterest
distribution *without* being the entity that breaks their ToS.

The mutation's error union is worth copying verbatim — it forces you to handle
`LimitReachedError`, `UnauthorizedError`, `NotFoundError`, `InvalidInputError`
as distinct outcomes rather than a generic failure.

**Revision to my advice: X / LinkedIn / Pinterest move from RED to AMBER,
reachable via Buffer.** Reddit stays RED — Buffer doesn't cover it, and the
Responsible Builder Policy plus ~$12k/yr commercial tier is unchanged.

### 2. Distribution as a durable QUEUE, not inline posting

Their design note is the sharpest thing in the file:

> Fan-out maths killed the naive design: 10 personas x 13 channels = 130 POSTs
> per asset, ~156s against a 330s tick. Fan-out is a durable QUEUE. Enqueue
> writes rows (cheap, no network); a bounded worker drains
> `DIST_MAX_PER_TICK` jobs with persisted backoff, so a crashed tick never
> double-posts and never loses work.

Our `run_daily.py` posts inline. One slow channel stalls the run; a crash
mid-fan-out either loses posts or double-posts on retry. **Adopt the queue.**

Concretely: `state/dist_queue.jsonl` with rows
`{asset, channel, status, attempts, next_attempt_at, remote_url, error}`,
drained by a bounded worker with exponential backoff.

### 3. Permanent-vs-retryable error classification

```js
function _distPermanent(code) {
  if (code === 401 || code === 403 || code === 400 ||
      code === 404 || code === 422) return true;
  return false;
}
```

Every adapter returns a uniform
`{ok, remoteId, remoteUrl, error, permanent}`. `permanent=true` means never
retry. This is exactly what our Whop work kept needing ad-hoc — a 403 on
`experience:create` should never be retried, a 500 should. Adopt the shape.

Their `chSystemeIo` note is a good refinement: **422 is only success when the
body says "duplicate"** — otherwise it is a permanent validation error. Don't
blanket-map status codes without reading the body.

### 4. A channel registry — one line to add a channel

```js
function distChannels() {
  return {
    itch:      { fn: chItch,      keys: ['itch_api_key','itch_username'] },
    archive:   { fn: chArchive,   keys: ['archive_access_key','archive_secret_key'] },
    sellapp:   { fn: chSellApp,   keys: ['sellapp_api_key'] },
    ...
  };
}
```

> Adding one = an adapter + a line here. Nothing else changes.

Plus `hasChannelKeys()` — a channel with missing credentials is **skipped
silently**, not failed. That is how you ship 13 channels and let the operator
enable them one key at a time. Our current code would need editing in several
places per channel.

### 5. DRAFT / LIVE as a first-class global mode

`DISTRIBUTION_POSTING_MODE` (DRAFT = queue only, never post), separately from
`ARTICLE_POSTING_MODE` and `BUFFER_POSTING_MODE`. Per-surface kill switches,
defaulting to DRAFT. We have one global `MOCK`/`DRY_RUN`; per-channel gating is
better — you can go live on dev.to while Buffer is still dry.

---

## New channels they use that I had not listed

| Channel | API | What it takes | Note |
|---|---|---|---|
| **itch.io** | flat form POST | zip/html builds, images | Real audience for digital downloads |
| **Sellix** | `dev.sellix.io/v1` | product + file | Free storefront, instant |
| **Sell.app** | `sell.app/api/v2` | product + file | Same category |
| **FetchApp** | `api.fetchapp.com/api/v3` | file delivery | Digital delivery |
| **Webflow CMS** | `api.webflow.com/v2` | collection item | SEO pages if you have a site |
| **Systeme.io** | `api.systeme.io/api` | funnel/lead magnet | **Free email list + funnel** |
| **Gumroad** | REST | product | Second storefront alongside Whop |
| **Bluesky** | AT Protocol, app password | text | Free, bot-tolerant, no approval |
| **Discord webhooks** | webhook POST | text/embed | Release announcements |
| **FilePost** | `upload.filepost.dev/v1` | any file | CDN so links don't depend on GH Pages |

**Systeme.io and Gumroad are the two I'd add first** — Systeme.io gives the
email list my v1 plan called "the only channel you own", free. Gumroad is a
second storefront with its own marketplace search.

`chArchive` confirms Internet Archive S3 works in production, which validates
that item in my v1 list.

---

## Two things I would NOT copy

**Personas.** They run ~10 synthetic personas, each with its own accounts and
its own niche asset, explicitly to dodge duplicate-content detection:

> Each persona owns its OWN niche-specific free asset, so a release is
> 1 persona x N channels, not 10 x N. This also removes the duplicate-text /
> duplicate-URL problem structurally.

Structurally clever, and the honest framing is that it is also a
sockpuppet network. On platforms that police coordinated inauthentic
behaviour, discovery means losing every account at once. Their own hard rule —
*"personas NEVER post a paid URL"* — reads like a mitigation for exactly that
risk. We have one brand and no reason to take it.

**13 channels before a single sale.** They are optimising fan-out with 0
validated demand, same as us. Breadth multiplies a conversion rate; it cannot
create one. Two live channels and one paying stranger beats thirteen and none.

---

## Revised build order

| # | Item | Why |
|---|---|---|
| 1 | Worker pack pages + JSON-LD + sitemap + RSS | canonical target everything links to |
| 2 | **Durable queue + permanent/retryable + channel registry** | infrastructure all channels need; retrofitting later is painful |
| 3 | dev.to + Hashnode adapters | free, no approval, verified live |
| 4 | Telegram + Bluesky | free, bot-tolerant, all media |
| 5 | **Systeme.io** | owned email list |
| 6 | **Buffer** → X / LinkedIn / Pinterest | hostile platforms, legally |
| 7 | Gumroad + Sellix | second storefronts |
| 8 | Internet Archive + YouTube | permanent artifacts, video |
| 9 | Draft-for-human Issue (Reddit) | still the only safe Reddit path |

Item 2 is the one to build first even though it ships no visible channel,
because every adapter after it is then ~30 lines and one registry line.
