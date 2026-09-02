# ⚡ The Algorithmic Daemon Concern — Asset Bot

> A 24/7 autonomous storefront. It invents digital products, builds them,
> packages them into real files, generates promo media, publishes them to a
> Whop store, writes marketing content about them, and posts that content to
> forums — on **$0/month infrastructure** with no payment method on any account.

**This README is written to fully onboard a new engineer or AI agent.** Read
§1–§4 to understand the system, §5–§9 to operate it, §10–§13 to change it
safely. Every non-obvious design decision has a "why" — most were paid for
with a production bug.

---

## 0. Orientation — the 60-second version

```
                    ┌──────────────────────────────────────────┐
   GitHub Actions   │  daily-cycle.yml    (cron 06:23 UTC)     │
   = the compute    │  content-posting.yml(cron :17, 8×/day)   │
                    │  review-queue.yml   (on issue_comment)   │
                    │  webhook-events.yml (on repo_dispatch)   │
                    └────────────────┬─────────────────────────┘
                                     │ runs Python in engine/
                                     ▼
   ┌─────────────────────────────────────────────────────────────────┐
   │ engine/  topics → generate_pack → packaging → media → hosting   │
   │          → publish (Whop)  → review (GitHub Issues)             │
   │          content → post (Whop forums)                           │
   └────────────────┬────────────────────────────────────────────────┘
                    │ commits state back to git
                    ▼
   state/*.json  ── the bot's memory (source of truth, versioned)
                    ▲
                    │ read via authenticated proxy
   ┌────────────────┴────────────────────────────────────────────────┐
   │ Cloudflare Worker  asset-bot-edge                               │
   │  • serves dashboard/index.html (the Command Center)             │
   │  • /api/summary  — aggregated analytics                         │
   │  • /api/set /api/dispatch /api/comment — controls (token-gated) │
   │  • /webhook/whop — Whop events → repository_dispatch            │
   │  • KV BOT_STATE  — kill switch + dry run flags                  │
   └─────────────────────────────────────────────────────────────────┘
```

**The one human decision in the entire system:** approving a paid asset.
Everything else is automatic.

---

## 1. Quick reference card

| What | Where |
|---|---|
| **Command Center** | https://asset-bot-edge.simalidudu.workers.dev |
| Whop store | https://whop.com/the-algorithmic-daemon-concern |
| GitHub repo | https://github.com/simalidudu-boop/asset-bot |
| Asset hosting (free CDN) | GitHub Releases, tag `deliveries-YYYY-Www` (one per ISO week) |
| Company ID | `biz_A79oVYva4QTT8Z` |
| Public forum | `exp_yAsqFQ7ZjnjgaN` |
| Members forum | `exp_D0PxzzbduumS4k` |
| Control token | stored in your browser only; never in this repo (it is public) |

**Schedules (UTC).** Note the odd minutes — see §4.1, this is deliberate.

| What | Cron | Volume |
|---|---|---|
| Daily asset cycle | `23 6 * * *` (06:23) | 1 free + 2 paid assets |
| Content posting | `17 1,4,7,10,13,16,19,22 * * *` | 1 post/run → up to 8/day × 2 forums |

---

## 2. The four phases

| Phase | Trigger | What happens | Autonomy |
|---|---|---|---|
| **A+B — Assets** | `daily-cycle.yml` | pick topic → generate pack → package to PDF/DOCX/HTML/ZIP → promo images + slideshow video → upload to GitHub Releases → create Whop product | free: auto-live · paid: gated |
| **C — Content** | `content-posting.yml` | pick a live free asset → write a post about it → post to public forum + a variant to members forum | fully automatic |
| **D — Webhooks** | `webhook-events.yml` | Whop payment/membership event → Worker → `repository_dispatch` → appended to `state/events.jsonl` | fully automatic |
| **Review** | `review-queue.yml` | `/approve` or `/reject` comment on a review Issue → create plan + make visible, or close | **you decide** |

