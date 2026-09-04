# Monetization under sanctions

Rewritten 2026-09-04 after learning the operator is in **Iran**. The previous
version was wrong throughout: it optimised fee percentages on platforms that
will never pay out to an Iranian account.

---

## The constraint that governs everything

**Iran is under comprehensive OFAC sanctions.** Consequences that actually
bind us:

- Gumroad, Ko-fi, Payhip, Lemon Squeezy, Stripe, PayPal — **cannot pay out.**
  Fee comparisons between them are meaningless.
- Crypto is **not** the workaround people assume. OFAC made Iran's digital
  asset sector **sanctionable as a whole sector** (Aug 2026), designated the
  four largest Iranian exchanges (Nobitex, Wallex, Bitpin, Ramzinex, Jun 2026),
  and **Tether has frozen ~$475M** in Iran-linked USDT. Any USDT touching an
  Iranian exchange or IP is freezable. **Do not build on USDT/Tron.**
- Whop is currently the **only** channel that has any chance of transacting,
  and its payout path to Iran is **unverified**.

### Therefore the real strategy

**Stop optimising the sale. Optimise the two things sanctions cannot block:**

1. **Audience + reputation** — free assets, everywhere, permanently indexed.
2. **A payment rail that is genuinely permissionless** — Bitcoin **Lightning
   zaps** via Nostr, which we already have the identity for.

Everything else is theatre until a rail exists.

---

## Tier 1 — Fix the offer (rewritten for sanctions)

### 1. Verify the Whop payout path FIRST. This is the load-bearing unknown.

Before another line of code: **can Whop actually pay you?** If yes, it is the
only conventional rail and everything routes through it. If no, the paid
catalogue is fiction and 100% of effort should go to Lightning + audience.

Nothing else in this document matters more, and it costs one support ticket.

### 2. Lightning zaps — the only permissionless rail we can build

Nostr is already live (17-channel mesh, verified posting). Zaps are
**native Bitcoin micropayments** on Nostr, no KYC, no platform, no account to
suspend, nothing to geoblock. We already hold the identity.

Missing piece: a **Lightning address in the Nostr profile** (NIP-57). Without
it, zapping is impossible; with it, every Nostr post becomes payable.

Value-for-value fits our catalogue exactly: give the pack away free, let it be
zapped. It converts our biggest asset (volume of free output) into the only
income stream that cannot be frozen.

**Action:** get a Lightning wallet that works from Iran (self-custodial —
Phoenix, Breez, or a self-hosted node; avoid custodial services that geoblock),
publish the address as a NIP-05/lud16 profile field, then include it in every
`/p/` page and post.

### 3. Price ladder — but denominated in sats, not dollars

The $0/$11 coin-flip is still wrong. Revised for a zap-first world:

| Tier | What | Rail |
|---|---|---|
| Free | every pack | none — this is the funnel |
| **Zap** | "found this useful? zap it" | **Lightning (works)** |
| Paid | bundle $39–79 | Whop **only if payout verified** |

### 4. Affiliates: keep, but expectations down

40% is live on both Whop products. Affiliates are paid **by Whop**, so this
works regardless of our own payout — someone else's audience, someone else's
bank. Genuinely useful under sanctions.

---

## Tier 2 — Exploit each channel for what it is good at (rewritten)

The mesh's job is no longer "drive traffic to checkout". It is **build
reputation and collect zaps**. Re-scored on that basis:

| Channel | Real job now | Priority |
|---|---|---|
| **Nostr** | **The money channel.** Zaps are the only unblockable rail. Post every pack, include the Lightning address. | **1** |
| **Whop** | Only conventional checkout. Verify payout, then push marketplace listing. | **1** |
| **YouTube** | Search surface for "AI prompts for X". Public uploads now on. Lightning address in description. Ad revenue needs 1k subs — irrelevant for now. | 2 |
| **Worker `/p` pages** | Canonical, self-owned, sanction-proof. Add the zap CTA here. | 2 |
| **dev.to / Blogger / Tumblr / Webflow** | SEO + authority. Always `canonical_url`. Free-pack link, not a checkout link. | 2 |
| **Hugging Face** | Developer audience actively searching prompt datasets. High intent, technical, no payment friction because the asset is free. | 2 |
| **Telegram** | Owned channel, no algorithm, all media types. Best free-pack delivery + direct audience. | 2 |
| **Bluesky / Mastodon** | Zero-cost reach, bot-tolerant. Launch pings. | 3 |
| **Buffer → X / LinkedIn** | Professional reach we cannot get otherwise. Post outcomes, not artefacts. | 3 |
| **Archive.org / Zenodo** | Authority backlinks + permanence. Cannot be deplatformed. Under sanctions, permanence is worth more than usual. | 3 |
| **itch.io** | Real download audience; free packs build a follower base. | 3 |
| **IndexNow / RSS / sitemap** | Plumbing. Makes the rest index fast. | 3 |
| ~~Gumroad / Ko-fi~~ | **Cannot pay out. Use for $0 distribution only** — as the operator already concluded. | 4 |

