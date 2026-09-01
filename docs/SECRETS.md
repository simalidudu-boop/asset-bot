# Secrets Checklist

Every secret the bot needs, where it lives, and how to get it. All optional
LLM keys can be added later — the $0 router skips missing providers.

## GitHub repo → Settings → Secrets and variables → Actions → Secrets

| Secret | Required | Where to get it |
|---|---|---|
| `GH_TOKEN` | ✅ (set by finish_github.py) | same classic PAT used for setup |
| `GH_MODELS_TOKEN` | ❌ retired (GitHub Models shut down 2026) | removed from router |
| `WHOP_API_KEY` | ✅ go-live | whop.com → Developer Portal → Account API keys (perms: `forum:post:create`, `access_pass:create`, products/plans) |
| `WHOP_COMPANY_ID` | ✅ go-live | `biz_...` — from Whop dashboard URL or `/accounts/me` + `/companies` |
| `OWN_FORUM_ID` | ✅ go-live | `exp_...` of your members-only forum experience |
| `PUBLIC_EXPERIENCE` | optional (default `public`) | leave as `public` to post to your company's public forum |
| `PRODUCT_PAGE_BASE` | ✅ go-live | `https://whop.com/YOUR-COMPANY-ROUTE` |
| `CF_API_TOKEN` | ✅ images | dash.cloudflare.com → My Profile → API Tokens → Workers AI:Edit + KV:Edit (new `cfat_` account tokens work) |
| `CF_ACCOUNT_ID` | ✅ images | Cloudflare dashboard right sidebar |
| `EDGE_URL` | optional | worker URL — only needed for the R2 /upload path (R2 requires a payment method; hosting is GitHub Releases by default) |
| `BOT_TOKEN` | optional | only needed for the R2 /upload path |
| `MISTRAL_API_KEY` | recommended | console.mistral.ai (Experiment tier = free, ~1B tokens/month) |
| `GROQ_API_KEY` | recommended | console.groq.com (free tier) |
| `CEREBRAS_API_KEY` | optional | cloud.cerebras.ai (free tier) |
| `GEMINI_API_KEY` | optional | aistudio.google.com (free tier) |
| `XAI_API_KEY` | optional | console.x.ai ($25 signup credits — premium pass only) |
| `COHERE_API_KEY` | optional | dashboard.cohere.com (trial key — embed/rerank) |

## Cloudflare Worker secrets (`npx wrangler secret put`)

| Secret | Value |
|---|---|
| `GH_TOKEN` | same PAT (worker uses it for repository_dispatch) |
| `BOT_TOKEN` | same random string as GitHub secret above |
| `CLOUDFLARE_API_TOKEN` | same CF token as above |

## Local .env for spike / setup

```
GH_PAT=github_pat_...   # only for finish_github.py, never committed
WHOP_API_KEY=...
WHOP_COMPANY_ID=...
OWN_FORUM_ID=...
CF_API_TOKEN=...
CF_ACCOUNT_ID=...
EDGE_URL=...
BOT_TOKEN=...
MISTRAL_API_KEY=...
GROQ_API_KEY=...
CEREBRAS_API_KEY=...
GEMINI_API_KEY=...
XAI_API_KEY=...
COHERE_API_KEY=...
```

To bulk-set secrets from a KEY=value file later:
`python3 finish_github.py --secrets-file secrets.env`
