# ⚡ The Algorithmic Daemon Concern — Asset Bot

> Your 24/7 Whop automation engine. It creates AI prompt packs and skill
> assets, lists them on your Whop store, posts content to your forums,
> and runs on **$0/month infrastructure** (no card on any account).

This file is your documentation, user manual and daily operations guide.
If the bot misbehaves, start at [§8 Troubleshooting](#8-troubleshooting).

---

## 0. Quick reference card

| What | Where |
|---|---|
| **Command Center** (your control room) | https://asset-bot-edge.simalidudu.workers.dev |
| Whop store | https://whop.com/the-algorithmic-daemon-concern |
| GitHub repo (code, runs, issues) | https://github.com/simalidudu-boop/asset-bot |
| Worker (API + dashboard host) | https://asset-bot-edge.simalidudu.workers.dev |
| Asset hosting (free CDN) | GitHub Releases, tag `deliveries-YYYY-WW` (one per week) |
| Company ID | `biz_A79oVYva4QTT8Z` |
| Public forum (general public space) | `exp_yAsqFQ7ZjnjgaN` |
| Your forum (members space) | `exp_D0PxzzbduumS4k` |
| Control token | given to you in chat — stored in your browser (never printed here; repo is public) |

**Schedules (UTC):**

| What | When | Volume |
|---|---|---|
| Daily asset cycle | 06:00 UTC daily | 1 free + 2 paid assets |
| Content posting | every 3 h (01, 04, 07, 10, 13, 16, 19, 22) | 1 post per run → 6–8 posts/day |

---

## 1. What the bot does

Four phases run continuously:

| Phase | What happens | Runs where |
|---|---|---|
| **A+B — Assets** | Picks a topic (from your seed topics + bot-suggested), generates a prompt pack / skill set (text + code recipes), produces PDF / DOCX / HTML / ZIP, creates AI promo images and a slideshow video, uploads everything to GitHub Releases, then lists the product on Whop | `daily-cycle` workflow |
| **C — Content** | Writes a free LLM post relevant to one of your free assets, attaches an AI image, posts to the **public forum** and a variation to **your forum**, every post links to that asset's Whop page | `content-posting` workflow |
| **D — Webhooks** | Whop sends payment/membership events → the Worker relays them → GitHub records them in `state/events.jsonl` | `webhook-events` workflow |
| **Review queue** | Paid assets wait as GitHub Issues with the `asset-review` label until you approve them | `review-queue` workflow |

**Autonomy rules (by your instruction):**

- ✅ Free assets → fully automatic, no review.
- ✅ Content posts → fully automatic, no review.
- ⛔ Paid assets → drafted, **wait for your /approve** in the Command Center.
- 💀 Kill switch → aborts every scheduled run.
- 🛟 Dry run → generates everything, posts nothing to Whop.

---

## 2. Command Center — user manual

Open **https://asset-bot-edge.simalidudu.workers.dev**

> If panels show stale data after an update, load it once with `?v=2` to
> bypass the 5-minute HTML cache.

### 2.1 First visit — the control token

The first time you use a control, the page asks for the **control token**
(the one you were given in chat). It is stored only in your browser
(localStorage), used as the `X-Bot-Token` header, and checked against the
secret on the Worker. Never share it — anyone with it can kill the bot or
approve products.

*If you lose it:* it can be reset by re-deploying the Worker with a new
`BOT_TOKEN` secret and updating the `BOT_TOKEN` GitHub secret to match
(see §9). The old value is not recoverable from anywhere.

### 2.2 Status pills (top right)

| Pill | Meaning |
|---|---|
| **WORKER** | Green = the edge API is responding. |
| **KILL SWITCH** | Green = **ON** → every scheduled run aborts itself. Red = OFF (normal). |
| **DRY RUN** | Green = **ON** → runs generate but never post to Whop. Red = OFF (normal). |
| **LAST RUN** | Most recent workflow run time + result. |

### 2.3 Controls

| Button | What it does | Effect |
|---|---|---|
| ▶ **RUN DAILY CYCLE** | Dispatches the asset pipeline immediately | New assets within ~5–10 min |
| ▶ **RUN CONTENT POST** | Dispatches the content pipeline immediately | New posts within ~2–5 min |
| ☑ **mock mode** | When ticked, the next manual run posts nothing real | Safe trial of a run |
| ☠ **KILL SWITCH** | Toggles the kill flag (persisted in KV) | ON = every scheduled run exits instantly |
| 🛟 **DRY RUN** | Toggles the dry flag (persisted in KV) | ON = bot keeps working but never touches Whop |

Toggle state is stored in Cloudflare KV (`BOT_STATE`), so it survives
worker redeploys and applies to **all** future runs until you flip it back.

### 2.4 Review queue — approving or rejecting a paid asset

1. Every daily cycle opens one GitHub Issue per paid asset, labelled
   `asset-review`, titled `[Review] <title> ($price)`. It appears in the
   queue panel with **✅ Approve** and **✖ Reject** buttons.
2. **Approve** → `review-queue` workflow creates the plan on Whop at the
   proposed price, makes the product **visible**, comments the result, and
   closes the issue.
3. **Reject** → the issue is closed and the product stays hidden on Whop
   (no plan). You can re-open the issue on GitHub and approve later if you
   change your mind.
4. Double-clicking Approve is safe — a dedup guard prevents double plans.

The queue is where the **only** human decision in the whole system lives.
Everything else is automatic.

### 2.5 Panels

| Panel | Shows | Source |
|---|---|---|
| Pipeline runs | Recent GitHub Actions runs (success/failure, link to logs) | GitHub API |
| Assets | Last 12 assets: FREE/PAID tag, Whop link, status, topic | `state/manifest.json` |
| Posts | Last 15 posts: title, format, language, time | `state/manifest.json` |
| LLM budgets | Today's calls per provider (progress bars) | `state/llm_*.json` |
| Events | Last 10 Whop webhook events | `state/events.jsonl` |

All reads go through the Worker's GitHub proxy (authenticated + cached),
so the page never hits browser rate limits.

---

## 3. Daily operations — what runs itself, what you do

**Automatic (no action needed):**

- 06:00 UTC — daily cycle: 1 free + 2 paid assets created, free one goes
  live with a $0 plan and download links, paid ones appear in your queue.
- Every 3 h — a new content post (public forum + your forum).
- Weekly — a new GitHub Release tag hosts the week's deliverables.

**You (usually 2 minutes a day):**

1. Open the Command Center.
2. Glance at the status pills (KILL OFF, DRY OFF is normal).
3. Approve or reject whatever sits in the review queue.
4. Optionally watch the Posts panel to see the voice the bot developed.

---

## 4. Assets & pricing

- **Prompt packs**: 6–10 prompts each → **$5–$29**
- **Skill sets**: include Python / Apps Script code recipes → **$19–$49**
- **Free assets**: `$0` one-time plan + download links (PDF, DOCX, ZIP, HTML)
  written directly into the product description, plus aggressive upsells in
  the pack and in every content post that links to it.
- **Custom work** (manual, you): **$150–$1,000**.

Deliverables per asset: `.pdf`, `.docx`, `.zip`, `.html` pack page,
2 promo `.jpg` images, and a `.mp4` slideshow video (images + text +
narration, built with ffmpeg — free).

---

## 5. Content system

- Every post is written about **a free asset** and links to its Whop page
  (`PRODUCT_PAGE_BASE` + route).
- Two variants per post: one for the **public forum**, one for **your forum**.
- Posting is staggered and volume-limited (1 per run, 8 runs/day → 6–8 posts).
- **Multilingual**: variants can be translated (primary language English,
  translations for other languages per your settings).
- Images come from Cloudflare Workers AI (Flux Schnell), falling back to
  Pollinations — both free.

---

## 6. The $0 infrastructure

| Need | Solution | Cost |
|---|---|---|
| Text generation | Free-tier router: Groq (`qwen/qwen3.8-27b`), Gemini, Mistral, xAI, Cloudflare | $0 |
| Images | Cloudflare Workers AI (Flux Schnell) → Pollinations fallback | $0 |
| Videos | ffmpeg slideshows on the GitHub runner | $0 |
| Scheduling | GitHub Actions (cron + dispatch) | $0 |
| State | GitHub repo + Cloudflare KV (free tier) | $0 |
| Asset hosting/CDN | GitHub Releases (stable public URLs) | $0 |
| Dashboard + webhooks | Cloudflare Worker (free tier) | $0 |

**Router order** (automatic failover): quality tasks
mistral → gemini → xai → groq → cloudflare; bulk tasks
groq → gemini → cloudflare → mistral.

> Cerebras and GitHub Models were removed — their free tiers are dead.

---

## 7. Webhooks (money events)

Whop webhook `hook_BztRnwwFL4aGX` → `POST /webhook/whop` on the Worker →
buffered in KV → GitHub `repository_dispatch` → `webhook-events` workflow
appends to `state/events.jsonl`.

Events subscribed: `payment.succeeded`, `membership_went_valid`,
`membership_went_invalid`. The signing secret lives in the
`WHOP_WEBHOOK_SECRET` GitHub secret.

---

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Panels show "error 403" or everything blank | GitHub unauthenticated rate limit (60/h) | Fixed: reads now go through the Worker proxy. Hard-refresh with `?v=2`. |
| "state not published yet" | Manifest never written (no successful run yet) | Run a daily cycle once; check its run page. |
| Queue empty but you expected items | All review issues closed (approved/rejected) | Normal. See closed issues on GitHub if unsure. |
| Run shows name `./workflows/x.yml`, 0 jobs, failure | A workflow file failed GitHub's YAML validation (e.g. duplicate env key) | Check the workflow file for duplicate keys; fix and push. |
| Groq provider errors 1010 / 403 | Python default User-Agent blocked | Engine already sends `Mozilla/5.0 (asset-bot)`. Don't remove it. |
| Groq `model_not_found` | Groq retired a model | Enumerate `GET https://api.groq.com/v1/models` and update `engine/textgen.py`. |
| Push rejected (non-fast-forward) | The bot committed while you worked | `git fetch && git rebase FETCH_HEAD` then push (see §9). |
| Whop 400 "Please provide a resource id" | Webhook/API call missing `resource_id` | Use `resource_id: biz_A79oVYva4QTT8Z` (not `company_id`) for webhooks. |
| Plans list endpoint returns error | Business key lacks that scope | Creation works; the engine never relies on the list. |
| Product exists but no plan | Plan creation failed mid-run | Re-run the cycle in mock off, or approve from the issue again. |
| `error code: 1101` from a control call | Worker threw — usually a bad GitHub dispatch | Check the workflow YAML on main; see run history. |

---

## 9. Repo map & where things live

```
asset-bot/
├── engine/                # all Python logic (runs on GitHub Actions)
│   ├── run_daily.py       # Phase A+B entry: topics → packs → publish → review
│   ├── run_content.py     # Phase C entry: posts for the current window
│   ├── textgen.py         # $0 LLM router (Groq/Gemini/Mistral/xAI/Cloudflare)
│   ├── generate_pack.py   # prompt packs & skill sets (text + code)
│   ├── media.py           # images (Workers AI / Pollinations) + slideshow videos
│   ├── packaging.py       # pdf / docx / html / zip deliverables
│   ├── hosting.py         # GitHub Releases upload (weekly tags)
│   ├── publish.py         # Whop product + plan creation, visibility, pricing
│   ├── post.py            # forum posting (public + own forum, variants, langs)
│   ├── review.py          # opens/closes review issues, comments
│   ├── approve_from_issue.py  # /approve handler (dedup-guarded)
│   ├── reject_from_issue.py   # /reject handler
│   ├── react_webhook.py   # Phase D handler
│   ├── topics.py          # seed topics + bot-suggested topics
│   └── whop_client.py     # shared Whop API helper
├── workers/
│   ├── src/index.ts       # Cloudflare Worker: dashboard, control API, webhooks, images
│   └── wrangler.json      # worker config (KV, AI binding, vars)
├── dashboard/
│   └── index.html         # the Command Center UI (single file)
├── state/                 # bot state committed back to the repo
│   ├── manifest.json      # assets + posts ledger
│   ├── events.jsonl       # webhook event log
│   └── llm_<provider>.json# daily per-provider call counters
└── .github/workflows/
    ├── daily-cycle.yml    # cron 06:00 UTC + manual dispatch
    ├── content-posting.yml# cron every 3h + manual dispatch
    ├── review-queue.yml   # runs on issue comments (/approve, /reject)
    └── webhook-events.yml # runs on repository_dispatch from the Worker
```

### Committing changes

```bash
cd asset-bot
git config user.name "asset-bot"            # once per machine
git config user.email "bot@users.noreply.github.com"
git add -A && git commit -m "describe the change"
git fetch origin main && git rebase FETCH_HEAD   # bot commits land meanwhile
git push origin main
```

If the rebase conflicts on `state/`, keep the remote state and your code:

```bash
git checkout --ours state/ && git add -A && git -c core.editor=true cherry-pick --continue
```

### Deploying the Worker after changing `workers/src/index.ts`

```bash
cd workers
export CLOUDFLARE_API_TOKEN=<cf token>   # not stored in the repo
export CLOUDFLARE_ACCOUNT_ID=0c6059d950fad268faa25cbb6d21ef77
npx wrangler deploy
```

---

## 10. Secrets & configuration (names only — values never live in the repo)

GitHub repo secrets (used by workflows): `WHOP_API_KEY`,
`WHOP_COMPANY_ID`, `OWN_FORUM_ID`, `PUBLIC_FORUM_ID`, `PRODUCT_PAGE_BASE`,
`MISTRAL_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `COHERE_API_KEY`,
`XAI_API_KEY` (unused), `GH_TOKEN`, `BOT_TOKEN`, `WHOP_WEBHOOK_SECRET`.

Worker secrets: `BOT_TOKEN` (control token), `GH_TOKEN` (GitHub API).
Worker vars: `GH_OWNER`, `GH_REPO`.

Environment knobs in the workflows: `N_FREE` (default 1), `N_PAID`
(default 2), `N_POSTS` (default 1), `POST_LANGS` (default `en`),
`DRY_RUN` / `MOCK` (auto-set by the guards), `KILL` (auto-checked).

---

## 11. Glossary

| Term | Meaning |
|---|---|
| Kill switch | KV flag; ON = scheduled runs abort before doing anything |
| Dry run | KV flag; ON = generate but never publish/post |
| Mock run | one-off dispatch with fake outputs (no LLM keys needed) |
| Review queue | open GitHub Issues labelled `asset-review` |
| Router | `engine/textgen.py` — picks the free provider that answers |
| Manifest | `state/manifest.json` — the bot's ledger of assets & posts |
| Free asset | $0 plan + download links; carries upsells |
| Paid asset | hidden until you /approve; gets a plan at the proposed price |
