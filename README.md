# asset-bot

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

**Live:** Nostr, dev.to, Bluesky, Mastodon, Discord, Webflow, Systeme.io,
FilePost, Hugging Face, itch.io, Buffer → X/LinkedIn/Pinterest, YouTube,
Tumblr, Archive.org, Zenodo, IndexNow.

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

2 live products ($0 and $11), **$0 revenue**, both still `pending_review` on
Whop Discover. The machine is built and running; it has not yet sold anything.

Next: verify Whop payouts to Iran, prove a zap lands, ship a bundle, rotate
credentials.
