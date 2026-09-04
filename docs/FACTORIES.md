# The factory architectures

Three factories exist. They are **not** variations of one idea — they are three
structurally different answers to the question *"how does an asset reach a
person, and how does money come back?"*

Naming them matters because the difference is architectural, and choosing
wrong for Factory 4 wastes weeks.

---

## Factory 1 — **THE STOREFRONT**

> *Gated asset, hosted checkout, platform-mediated delivery.*

| | |
|---|---|
| Asset | AI prompt packs (MD / PDF / DOCX) |
| Lives at | Whop product page |
| **Delivery** | **Buyer checks out → Whop grants access → download links in the product description** |
| Money | Whop checkout (payout to Iran **unverified**) + affiliates at 40% |
| Gate | Free = instant; paid = hidden until `/approve` |
| Approval needed | **Yes** — Whop marketplace review, and a working payout rail |

**The defining property:** the asset is *withheld* until a transaction
completes. That is what makes it a storefront, and it is also its weakness —
it cannot earn a cent until the platform both approves the listing *and* can
physically pay you.

Status: running. 8 products, 2 `pending_review`, **$0 earned**.

---

## Factory 3 — **THE COMMONS**

> *Ungated public artefact, zero-friction delivery, voluntary payment.*

| | |
|---|---|
| Asset | Developer datasets + stdlib-only tools |
| Lives at | GitHub repo + Hugging Face dataset |
| **Delivery** | **`git clone`, `raw.githubusercontent.com`, or `datasets.load_dataset()` — no checkout, no login, no gate** |
| Money | **Lightning zaps + FUNDING.yml sponsor button** |
| Gate | None. Public domain (CC0) from the moment it exists |
| Approval needed | **None.** Anyone can publish to GitHub and HF today |

**The defining property:** the asset is *given away completely*, and payment is
voluntary and detached from delivery. Nobody can decline you, review you, or
fail to pay you — because nobody stands between the asset and the user.

This is the inverse of the storefront, and under sanctions it is strictly
stronger: it converts reputation into money without a payment processor ever
being involved.

Status: running, **distribution LIVE**. 2 datasets published and announced
across 7 channels each.

*(Factory 2 — **THE BROKER**, affiliate content — was built, verified, and
shut down. It depended on being *accepted* by affiliate programmes, which is a
third structure: no asset of your own, revenue borrowed from someone else's.)*

---

## Delivery, side by side

This is the distinction that was missing from earlier write-ups:

```
STOREFRONT   asset → [ paywall ] → checkout → platform grants → buyer
                        ↑ can be blocked, reviewed, or unpayable

COMMONS      asset → public URL → user          money ← zap (separate path)
                        ↑ nothing in the way     ↑ voluntary, unblockable
```

The storefront couples delivery to payment. The commons decouples them. Under
sanctions, coupling is the liability.

---

## What Factory 4 should be

Given the goal — *most money, shortest time, autonomous* — the honest
constraint is that **reach is the bottleneck, not production**. F1 and F3
already produce more than ~27 followers can absorb.

So Factory 4 should not be a fourth asset type competing for the same eyeballs.
It should be the missing structure:

### **THE UTILITY** — a free hosted tool that runs on the Worker

| | |
|---|---|
| Asset | A single-purpose web tool people *use repeatedly*, not download once |
| Lives at | Our Cloudflare Worker (already deployed, already free) |
| Delivery | Instant, in-browser, no install |
| Money | Zaps + "powered by" backlinks + an upgrade path later |
| Approval | None |

**Why this and not another content factory:**

1. **Tools get shared; documents get downloaded and forgotten.** A useful tool
   is linked from Stack Overflow answers, README files and Slack threads —
   that is compounding distribution we cannot buy.
2. **It reuses infrastructure that already exists and costs nothing.** The
   Worker already serves `/p/`, `/a/`, sitemap and RSS.
3. **Repeat usage is the thing we have zero of.** F1 and F3 assets are consumed
   once. A tool brings the same person back, which is the only way 27
   followers becomes 270.
4. **It feeds the other factories.** Every F3 dataset can have a matching
   browser tool; every tool page can link the dataset.

Candidate first tool: a **prompt-injection tester** — paste a prompt, get it
checked against the F3 adversarial dataset we already publish. It uses our own
asset, targets the audience we are already reaching, and needs no new keys.

### What I would explicitly not build

- **A fourth content factory.** More output into the same 27 followers earns
  the same $0.
- **Anything needing marketplace approval.** F1 already blocks on that.
- **Anything needing an affiliate acceptance.** F2 was shut down for exactly
  that dependency.
