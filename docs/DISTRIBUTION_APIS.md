# Every free distribution API, graded — text, image, video, PDF

Researched 2026-09-02. Companion to `DISTRIBUTION.md`. This is the "distribute
to the entire internet autonomously" answer, with the honest edges marked.

**Live-probed from the sandbox (2026-09-02):**

| Endpoint | Result |
|---|---|
| `POST dev.to/api/articles` | **401 unauthorized** — endpoint live, auth is the only gate |
| `api.telegram.org/bot<token>/getMe` | **401** with a well-formed JSON error — live |
| `s3.us.archive.org` | **200** — live |
| `gql.hashnode.com` | **301 redirect to the web app** — could not confirm |

A 401 is the *good* result here: it proves the route exists and only a key
stands between us and publishing.

Grading:

- **GREEN** — free API, automation is *explicitly permitted*, build it.
- **AMBER** — free API exists but automation is rate-gated, approval-gated, or
  tolerated-not-encouraged. Build with a human gate or low volume.
- **RED** — do not automate. Either the ToS forbids it, or the account/brand
  gets destroyed. Draft-for-human only.

---

## GREEN — build these, in this order

### 1. dev.to (Forem) — text + markdown + images
- `POST https://dev.to/api/articles`, header `api-key: <key>`
- Key: dev.to → Settings → Extensions. **Free, no approval, no credit card.**
- Body: `{article:{title, body_markdown, published, tags[≤4], canonical_url,
  main_image, description, series, organization_id}}`
- Update: `PUT /api/articles/{id}`
- **Set `canonical_url` every single time.** Without it dev.to's high-authority
  domain outranks our own page for our own content.
- Rate limit: HTTP 429 on bursts; space posts out.
- Tags must be lowercase alphanumeric, max 4.
- Why first: largest dev-specific feed, zero approval, immediate strangers.

### 2. Hashnode — text + markdown  *(endpoint unverified — see note)*
- `POST https://gql.hashnode.com` (GraphQL), header `Authorization: <PAT>`
- **Verification note:** from this sandbox that host 301-redirects to the
  Hashnode web app rather than answering GraphQL. Either it is geo/UA-gated or
  the endpoint has moved. Confirm the current endpoint before building; do not
  trust the URL above blindly.
- PAT: hashnode.com/settings/developer. **Free.**
- Mutation `publishPost(input: PublishPostInput!)` with `publicationId`,
  `title`, `contentMarkdown`, `tags:[{name,slug}]`, `originalArticleURL`
  (their canonical field), `slug`.
- Publication id is public: query `{publication(host:"x.hashnode.dev"){id}}`
- Note: some features moved behind $5/mo Pro in 2026; publishing is still free.

### 3. Our own Worker pages — text + images + PDF + video embeds
- Zero cost, zero permission, fully ours, already 90% built.
- The canonical source every syndicated copy points back to.
- Add: `Product` + `FAQPage` JSON-LD, `sitemap.xml`, `robots.txt`, RSS feed.
- **This is the highest-value item on the entire list** because everything
  else borrows authority and this one accrues it.

### 4. Telegram Bot API — text + image + video + PDF, all free
- `https://api.telegram.org/bot<TOKEN>/sendMessage|sendPhoto|sendVideo|sendDocument`
- Token from @BotFather, **free, instant, no approval, no quota worth caring
  about** (~30 msg/s). Documents up to 50MB via bot API.
- The only channel here that natively takes **all four media types** with one
  trivial auth. Create a channel, push every asset, embed the join link.
- Genuinely autonomous with no ban risk *for your own channel*.

### 5. Internet Archive — PDF + video + images, permanent, free
- S3-like API: `PUT https://s3.us.archive.org/<identifier>/<file>` with
  `authorization: LOW <access>:<secret>` (archive.org/account/s3.php).
- **Free, unlimited, permanent, high domain authority backlink.**
- Every pack PDF uploaded here is an indexable, permanent artifact.

### 6. YouTube Data API v3 — video
- `videos.insert`, OAuth 2.0 required (not just an API key).
- **Free.** Quota reform matters: Google cut `videos.insert` from ~1600 units
  to ~100 (Dec 2025), then moved uploads to **their own bucket, ~1 unit/call,
  100 uploads/day** (Jun 2026). Uploads no longer eat the 10k pool.
- We already generate slideshow videos — this is a real, free, high-traffic
  surface sitting unused.
- Watch: `search.list` still costs 100 units. Never poll with search.

### 7. RSS / JSON Feed — the free multiplier
- Not an API to call; an API to *offer*. dev.to can auto-import via RSS,
  aggregators and readers pull it, and it costs one static file.

