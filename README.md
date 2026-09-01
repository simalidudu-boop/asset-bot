# Asset Bot — 24/7 Whop store automation at $0

Generates AI prompt packs & skill sets (1 free + 2 paid/day), packages them
as PDF/HTML/MD/DOCX/ZIP, lists them on your Whop store, promotes them with
AI images + slideshow videos, and posts 6–8 content pieces/day to the
**public Whop space** and **your own forum** — fully automated, free to run.

## Architecture

```
 Cloudflare Worker (edge)          GitHub Actions (orchestrator, free)
 ┌─────────────────────────┐       ┌──────────────────────────────────┐
 │ /webhook/whop → KV →    │──────▶│ cron 4x/day: topics → packs →   │
 │   GitHub dispatch       │       │   package → media → publish     │
 │ /image (Flux Schnell)   │◀──────│ cron 8x/day: content → post to  │
 │ /upload → R2 (CDN)      │ files │   public + own forum            │
 └─────────────────────────┘       │ /approve issues → paid go live  │
                                   └──────────────────────────────────┘
              Whop: products/plans · forum_posts · webhooks
```

## The $0 generation layer

Text goes through a cascade router (`engine/textgen.py`) across free tiers —
**Mistral** (1B tok/mo), **Groq**, **Cerebras**, **GitHub Models**, **Gemini**,
**Cloudflare Workers AI**, **xAI** (credits only). ~40k tokens/day needed vs.
millions available. Images: Cloudflare Flux Schnell (10k neurons/day) →
Pollinations fallback. Video: images + TTS + ffmpeg on the free runner.

## Setup (one time)

1. **Push this repo to GitHub** (public repo = unlimited free Actions minutes):
   ```
   git init && git add -A && git commit -m "asset bot"
   git remote add origin git@github.com:YOU/asset-bot.git && git push -u origin main
   ```
2. **Cloudflare:** `npx wrangler deploy` from `workers/` after:
   - `wrangler kv namespace create BOT_STATE` → put the id in `wrangler.toml`
   - `wrangler r2 bucket create asset-bot-promo`
   - `wrangler secret put GH_TOKEN` (PAT with `repo` scope)
   - `wrangler secret put BOT_TOKEN` (any random string — matches Actions secret)
   - `wrangler secret put CLOUDFLARE_API_TOKEN`
   - edit `GH_OWNER`/`GH_REPO` vars in `wrangler.toml`
3. **Whop dashboard:** create an **Account API key** with permissions
   `forum:post:create`, `access_pass:create`, product/plan create. Subscribe
   webhooks (`payment.succeeded`, `membership.activated`) to
   `https://YOUR-WORKER.workers.dev/webhook/whop`.
4. **GitHub repo → Settings → Secrets and variables → Actions:**
   | Secret | Value |
   |---|---|
   | `WHOP_API_KEY` | account key |
   | `WHOP_COMPANY_ID` | `biz_...` |
   | `OWN_FORUM_ID` | `exp_...` of your members forum |
   | `PUBLIC_EXPERIENCE` | `public` (your company's public forum) |
   | `PRODUCT_PAGE_BASE` | `https://whop.com/YOUR-COMPANY-ROUTE` |
   | `CF_API_TOKEN` / `CF_ACCOUNT_ID` | Cloudflare |
   | `EDGE_URL` | `https://YOUR-WORKER.workers.dev` |
   | `BOT_TOKEN` | same random string as Worker |
   | `GH_TOKEN` | PAT with repo+contents scope |
   | `MISTRAL_API_KEY` | console.mistral.ai (experiment tier) |
   | `GROQ_API_KEY` / `CEREBRAS_API_KEY` / `GEMINI_API_KEY` / `GH_MODELS_TOKEN` / `XAI_API_KEY` / `COHERE_API_KEY` | optional — router skips missing |

## Runbook

```bash
# Phase 0 — verify integrations (on your machine with keys):
python3 spike/run_spike.py

# Local end-to-end test with ZERO keys (mock pack -> pdf/docx/zip):
MOCK=1 DRY_RUN=1 python3 engine/run_daily.py --assets-only
MOCK=1 DRY_RUN=1 python3 engine/run_content.py

# Go live:
#  - remove DRY_RUN (daily-cycle.yml and content-posting.yml run LIVE by default)
#  - approve paid assets by commenting /approve on their review Issues
```

## How publishing works

- **Free asset** → Whop product (visible) + $0 plan, live immediately.
- **Paid asset** → product created *hidden*, review Issue opened with previews
  + real file links. Comment `/approve` → plan + visible. `/reject` → closed.
- **Deliverables** → R2 public CDN via the Worker; Whop Files-app upload path
  is confirmed in the spike (fallback: R2 links in product page + welcome msg).
- **Every content post** contains the free asset's Whop page link + one CTA
  (Pro upsell or custom work $150+).

## State

- `state/topics_index.json` — dedupe index (embeddings + used topics)
- `state/manifest.json` — assets (slug, page_url) + post history
- `state/llm_*.json` — per-provider daily budgets (auto-reset at midnight)
- `state/events.jsonl` — every webhook event

All persisted by committing back to the repo from the workflow.

## Pricing (auto)

- Prompt packs: **$5–29** (depth-based: prompt count)
- Skill sets: **$19–49**
- Custom work product: **$150–1,000** (create once manually, bot links to it)

## Repo map

```
engine/            textgen router · whop client · generate_pack · packaging
                   media · publish · topics · content · post · review
                   run_daily · run_content · react_webhook · approve_from_issue
workers/           Cloudflare Worker (webhooks, /image, /upload, R2 CDN)
.github/workflows/ daily-cycle · content-posting · webhook-events · review-queue
prompts/           style guide (bot bootstraps from seeds) · CTA templates
topics/            seed topics (edit anytime)
spike/             Phase 0 verification kit
```
