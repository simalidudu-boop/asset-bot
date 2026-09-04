# Factory 2 — Bitcoin/Lightning affiliate content

**Standalone.** Own state, own queue, own manifest, own copy of the
infrastructure. Shares nothing with Factory 1 (`engine/`) — you can break,
rewrite or delete either without touching the other.

## Why this exists

Factory 1 sells prompt packs on Whop. Under OFAC sanctions Whop's payout to
Iran is unverified, so Factory 1's revenue is uncertain by construction.

Factory 2 monetises differently: **affiliate commissions paid in Bitcoin over
Lightning**. Every programme in `affiliates.py` was selected on one criterion —
*can it pay a sanctioned-country affiliate?* The audience (Bitcoin/Nostr) and
the money rail (Lightning) are the same ecosystem, which is the whole point.

## Flow

```
pick topic -> generate article (LLM) -> QC gate -> render markdown
           -> enqueue -> 22 channels -> drain
```

## Files

| File | Role |
|---|---|
| `affiliates.py` | Programme registry + referral-link builder |
| `generate_article.py` | Topic seeds, article schema, markdown renderer |
| `qc_article.py` | Article quality gate (thin/hype/unsafe/leakage) |
| `run_factory2.py` | Runner |
| `dist_*.py`, `resilience.py`, `textgen.py`, … | Own copies of the shared infra |

## QC differs from Factory 1

Prompt counts are meaningless here. Articles are blocked for:

- fewer than 3 sections, or any section under 400 chars
- under 2,000 chars overall
- a paragraph repeated to pad length
- model leakage (`"As an AI"`, `lorem ipsum`, `{{placeholder}}`)
- 3+ hype phrases (`game-changer`, `revolutionize`, `delve into`)
- **unsafe claims** — anything about evading sanctions is blocked outright

## Money

`AFFILIATE_IDS` is JSON: `{"amboss":"yourref","trezor":"yourref"}`.
Programmes without an id are written about **without a link** rather than with
a fabricated one. Affiliate disclosure is appended automatically — undisclosed
links breach FTC guidance and most platforms' terms.

The Lightning address is appended to every article, so value-for-value works
even at zero affiliate clicks.

## Keys

Uses Factory 1's keys by default. Override any of them per-factory with an
`F2_` prefix (`F2_DEVTO_API_KEY`, `F2_BSKY_HANDLE`, `F2_NOSTR_NSEC`,
`F2_DIST_POSTING_MODE`, …) as you create separate accounts.

**Defaults to `DRAFT`** — nothing posts until `F2_DIST_POSTING_MODE=LIVE`.

## Run

```bash
cd factory2
MOCK=1 DRY_RUN=1 python3 run_factory2.py    # safe local test
python3 dist_core.py status                  # factory 2's own queue
```

Schedule: `35 9 * * *`, clear of Factory 1's 06:20 slot.
