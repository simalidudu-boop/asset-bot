# asset-bot

Three factories, three architectures — see **[`docs/FACTORIES.md`](docs/FACTORIES.md)**:

| | Name | Delivery | Money | Status |
|---|---|---|---|---|
| **F1** | **The Storefront** | gated — checkout then download | Whop | running |
| F2 | The Broker | n/a (affiliate content) | commissions | **shut down** |
| **F3** | **The Commons** | ungated — `git clone` / raw URL | zaps + sponsors | running, LIVE |
| **F4** | **The Utility** | free browser tools at `/tools` | zaps | running, LIVE |

An autonomous digital-product factory. Every day it invents a topic, generates
an AI prompt pack, renders images and video, packages it, publishes it as a
product on Whop, and syndicates it across ~22 channels — with no human in the
loop.

> **New agent or LLM picking this up?** Open **[`docs/ARCHITECTURE.html`](docs/ARCHITECTURE.html)**
> first. It is a single self-contained page with the full architecture, every
> credential, every known trap, and the current state of play.

---

## Pipeline

```
topics → generate_pack (LLM cascade) → QC gate → media (images + video)
      → packaging (MD/PDF/DOCX) → hosting (GitHub Releases)
      → publish (Whop product, cover, FAQ, marketplace submit)
      → distribution queue → 22 channel adapters
      → Cloudflare Worker /p/:slug canonical page (+ Lightning zap CTA)
```

**Command Center:** <https://asset-bot-edge.simalidudu.workers.dev>
**Store:** <https://whop.com/the-algorithmic-daemon-concern>

## Schedules

GitHub's `schedule:` silently drops runs, so **Cloudflare Worker cron is the
primary trigger** (it fires `workflow_dispatch`) and GitHub's schedule is a
dead-man's fallback that no-ops via `/api/cronclaim` when the Worker already ran.

| Workflow | Primary (CF) | Fallback (GH) |
|---|---|---|
| `daily-cycle.yml` | `20 6 * * *` | `50 7 * * *` |
| `content-posting.yml` | `0 1,4,7,…,22 * * *` | `40 2,5,…,23 * * *` |
| `review-queue.yml` | `issue_comment` — `/approve`, `/reject` | |
| `webhook-events.yml` | `repository_dispatch` | |

Free assets publish automatically; paid assets open a GitHub Issue and wait for
`/approve`.

## Layout

| Path | What |
|---|---|
| `engine/` | The factory (24 modules — see below) |
| `workers/src/index.ts` | Cloudflare Worker: dashboard, APIs, `/p` pages, cron, Ko-fi webhook |
| `dashboard/index.html` | Command Center UI (served by the Worker) |
| `appsscript/youtube-bridge.gs` | YouTube upload + Blogger email via Google Apps Script |
| `.github/workflows/` | Four workflows |
| `state/` | `manifest.json`, `dist_queue.jsonl`, heartbeats, topic index |
| `docs/` | Architecture, resilience, distribution, monetization |

### Key modules

| Module | Responsibility |
|---|---|
| `run_daily.py` | Main cycle |
| `run_content.py` | 3-hourly posts + drains the distribution queue |
| `textgen.py` | LLM cascade + JSON truncation repair |
| `qc.py` | **Quality gate** and idle-run guard |
| `resilience.py` | **alert / retry / first_ok / safe** + circuit breaker |
| `preflight.py` | Fail-fast environment and manifest validation |
| `dist_core.py` | Durable queue, retry semantics, channel registry, CLI |
| `dist_channels.py` | All 22 channel adapters |
| `marketplace.py` | Whop Discover listing + idempotent status polling |
| `nostr_profile.py` | Publishes the kind-0 profile that enables zaps |

## Distribution

22 registered channels. **Only Whop can take money** — everything else is a
pointer or a reputation surface.

**Distribution is LIVE** (`DIST_POSTING_MODE=LIVE`).

**Working:** Nostr, dev.to, Bluesky, Mastodon, Discord, Webflow, Systeme.io,
FilePost, Hugging Face, itch.io, Buffer → X/LinkedIn/Pinterest, YouTube,
Tumblr, Archive.org, Zenodo, IndexNow.

Only **free, visible** products are distributed. Paid assets stay `hidden`
until `/approve`, and are enqueued at that point — broadcasting a hidden
product just advertises a dead link.

**Awaiting keys:** Telegram, Gumroad, Blogger.
**Blocked externally:** FetchApp (API down), Sellix (unreachable), Hashnode
(API went paid).

Nothing posts until `DIST_POSTING_MODE=LIVE`; channels with missing
credentials are skipped silently, so you can enable them one key at a time.

## Reliability

Built after a run reported **success while producing 0/3 assets**.