---

## AMBER — automate carefully, with a gate

### 8. Pinterest API v5 — image + video, big traffic for product content
- Official `POST /v5/pins` with `board_id`, media, `link`. **Free**, but needs
  a Business account, app registration and approval; trial access is heavily
  rate-limited until upgraded.
- High relevance: Pins are *designed* to drive outbound traffic, which is
  exactly our use case. Worth the approval friction.
- Avoid unofficial clients (`py3-pinterest` etc.) — cookie-mimicking browser
  automation, straight ToS violation, account loss.

### 9. Medium — text
- **The API is dead.** No new integration tokens since 2023. Anything claiming
  otherwise is stale.
- Working path: publish to our page → Medium **Import a story** → it fetches
  the URL and *sets the canonical back to us automatically*. Manual, ~30s.

### 10. Mastodon / Fediverse — text + image + video
- `POST /api/v1/statuses`, bearer token from the instance. **Free, trivially
  automatable, bots are explicitly welcome** if tagged as a bot account.
- Reach is modest but the cost is near zero and there is no ban risk.

### 11. LinkedIn / X (Twitter) — text + image
- Both have official APIs; both are now effectively **paid or heavily gated**
  for posting volume (X's free tier is minimal). Automation of promotional
  content is also what their spam systems target.
- Treat as draft-for-human.

---

## RED — do not automate

### 12. Reddit — highest potential reach, highest danger
This is the one people always want, so here is the 2026 reality:

- **Self-service API access is CLOSED.** Under the *Responsible Builder
  Policy* (late 2025), every new OAuth token requires prior approval.
- **Commercial use requires a separate agreement**, reportedly from
  ~$12,000/year. Developer Terms explicitly prohibit monetized products on
  the API without it.
- Policy text: apps "must not engage in spamming activity through automated
  posts, comments, or direct messages. This includes posting identical or
  substantially similar content across subreddits." That sentence describes
  precisely what an autonomous syndication bot does.
- Community norm is **9:1** — nine genuine contributions per promotional post.
- Consequence: shadowban (invisible to everyone but you, so you keep posting
  into a void for weeks), then sitewide suspension.

**Verdict: draft-for-human only.** Reddit can absolutely work for this
product — but as *you* posting, with the bot writing drafts.

### 13. Facebook Groups, Discord servers, Slack communities, Quora
Same logic. Unsolicited automated promotion into someone else's community is
the definition of spam on every one of these. The bot drafts; a human posts.

### 14. Browser-automation "APIs" for any platform
Selenium/Playwright against Pinterest, Reddit, LinkedIn, Instagram. Works
until it doesn't, violates ToS everywhere, and burns the account permanently.

---

## The uncomfortable truth about "the entire internet"

You can genuinely, safely automate publishing to: **your own site, dev.to,
Hashnode, Telegram, Internet Archive, YouTube, Mastodon, and RSS.** That is a
real, compounding, permanent distribution footprint and it is nothing to
dismiss.

You cannot safely automate: **Reddit, X, LinkedIn, Facebook, Discord,
Instagram, TikTok, Quora.** Not because of engineering difficulty — each is a
weekend of work — but because every one of them is built to detect and punish
exactly this pattern, and the punishment is permanent removal from the
audience you were trying to reach.

The failure mode is not "the bot doesn't work." It is "the bot works for six
weeks, gets the brand shadowbanned across every channel that mattered, and we
find out months later when we notice nobody has ever replied."

So the strategy is **automate breadth on permissive surfaces, and use the
saved human time on the two or three hostile-but-valuable ones.**

## Build order (concrete)

| # | Surface | Media | Effort | Gate |
|---|---|---|---|---|
| 1 | Worker pack pages + JSON-LD + sitemap + RSS | all | M | none |
| 2 | dev.to | text/img | S | API key |
| 3 | Telegram channel | all | S | BotFather |
| 4 | Hashnode | text | S | PAT |
| 5 | Internet Archive (PDFs) | pdf/img | S | S3 keys |
| 6 | YouTube (slideshow videos) | video | M | OAuth |
| 7 | Mastodon | text/img | S | token |
| 8 | Pinterest | img/video | L | approval |
| 9 | Draft-for-human Issue (Reddit/X/LI) | text | S | human |

Secrets needed: `DEVTO_API_KEY`, `HASHNODE_PAT`, `HASHNODE_PUBLICATION_ID`,
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL_ID`, `IA_ACCESS_KEY`, `IA_SECRET_KEY`,
`YOUTUBE_CLIENT_ID/SECRET/REFRESH_TOKEN`, `MASTODON_INSTANCE`, `MASTODON_TOKEN`.
