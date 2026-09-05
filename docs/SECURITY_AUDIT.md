# Security audit — all factories

Run 2026-09-05, triggered by an unauthorised product publication.

## 🔴 CRITICAL 1 — Anyone could publish products to the live store

**Status: FIXED.**

GitHub user `Zhiyilang074811` (`author_association: NONE` — no relationship to
this repo) commented `/approve` on issue #10. Fifteen seconds later the
workflow created plan `plan_bHAZejF7Sdwmh` at **$11** and made the product
**visible and purchasable** on the live Whop store.

Cause: `review-queue.yml` gated on the comment *body* only —

```yaml
if: contains(github.event.comment.body, '/approve') || ...
```

The repo is public, so **any GitHub user on the internet** could publish, price
and list products — or `/reject` to destroy pending ones.

Fix: the job now also requires `OWNER`, `MEMBER` or `COLLABORATOR`.
Damage: product set to `hidden`, **zero sales occurred**.

## 🔴 CRITICAL 2 — Paid products are free to download

**Status: OPEN — needs a decision.**

Deliverables are hosted as **public GitHub Release assets**, and every review
issue publishes the direct links in a public repo. Verified as an anonymous
stranger with no token:

```
…-img-1-v2.jpg          200  348,273 b
…-img-2-v2.jpg          200  593,085 b
…-pack.pdf              200   57,693 b   (valid PDF 1.7)
…-pack.docx             200   42,968 b
…-pack.zip              200  110,778 b
```

**177 public files** across 68 jpg, 24 pdf, 24 docx, 24 zip, 24 html, 11 mp4.
Every paid product ever generated is downloadable for free, no login.

This is architectural, not a bug: `hosting.py` uses GitHub Releases because it
is free and reliable, and Whop's free-tier delivery needs a public URL. The
$0 products *should* be public. The $11-$14 ones should not.

### Options

| Option | Effect | Cost |
|---|---|---|
| **A. Whop-hosted delivery for paid** | Buyer gets files only after checkout | Whop file upload API; free products keep working as-is |
| **B. Private repo for paid deliverables** | Links 404 for non-owners | Whop cannot fetch them either — breaks delivery |
| **C. Signed/expiring URLs via the Worker** | Link works only with a purchase token | Needs a purchase→token flow; most work |
| **D. Accept it** | Paid catalogue is effectively free | $0 revenue by design |

Recommendation: **A**, and stop putting file links in public review issues —
the issue only needs the product id and a private summary.

## 🟡 MEDIUM — Review issues are public by design

The repo is public, so every `[Review]` issue exposes titles, prices, product
ids and download links before you approve anything. Competitors can watch the
catalogue in real time. Making the repo private would fix issues 1–3 at once,
but breaks GitHub Releases as a delivery mechanism for the free tier.

## 🟢 CLEAN

| Check | Result |
|---|---|
| Secrets in git history (30 days) | **none** |
| Secrets in tracked files | **none** |
| Worker mutating endpoints unauthed | **none** — all 7 check a token |
| Secrets leaked in API responses | **none** across summary/config/sales/cronlog |
| Ko-fi webhook | token-verified, replay-protected |
| Factory 2 | disabled ×3 (workflow, cron, runtime flag) |
| Factory kill switches | F2/F3/F4 all require an explicit `*_ENABLED=1` |
| Distribution | defaults to `DRAFT`; missing keys skip silently |

## 🟡 Other workflows

`daily-cycle`, `content-posting`, `factory3`, `factory4` trigger on
`schedule` + `workflow_dispatch` only. Dispatch already requires write access,
so no actor check is needed. `webhook-events` uses `repository_dispatch`,
which also requires a token.

## Actions for the operator

1. **Decide on CRITICAL 2** (paid file exposure) — the only open item.
2. **Rotate every credential.** All were pasted in chat; none are in the repo,
   but chat history is not a vault.
3. The unauthorised product `prod_lY8V0LqQ9dr0x` is hidden — approve or archive.