- **Fallbacks everywhere:** text (Mistral→Groq→Gemini), images (CF Flux→
  Pollinations), video (JSON2Video→ffmpeg), JSON (parse→repair→regenerate).
- **Retry** with backoff + jitter, transient faults only — a `403` fails
  immediately instead of burning the time budget.
- **Circuit breaker** — 3 consecutive failures parks a provider for 300s.
- **QC gate** blocks packs with too few prompts, duplicates, placeholder text
  or model leakage (`"As an AI…"`).
- **Discord alerts** on every critical failure, deduplicated, each linking to
  the failing run.

See [`docs/RESILIENCE.md`](docs/RESILIENCE.md).

## Operating

```bash
cd engine
python3 dist_core.py status        # queue + which channels are armed
python3 dist_core.py drain 10
python3 dist_core.py retry-failed
python3 nostr_profile.py           # after changing the lightning address

MOCK=1 DRY_RUN=1 python3 run_daily.py    # local dry run, posts nothing

cd ../workers && npx --yes wrangler@4.86.0 deploy   # pin 4.86 — Node 20 box
```

**Safety switches:** `DIST_POSTING_MODE` (default `DRAFT`),
`DIST_MODE_<CHANNEL>`, `QC_STRICT`, plus kill-switch and dry-run toggles in
Cloudflare KV.

## Monetization — read before proposing anything

The operator is in **Iran**, under comprehensive OFAC sanctions. Gumroad,
Ko-fi, Payhip, Lemon Squeezy, Stripe and PayPal **cannot pay out**, and
USDT/Tron is actively frozen. **Bitcoin Lightning zaps are the only working
rail** — `SharkSkin@coinos.io`, verified with `allowsNostr: true`, wired into
the Nostr profile, every note, and every `/p/` page.

See [`docs/MONETIZATION.md`](docs/MONETIZATION.md).

## Current state

**Verified working 2026-09-04.** Three consecutive real runs each produced
**3/3 assets at 100/100 QC** — generated, quality-gated, published to Whop with
cover images, submitted to Discover, and queued for distribution with no human
involvement.

| | |
|---|---|
| Products on Whop | 8 (4 live/free, 4 paid awaiting `/approve`) |
| Revenue | **$0 — nothing has sold yet** |
| Discover | 2 `pending_review` (Whop's manual queue) |
| Distribution | **LIVE**, 34 jobs queued |
| Email list | empty — no capture form exists |

**Next:**
1. Verify Whop can pay out to Iran (one support ticket — unblocks or kills the paid strategy)
2. Prove a zap lands — send 10 sats to `SharkSkin@coinos.io`
3. Approve or archive the 4 pending paid products
4. **Rotate every credential** — all were exposed in chat
5. Prune the store; several products were generated during debugging

## Recent fixes worth knowing

| Fix | Why it mattered |
|---|---|
| JSON truncation repair + 8k tokens | Packs were dying mid-generation; runs shipped **0/3 assets while reporting success** |
| QC gate + idle-run guard | Blocks thin/leaked packs; fails the run loudly instead of a green tick on an idle factory |
| `$0` plan **before** marketplace submit | Ordering bug silently kept **every free asset off Discover** |
| `external_identifier` removed | Whop now 400s on it for every value; omitting it works |
| `ensure_shape()` | A missing `skills` key `KeyError`d a pack that had already scored 100/100 |
| Prompt top-up | Models return 3 prompts when asked for 10 — now tops up instead of failing QC |
| Paid assets not enqueued | 4 hidden products had queued **68 posts** pointing at dead links |


## Upsells

Every free lead magnet carries **two** upsells, on the product page (where the
buying decision happens) as well as inside the deliverable:

| Upsell | Where it points |
|---|---|
| ⭐ **Pro version** | the live PAID product most related to that free pack, chosen by topic-word overlap. Falls back to the store front page. Override with `UPSELL_PRO_URL`. |
| 🛠 **Custom work** | `/custom` — a lead-capture page on the Worker. Override with `UPSELL_CUSTOM_URL`. |

Both are guaranteed by `ensure_shape()` even when the LLM omits them.

**Why capture is self-hosted:** Whop's `/leads` API rejects every email we send
it (`Invalid value for parameter 'email'`), so leads are stored in Worker KV and
announced to Discord instead. Read them with `GET /api/leads` + `X-Bot-Token`.

## Worker routes

| Route | What |
|---|---|
| `/` | Command Center dashboard |
| `/p`, `/p/:slug` | canonical pack pages (JSON-LD, OG, zap CTA) |
| `/tools`, `/tools/:slug` | Factory 4 browser tools |
| `/custom` | custom-work lead capture |
| `/sitemap.xml`, `/rss.xml`, `/robots.txt` | SEO plumbing |
| `/api/factories` | all-factory status + staleness alerts |
| `/api/sales`, `/api/kofi` | revenue tracking + Ko-fi webhook |