**Autonomy rules**

- ✅ Free assets → fully automatic, no review.
- ✅ Content posts → fully automatic, no review.
- ⛔ Paid assets → created **hidden with no plan**, wait for your `/approve`.
- 💀 Kill switch → every scheduled run aborts immediately.
- 🛟 Dry run → generates everything, publishes nothing.

---

## 3. Repo map — what every file does

```
asset-bot/
├── engine/                     ← all Python. Runs on GitHub Actions runners.
│   ├── preflight.py            ← ★ FAIL-FAST GATE. Runs before every phase.
│   │                             Validates secrets, LLM keys, manifest
│   │                             integrity, and live asset URLs. Raises →
│   │                             the run goes red instead of silently no-oping.
│   ├── run_daily.py            ← Phase A+B entrypoint. Orchestrates one batch.
│   ├── run_content.py          ← Phase C entrypoint. Picks asset, posts, beats.
│   ├── topics.py               ← topic selection + dedupe (embeddings, cached)
│   │                             + record_asset() = the ONLY writer of assets
│   │                             into state/manifest.json.
│   ├── generate_pack.py        ← topic → structured pack JSON → markdown.
│   │                             MOCK=1 returns a canned pack (no keys needed).
│   ├── packaging.py            ← markdown → html/pdf/docx/zip deliverables
│   ├── media.py                ← images (CF Flux → Pollinations) + ffmpeg video
│   ├── hosting.py              ← uploads to GitHub Releases (the free CDN)
│   ├── publish.py              ← Whop product + plan creation, pricing, gating
│   ├── post.py                 ← forum posting + fix_links() URL sanitiser
│   ├── content.py              ← writes the marketing copy for one asset
│   ├── review.py               ← opens/closes review Issues, close_issue()
│   ├── approve_from_issue.py   ← /approve handler (dedup-guarded)
│   ├── reject_from_issue.py    ← /reject handler
│   ├── react_webhook.py        ← Phase D handler
│   ├── textgen.py              ← the $0 LLM router (see §6)
│   └── whop_client.py          ← thin Whop REST wrapper
├── workers/
│   ├── src/index.ts            ← Cloudflare Worker: dashboard host, control
│   │                             API, GitHub proxy, /api/summary analytics,
│   │                             Whop webhook relay, Workers-AI image endpoint
│   └── wrangler.json           ← KV + AI bindings, GH_OWNER/GH_REPO vars
├── dashboard/index.html        ← the Command Center (single file, no build)
├── state/                      ← ★ THE BOT'S MEMORY. Committed back each run.
│   ├── manifest.json           ← assets + posts ledger. THE critical file.
│   ├── heartbeat.json          ← last successful run per phase (staleness)
│   ├── events.jsonl            ← every Whop webhook event
│   ├── topics_index.json       ← used topics + cached embedding vectors
│   ├── roundrobin.txt          ← which asset to promote next
│   ├── fmt_rotation.txt        ← which post format to use next
│   └── llm_<provider>.json     ← per-provider daily call budgets
├── prompts/                    ← style guide + CTA templates (edit these to
│                                 change the bot's voice without touching code)
├── topics/seed_topics.md       ← your seed topics, one per `- ` line
└── .github/workflows/          ← the four workflows (see §2)
```

---

## 4. Critical invariants — break these and the bot misbehaves silently

These are the rules the system depends on. Each one exists because violating
it caused a real production failure.

### 4.1 Cron must NOT run at the top of the hour

GitHub queues `schedule` events behind push/PR events and drops them under
load. At `0 * * * *` — the most contended minute on the platform — we measured
an **average 87-minute lag** and roughly half of all runs never firing.
Schedules are therefore offset to `:17` and `:23`.

Check current punctuality any time:
```bash
curl -s https://asset-bot-edge.simalidudu.workers.dev/api/summary | jq .cron
```
If `avgLagMin` stays above ~60, migrate timing to a Cloudflare Worker cron that
calls `repository_dispatch` — the Worker already holds a `GH_TOKEN`.

