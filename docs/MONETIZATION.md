# Monetization: how to actually extract money from the distribution mesh

Written 2026-09-04. Researched, with fee maths. Companion to
`DISTRIBUTION_SETUP.md`.

## Where we actually stand

| Metric | Value |
|---|---|
| Live products | 2 (one **free**, one **$11**) |
| Marketplace status | both still `pending_review` |
| Revenue to date | **$0** |
| Channels verified live | 17 |

**We have built a 17-channel distribution mesh that currently sells one $11
product.** That is the imbalance to fix. Distribution without a priced,
purchasable catalogue is a megaphone pointed at an empty shop.

---

## The single most important structural fact

**Only 3 of our 17 channels can take money.** Everything else is a *pointer*.

| Role | Channels |
|---|---|
| **Can transact** | Whop, Gumroad, Ko-fi |
| **Pointers** (drive traffic, cannot sell) | dev.to, Bluesky, Mastodon, Nostr, Tumblr, Blogger, Discord, Telegram, Buffer→X/LinkedIn, YouTube, Webflow, Zenodo, Archive.org, Hugging Face, itch.io, IndexNow, RSS |

So the money equation is:

```
revenue = (pointer traffic) x (click-through) x (conversion) x (price) x (units)
```

We have spent all our effort on the first term. The other four are untouched.

---

## Tier 1 — Fix the offer before adding more reach

### 1. Price ladder. We have no ladder, we have a coin-flip.

$0 and $11 with nothing between and nothing above. Every buyer is either
worth nothing or $11. Research is consistent that **bundles outsell single
items roughly 10:1** and that complete *systems* (prompts + instructions +
examples) command materially higher prices.

Recommended ladder, all producible by the existing factory:

| Tier | Price | What it is |
|---|---|---|
| Free | $0 | one pack — lead magnet, email capture, review bait |
| Core | $9–19 | single themed pack (where we are) |
| **Bundle** | **$39–79** | **all packs to date, auto-assembled — this is the missing money** |
| Subscription | $9/mo | every new pack as it ships |

The bundle costs us *nothing* to produce: it is a zip of assets we already
made. It is pure margin and it is the highest-leverage single change here.

### 2. Whop marketplace listing — finish it

Both products sit at `pending_review`. `live_marketplace` is the only channel
we have that puts us in front of **strangers with payment intent** rather than
readers. Nothing else on this list matches that.

### 3. Affiliates are already armed — now recruit

40% commission is live on both products. Nobody knows. Add a
`/p/affiliate` page on the Worker and a line in every syndicated post. Pure
upside: we pay only on sales that would not have happened.

---

## Tier 2 — Exploit each channel for what it is actually good at

Not every channel deserves the same post. Concretely:

| Channel | Best monetization use |
|---|---|
| **Whop** | Primary checkout. 2.7–3% fee, marketplace traffic, affiliate engine. Keep as the buy destination. |
| **Gumroad** | Second storefront. 10% + 50c, but **Discover is a real marketplace** and ~41% of Gumroad sales come from organic search. Worth the fee for discovery we cannot otherwise buy. |
| **Ko-fi** | 0% on tips, 5% on shop (0% on Gold at $6/mo). Best used for **tips + "buy me a coffee" on free packs** — monetizes people who will never buy. |
| **YouTube** | Now uploads **public**. Not ad revenue (needs 1k subs) — its job is **search**: "AI prompts for X" is a high-intent query and video ranks in Google. Put the pack link in the first line of the description. |
| **dev.to / Blogger / Tumblr / Webflow** | SEO surface. Value is the canonical link to `/p/:slug`, not the post itself. Never syndicate without `canonical_url`. |
| **Bluesky / Mastodon / Nostr** | Zero-cost reach, no ban risk, bot-tolerant. Low conversion, but the marginal cost is ~0 so the ROI is technically infinite. Use for launch pings. |
| **Buffer → X / LinkedIn** | LinkedIn is the highest-value audience we reach: professionals who expense $50 tools. Post the *outcome* ("cut research 80%"), not the artefact. |
| **Telegram** | Owned channel, all 4 media types, no algorithm. Best as a **free-pack delivery channel** that captures a subscriber. |
| **Hugging Face** | Developers searching for prompt datasets. High intent, technical audience. |
| **Zenodo / Archive.org** | Not for sales — for **authority**. High-domain-authority backlinks that lift the `/p` pages that do sell. |
| **itch.io** | Real digital-download buyer audience with a built-in payment system. Underrated for prompt packs. |
| **Systeme.io email** | Highest ROI channel in every study. Currently **1 contact, unsubscribed**. Needs a capture form before it means anything. |
| **IndexNow / RSS** | Plumbing. Makes everything else index faster. |

---

## Tier 3 — Platforms worth adding (researched, not guessed)

| Platform | Why | Status |
|---|---|---|
| **PromptBase** | **The** dedicated AI-prompt marketplace: 260k+ prompts, 425k+ users, buyers arrive *specifically wanting prompts*. 20% commission. | 403 to bots — manual listing, no API |
| **Gumroad Discover** | Marketplace with genuine organic search traffic. Already have the adapter, need the key. | adapter built, needs `GUMROAD_ACCESS_TOKEN` |
| **Kit (ConvertKit)** | Free to 10k subscribers, **sells products directly to the list**, 3.5% + 30c. Would replace Systeme.io's dead-end (no send endpoint on free tier). | API live (401 without key) |
| **Amazon KDP** | Biggest ebook marketplace on earth. Our packs are already PDFs — a "100 AI Prompts for X" ebook is a genuine KDP product. 35–70% royalty. | no public API, manual upload |
| **Lemon Squeezy** | Merchant of Record — handles global VAT. Matters if EU buyers appear. | API live (401 without key) |
| **Product Hunt** | One-shot launch spike, high-quality audience. | API exists, needs OAuth |
| **Creative Market** | Millions of design buyers, but **50% commission** and approval required. | marginal |

### Explicitly NOT worth adding

- **Etsy** — **banned AI prompt bundles in July 2024.** Most guides still get
  this wrong. Do not build it.
- **Udemy** — instructor share cut to ~15% for 2026.
- **Reddit** — API closed, ~$12k/yr commercial tier, spam terms.

---

## The honest bottom line

The mesh is not the bottleneck any more. **The catalogue is.**

Ranked by expected revenue per hour of work:

1. **Ship the bundle** ($39–79). Zero production cost, pure margin, fixes the
   missing middle of the ladder.
2. **Finish the Whop marketplace listing.** Only source of strangers with
   payment intent.
3. **Email capture on the free pack.** The one channel nobody can ban, and it
   is currently empty.
4. **Gumroad key** → second storefront with real Discover traffic.
5. **PromptBase listing** (manual) → buyers who arrive wanting exactly this.
6. **Advertise the 40% affiliate rate** everywhere.

Everything above costs nothing but attention. None of it requires another
channel adapter.
