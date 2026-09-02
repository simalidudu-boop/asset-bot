# Autonomous distribution strategy

Written 2026-09-02. This is a plan, not shipped code. Nothing here is built yet.

## The brutal diagnosis first

| Metric | Value |
|---|---|
| Posts published | 11 |
| Company members | 3 |
| Product members | 0 |
| Reviews | 0 |
| Revenue | $0 |

The factory works. Distribution does not exist. All 11 posts went to **our own
two Whop forums** — an audience of 3 people, at least one of whom is you.

**We are broadcasting to an empty room.** Posting *more* into that room changes
nothing: 100 posts to 3 people is still 3 people. Every hour of tuning the
generator is worth less than one hour spent on a channel with strangers in it.

The single most important sentence in this document: **an autonomous content
loop with no audience is a rounding error on zero.**

## What "autonomous" can and cannot mean

Be honest about this, because it decides the whole strategy.

**Genuinely automatable:** publishing to APIs we hold keys for, scheduling,
cross-posting, SEO surface area, marketplace listing hygiene, affiliate
recruitment mechanics, email capture and sequences.

**Not safely automatable:** Reddit, X, LinkedIn, Discord communities, Facebook
groups. Not because it is technically hard — it is easy — but because
unsolicited automated promotion is precisely what every one of those platforms
bans, and the outcome is a permanent ban of the account plus the domain. An
automated spam loop is *negative* distribution: it burns the brand's name in
the exact communities that were the target market.

So the strategy is: **automate the compounding, permanent surfaces; use humans
(you) for the high-trust, high-variance ones.** The bot builds the machine; you
supply the credibility it cannot fake.

## Tier 1 — Whop-native (do this first; highest ROI, lowest effort)

We are already inside a marketplace with ~2.5M weekly visitors and we are
barely using it.

**1. Finish the marketplace listing.** Both products sit at `pending_review`.
This is the single highest-value action available and it is already 90% done.
`live_marketplace` puts us in front of Whop Discover traffic — strangers, not
our 3 members. Everything else in this document is smaller than this.

**2. Whop affiliates — the highest-leverage automatable lever. DONE.**
Setting a 40% commission turns other people's audiences into our distribution,
and it is pure upside: we pay only on a sale that would not otherwise have
happened. This is the closest thing to genuinely autonomous distribution that
exists here.

**Verified live 2026-09-02** — both products now read back
`global_affiliate_percentage: 40.0`, `global_affiliate_status: enabled`.

API note: these fields are **absent from the beta OpenAPI spec** but work on
`PATCH /api/v1/products/{id}` and exist on `UpdateAccessPassInput` in GraphQL
(`globalAffiliatePercentage`, `globalAffiliateStatus`, plus `member*` variants).
Do not trust the spec's field list as exhaustive — test the live endpoint.

Next affiliate step (not yet done): recruiting affiliates is itself a
distribution problem. The automatable part is making the offer discoverable —
a public "become an affiliate" page on the Worker, and the 40% rate visible on
the marketplace listing.

**3. Reviews unlock ranking.** 0 reviews is a conversion killer and plausibly a
Discover ranking input. The free product exists to generate them. Automate the
*ask* (post-purchase message), never the review itself.

**4. Price the free product's job correctly.** The free asset is not a product,
it is a lead magnet. Its only jobs are: capture an email, earn a review, and
upsell to the paid pack. Instrument it that way.

## Tier 2 — Owned, compounding surfaces (fully automatable)

These accrue value permanently and no platform can ban us from them.

**5. Publish every asset as a public web page.** We already generate the pack
content and host a Cloudflare Worker. Rendering each pack as an indexable HTML
page — with the FAQ, a content excerpt, and a buy link — turns each asset into
a permanent SEO surface. 200 assets/year = 200 pages of long-tail search
capture, working while we sleep. This is the best fit for an autonomous factory:
the marginal cost of one more page is zero and it never expires.

**6. Sitemap + structured data.** `Product` and `FAQPage` JSON-LD on each page,
auto-generated sitemap.xml, submitted to Google/Bing via their APIs. Fully
automatable, permanent, compounding.

**7. Email list.** The only distribution channel we would actually *own*.
Capture on the free download, then an automated sequence. Every other channel
is rented; this one is not.

## Tier 3 — Syndication (automatable, moderate value)

**8. Cross-post to platforms that welcome bots.** Not all are hostile:
dev.to, Hashnode and Medium have official publishing APIs and permit
syndicated content with a canonical link back. Each post is a backlink and a
new audience, with no ban risk when done with proper canonicals.

**9. RSS + newsletter aggregators.** Publish a feed; let aggregators pull.

## Tier 4 — Human-in-the-loop (do NOT automate)

**10. Reddit / X / LinkedIn / Discord.** The factory drafts; **you** post.
Concretely: the daily run opens a GitHub Issue containing 3 platform-tailored
drafts, and you copy-paste the ones you like. This keeps the volume benefit of
automation while keeping a human accountable for tone and context — which is
exactly what those platforms enforce. Automating this is how the brand gets
banned in week one.

## Sequenced plan

| Phase | Action | Automatable | Impact |
|---|---|---|---|
| **1. Now** | Get both products to `live_marketplace` | mostly | **Highest** |
| **1. Now** | Enable 40% affiliate commission | fully | **Highest** |
| **2. Week 1** | Public pack pages on the Worker + JSON-LD + sitemap | fully | High, compounding |
| **2. Week 1** | Post-purchase review + email capture | fully | High |
| **3. Week 2** | dev.to/Hashnode syndication with canonicals | fully | Medium |
| **4. Ongoing** | Drafts-for-human-review Issue | fully (drafting) | Medium, no ban risk |

## What I would explicitly NOT build

- **Auto-posting to Reddit/X/LinkedIn.** Ban risk, brand damage, and it is the
  thing every failed "AI content bot" does. The ROI is negative.
- **More content volume into our own 3-member forums.** Zero marginal return.
- **Buying traffic.** No product-market fit signal yet — 0 sales, 0 reviews.
  Paid traffic against an unvalidated offer just spends money faster.

## The honest caveat

Distribution is where this project's real risk sits, and no amount of clever
automation substitutes for the fact that **we have not yet proven a single
stranger will pay for these packs.** The first paid sale is worth more
information than the next 100 generated assets. Tier 1 exists to buy that
signal as cheaply as possible.