### 4.2 `state/` is git-tracked — NEVER also cache it

There used to be an `actions/cache` step restoring `state/`. It overwrote the
committed files with a stale snapshot, and the commit-back step then pushed
that stale copy — **silently reverting real state on every run**. A repaired
manifest was reverted within one run.

> **Rule: git is the single source of truth for `state/`.** Do not reintroduce
> `actions/cache` on that path.

### 4.3 One slug = one product, forever

`manifest.json` previously held five assets sharing the slug
`zero-click-content-machine`, four of which had no product at all. Content
posts linked all of them to one URL, and to products that were never created.

`topics.record_asset()` now calls `unique_slug()` (appends `-2`, `-3`, …) and
persists `free`, `price`, `product_id`, `status`. Never write assets into the
manifest by hand or from another code path.

Valid `status` values: `live` · `pending_approval` · `no_plan` · `orphaned` · `staged`.

### 4.4 Never fabricate a product URL

`asset_link()` returns `""` rather than guessing `BASE/<slug>` for an asset
with no `product_id`. Guessing produced live posts pointing at 404s.

### 4.5 Never emit a bare URL at the end of a sentence

`https://…/zero-click-content-machine.` — Whop absorbs the trailing period
into the path and returns **404**. `post.fix_links()` rewrites any URL glued to
trailing punctuation before posting. It runs automatically inside `_post()`.

### 4.6 Only promote assets that are free AND reachable

`pick_assets()` requires `free is True` **and** a `page_url` or `product_id`.
It used to default `a.get("free", True)` — so assets with no `free` field, i.e.
all of them, were promoted as free, including paid ones.

### 4.7 A green run is not proof of success

Historic failure mode: everything logged "success" while doing nothing useful.
Countermeasures now in place — keep them:
- `preflight.py` raises on fatal misconfiguration.
- `state/heartbeat.json` records the last real run per phase.
- `/api/summary` raises alerts on staleness, orphans, and failed workflows.

---

## 5. The Command Center

Open **https://asset-bot-edge.simalidudu.workers.dev**
(append `?v=2` once if you get a stale cached page.)

### 5.1 Panels

| Panel | Shows |
|---|---|
| **🚨 Alerts** | staleness, orphaned assets, failed workflows, kill/dry engaged. Empty = healthy. |
| **🎛 Controls** | run either pipeline, mock toggle, kill switch, dry run, token reset |
| **📊 At a glance** | assets (total/free/paid/orphaned), posts (total/today), review queue depth, avg cron lag |
| **🩺 Workflow health** | per-workflow success rate, last conclusion, age |
| **⏱ Cron punctuality** | sparkline of minutes-late per scheduled run (amber >30m, red >90m) |
| **✅ Review queue** | open paid assets with Approve/Reject |
| **📦 Assets** | last 12 with FREE/PAID + status tags and live links |
| **📝 Posts** | last 15 with format/language breakdown |
| **🏃 Recent runs** | last 10 Actions runs, linked to logs |

Auto-refreshes every 60 s. All reads go through the Worker's authenticated
GitHub proxy, so the browser never hits the 60 req/h unauthenticated limit.

### 5.2 The control token

First use of any control prompts for the token. Stored in `localStorage`, sent
as `X-Bot-Token`, compared against the Worker's `BOT_TOKEN` secret. Anyone with
it can kill the bot or approve products.

Lost it? Redeploy the Worker with a new `BOT_TOKEN` secret and update the
matching GitHub Actions secret. The old value is unrecoverable.

### 5.3 Mock vs Dry vs Kill — know the difference

| Mode | Generates? | Publishes? | Scope |
|---|---|---|---|
| **Mock** (checkbox) | canned content, no LLM keys needed | no | one manual run |
| **Dry run** (KV flag) | yes, real generation | no | all runs until toggled off |
| **Kill switch** (KV flag) | no — aborts instantly | no | all runs until toggled off |