---

## Free, autonomous listing surfaces worth adding

Researched this round. All free, all accept submissions, none require a
payout account:

| Surface | Why | Automatable? |
|---|---|---|
| **AlternativeTo** (DR 89) | free, huge mainstream traffic, top AI-citation target | manual submit |
| **SaaSHub** (DR 72) | free, 226k products, dofollow | manual submit |
| **StackShare** (DR 82) | free, 1.5M developers | manual submit |
| **SourceForge** (DR 93) | **free listing + it is a download channel** — can host the packs | manual |
| **Crunchbase / F6S** (DR 91/81) | free company profile, credibility + AI-citation | manual |
| **Future Tools** | genuinely free, human-curated (strict: >75% rejected) | manual |
| **Openfuture.ai** | **highest-traffic FREE AI directory** (~198k/mo) | manual |
| **AI Tools Directory / Tool Pilot / Dokey / AIxploria** | free tiers, long-tail | manual |
| **DEV Community** (DR 89) | already automated ✅ | **yes — live** |
| **IndexNow** | already automated ✅ | **yes — live** |

**Honest note:** essentially every directory is *manual submission*. There is
no API. The 2026 pattern is also that many advertise "dofollow" and deliver
nofollow, or demand a reciprocal badge. Treat them as a one-afternoon manual
push, not an automation target. **Openfuture.ai, AlternativeTo, SourceForge
and Future Tools are the four worth the time.**

---

## What NOT to do (sanctions-specific)

- **Do not route income through USDT/Tron.** It is the single most-frozen
  asset in the Iran enforcement campaign (~$475M frozen).
- **Do not use Iranian exchanges** — all four majors are OFAC-designated with
  secondary sanctions.
- **Do not misrepresent location** to a payment platform. Account seizure plus
  legal exposure, and it puts every channel we built at risk.
- **Do not spend more effort on Gumroad/Ko-fi/Payhip integrations.** They
  cannot pay you. Distribution only.

---

## Revised priority

1. **Ask Whop support whether they can pay out to Iran.** One ticket. Unblocks
   or kills the entire paid strategy.
2. **Set up a Lightning address and publish it** (Nostr profile, `/p` pages,
   YouTube descriptions, Telegram). The only rail nobody can switch off.
3. **Ship the free bundle** — with zap CTA. Costs nothing, builds the audience
   that makes zaps meaningful.
4. **One afternoon of manual directory submissions** (Openfuture, AlternativeTo,
   SourceForge, Future Tools).
5. Keep the mesh running. It is doing its job: reputation, reach, permanence.

## Lightning address — Spark address is NOT zappable (2026-09-04)

Supplied: `spark1pgssyrvysh9twaq74jwrz3wp26g8cnn7et7llq6twfwrnsnrqmrwkfkn647xay`

That is a **Spark address** — a Bech32m identifier for a wallet on the Spark
Bitcoin L2. Per Spark's own docs it "maps to a wallet's identity public key…
think of them as user IDs". It is **not** a payment endpoint.

NIP-57 zaps require one of:

| Field | Format | Example |
|---|---|---|
| `lud16` | lightning address | `name@domain.com` |
| `lud06` | LNURL | `lnurl1...` |

A `spark1...` string is neither, so no Nostr client can zap it. Publishing it
would look like a payment option and silently collect nothing.

**Guarded in code:** both the Nostr adapter and the Worker `/p` pages only
render the zap CTA when `LIGHTNING_ADDRESS` contains `@`. A Spark address is
skipped with a log line rather than shipped as a dead CTA.

### What is needed instead

Spark wallets **can** create Lightning invoices (`createLightningInvoice()`),
so the wallet supports Lightning — it just has not exposed a reusable
*address*. Options:

1. **A Spark app that issues a username** → many give `you@theirdomain.com`.
   Check the wallet UI for "Lightning address" / "username", not "Spark
   address".
2. **A dedicated LUD-16 provider.** Self-custodial and generally reachable:
   **Phoenix** (Bolt12/LN address), **Breez**, **Alby Hub**, **Coinos**,
   **Blink**. Avoid custodial US services (Strike, Cash App) — they geoblock.
3. **Self-host** an LNURL-pay endpoint on the Worker pointing at a node. Most
   sovereign, most work.

Anything ending in `@something` works the moment it is set — the code is
already deployed and waiting.