---

## 6. The $0 generation layer

| Need | Solution | Cost |
|---|---|---|
| Text | free-tier router: Mistral, Groq, Gemini, xAI, Cloudflare Workers AI | $0 |
| Images | Cloudflare Flux Schnell → Pollinations fallback | $0 |
| Video | ffmpeg slideshow on the runner | $0 |
| TTS | Cloudflare MeloTTS *(currently 500s — videos are silent)* | $0 |
| Scheduling | GitHub Actions cron | $0 |
| State | git + Cloudflare KV | $0 |
| CDN | GitHub Releases (public repo = free, stable URLs) | $0 |
| Dashboard/webhooks | Cloudflare Worker | $0 |

**Router order** (`engine/textgen.py`, automatic failover):
quality → `mistral → gemini → xai → groq → cloudflare`
bulk → `groq → gemini → cloudflare → mistral`

Every key is optional; the cascade skips providers whose key is absent. Daily
per-provider budgets live in `state/llm_*.json` and reset at UTC midnight.

> Cerebras and GitHub Models were removed in 2026 — their free tiers are dead.
> R2 is deliberately unused: it requires a card. Hosting is GitHub Releases.

---

## 7. Money flow — pricing and webhooks

- Prompt packs **$5–29** (scales with prompt count)
- Skill sets **$19–49**
- Free assets: `$0` plan + download links written into the description
- Custom work **$150–1,000** (manual product; the bot links to it)

Whop webhook `hook_BztRnwwFL4aGX` → `POST /webhook/whop` → buffered in KV →
`repository_dispatch` → `webhook-events.yml` → appended to `state/events.jsonl`.
Subscribed: `payment.succeeded`, `membership_went_valid`, `membership_went_invalid`.

**Whop API gotchas learned the hard way**

- Use `resource_id: biz_…` for webhooks, not `company_id`.
- **Plan writes (`PATCH`/`DELETE`) work on `/api/v1/plans/…` but return 401 on
  `/api/v2/`.** To retire a plan, `PATCH v1` with `{"visibility":"hidden"}`.
- `/api/v1/companies` requires `company:basic:read`, which the bot key lacks —
  harmless, nothing depends on it.
- `external_identifier` is rejected on product create; do not send it.

---

## 8. Daily operations

**Automatic:** assets at 06:23, content 8×/day, weekly release tag rollover.

**You, ~2 minutes/day:**
1. Open the Command Center.
2. Check **🚨 Alerts** is empty and the heartbeat pill is green.
3. Approve or reject anything in the review queue.
4. Glance at cron punctuality — sustained red means act on §4.1.

---

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Scheduled runs missing/late | GitHub cron contention | Expected up to ~90 min. Sustained? See §4.1. |
| `no published free assets to promote` | no asset with `free:true` + a URL | Check manifest status fields; run a daily cycle. |
| State reverts every run | `actions/cache` on `state/` | **Never cache `state/`** — §4.2. |
| Posts link to 404 | fabricated URL or trailing period | §4.4, §4.5 — both auto-handled now. |
| All posts are `text` | format rotation not advancing | `state/fmt_rotation.txt` must persist. §4.7. |
| Run red at preflight | missing secret / corrupt manifest | Read the `::error::` lines; they name the exact problem. |
| Approve leaves issue open | GitHub 422 on close | Handled — `review.close_issue()` sends `state_reason`, never fails the run. |
| Dashboard blank / 403 | GitHub rate limit | Reads go through the Worker proxy; hard-refresh with `?v=2`. |
| Groq `model_not_found` | Groq retired a model | `GET https://api.groq.com/openai/v1/models`, update `textgen.py`. |
| Push rejected | bot committed meanwhile | Workflows retry 5× with `--autostash`. Locally: `git pull --rebase`. |
| Duplicate `$0` plans on a paid product | double publish | `PATCH v1` the extra plan to `hidden` (§7). |

---

## 10. Secrets & configuration

**GitHub Actions secrets:** `WHOP_API_KEY`, `WHOP_COMPANY_ID`, `OWN_FORUM_ID`,
`PUBLIC_FORUM_ID`, `PRODUCT_PAGE_BASE`, `CF_API_TOKEN`, `CF_ACCOUNT_ID`,
`GH_TOKEN`, `BOT_TOKEN`, `EDGE_URL`, `WHOP_WEBHOOK_SECRET`, plus optional LLM
keys (`MISTRAL_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `XAI_API_KEY`,
`COHERE_API_KEY`).

**Worker secrets:** `BOT_TOKEN`, `GH_TOKEN`. **Worker vars:** `GH_OWNER`, `GH_REPO`.

**Env knobs:** `N_FREE`(1) `N_PAID`(2) `N_POSTS`(1) `POST_LANGS`(en)
`N_IMAGES`(2) `MAKE_VIDEO`(1) `PREFLIGHT_STRICT`(1) `SKIP_LINK_CHECK`(0)
`DRY_RUN` / `MOCK` / `KILL` (set by the guards).

> ⚠️ A Cloudflare token starting `cfat_` is **account-owned**: it fails at
> `/user/tokens/verify` and must be verified at
> `/accounts/{id}/tokens/verify`. A "dead" `cfat_` token is usually a wrong
> verify endpoint, not a dead token.

---

## 11. Working on this repo

```bash
git clone https://github.com/simalidudu-boop/asset-bot && cd asset-bot
git config user.name "asset-bot"; git config user.email "bot@users.noreply.github.com"
```

Test the whole pipeline offline, no keys, nothing published:
```bash
MOCK=1 DRY_RUN=1 python3 engine/run_daily.py
MOCK=1 DRY_RUN=1 python3 engine/run_content.py
python3 engine/preflight.py content      # validate config only
```

Deploy the Worker after editing `workers/src/index.ts`:
```bash
cd workers
export CLOUDFLARE_API_TOKEN=<token>
export CLOUDFLARE_ACCOUNT_ID=0c6059d950fad268faa25cbb6d21ef77
npx wrangler deploy
```

Committing (the bot commits too, so always rebase):
```bash
git add -A && git commit -m "describe the change"
git pull --rebase --autostash origin main && git push origin main
```
If a rebase conflicts on `state/`, prefer the remote copy — it is newer bot
state — and keep your code changes.

**Before you push, ask:** does this violate any invariant in §4?

---

## 12. Extending the bot

| Goal | Where |
|---|---|
| Change the voice | `prompts/style_guide.md`, `prompts/cta_templates.md` |
| Add topics | `topics/seed_topics.md` |
| Change pricing | `publish.price_for()` |
| Add an LLM provider | `textgen.PROVIDERS` + the order lists |
| Add a post format | `content.FORMATS` (rotation is automatic) |
| Add a dashboard metric | compute in the Worker's `/api/summary`, render in `dashboard/index.html` |
| Add a safety check | `preflight.py` — prefer FATAL over silent degradation |

---

## 13. Glossary

| Term | Meaning |
|---|---|
| Kill switch | KV flag; ON = scheduled runs abort before doing anything |
| Dry run | KV flag; ON = generate but never publish/post |
| Mock run | one-off dispatch using canned content, no LLM keys required |
| Preflight | `engine/preflight.py`; fails the run rather than degrading silently |
| Heartbeat | `state/heartbeat.json`; last successful run per phase |
| Orphaned asset | manifest entry with no Whop product — excluded from promotion |
| Manifest | `state/manifest.json`; the bot's ledger of assets and posts |
| Router | `textgen.py`; picks the first free LLM provider that answers |
| Review queue | open GitHub Issues labelled `asset-review` |
