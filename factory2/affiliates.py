"""Affiliate programme registry — the products Factory 2 writes about.

Why these and not the obvious big names
---------------------------------------
The operator is in Iran under OFAC sanctions. Most affiliate networks pay via
PayPal, Stripe or bank transfer, none of which can pay out. The programmes
here were chosen on ONE criterion above all others:

    **Can it pay a sanctioned-country affiliate?**

Bitcoin/Lightning payouts are the only reliable answer, which is also why this
factory targets the Bitcoin audience — the money rail and the readership are
the same ecosystem.

`payout` values:
  lightning  — paid in BTC over Lightning. Best case: instant, no bank.
  btc        — paid in on-chain BTC.
  crypto     — paid in crypto, usually exchange-custodied (weaker).
  fiat       — cannot pay us. Kept only for honest comparison articles.

Set `AFFILIATE_IDS` as JSON (`{"amboss":"myref", ...}`) to inject real
referral codes; anything without an id is written about WITHOUT a link rather
than with a fake one.
"""
from __future__ import annotations

import json
import os

PROGRAMMES = [
    {
        "key": "amboss",
        "name": "Amboss Payments",
        "url": "https://amboss.tech",
        "category": "lightning-payments",
        "commission": "15% of platform fees for 12 months (20% above $1M/30d volume)",
        "payout": "lightning",
        "recurring": True,
        "why": "Merchant Lightning payments with settlement in BTC/USDT/USDC at "
               "a flat 0.5% fee. Commissions paid in bitcoin over Lightning, "
               "claimable at any amount at any time.",
        "audience": "merchants, PSPs, Lightning integrators",
    },
    {
        "key": "bitbo",
        "name": "Bitbo Pro",
        "url": "https://bitbo.io",
        "category": "analytics",
        "commission": "40-50% recurring for 12 months",
        "payout": "btc",
        "recurring": True,
        "why": "Bitcoin charts, on-chain data and alerts. High recurring rate "
               "and the audience overlaps almost perfectly with Nostr.",
        "audience": "bitcoin analysts, traders",
    },
    {
        "key": "trezor",
        "name": "Trezor",
        "url": "https://trezor.io",
        "category": "hardware-wallet",
        "commission": "12-15% per sale",
        "payout": "btc",
        "recurring": False,
        "why": "Open-source hardware wallet. Pays in BTC, ships worldwide, and "
               "self-custody is the single most-recommended purchase in this "
               "niche.",
        "audience": "self-custody advocates, newcomers securing a first stack",
    },
    {
        "key": "coolwallet",
        "name": "CoolWallet",
        "url": "https://coolwallet.io",
        "category": "hardware-wallet",
        "commission": "10%+ per sale",
        "payout": "crypto",
        "recurring": False,
        "why": "Card-format cold wallet. Crypto payout, $200 minimum.",
        "audience": "mobile-first holders",
    },
    {
        "key": "changenow",
        "name": "ChangeNOW",
        "url": "https://changenow.io",
        "category": "exchange",
        "commission": "0.4% of swap volume",
        "payout": "crypto",
        "recurring": True,
        "why": "Non-custodial swaps with no account required. Pays anytime in "
               "11+ currencies — unusually accessible for restricted regions.",
        "audience": "privacy-conscious swappers",
    },
    {
        "key": "blockbee",
        "name": "BlockBee",
        "url": "https://blockbee.io",
        "category": "payment-gateway",
        "commission": "20% revenue share",
        "payout": "crypto",
        "recurring": True,
        "why": "No-KYC crypto payment gateway at 0.25% fees, 12+ coins, "
               "non-custodial so funds never sit with a third party.",
        "audience": "developers, e-commerce operators",
    },
    {
        "key": "coinremitter",
        "name": "Coinremitter",
        "url": "https://coinremitter.com",
        "category": "payment-gateway",
        "commission": "30% revenue share on transaction fees",
        "payout": "crypto",
        "recurring": True,
        "why": "No-KYC gateway, 0.23% fee — the lowest in the category — with "
               "invoicing and a plugin ecosystem.",
        "audience": "merchants who cannot pass KYC",
    },
]

# Kept deliberately: honest comparisons need the mainstream options, but we
# must never imply we can be paid by them.
CANNOT_PAY_US = ["Coinbase", "Kraken", "Gemini", "Robinhood", "River"]


def _ids() -> dict:
    try:
        return json.loads(os.environ.get("AFFILIATE_IDS", "{}")) or {}
    except Exception:  # noqa: BLE001
        return {}


def link_for(prog: dict) -> str:
    """Referral URL, or the bare URL when no id is configured.

    Never fabricates a referral code — a broken link costs more trust than a
    missed commission.
    """
    rid = _ids().get(prog["key"], "").strip()
    if not rid:
        return prog["url"]
    sep = "&" if "?" in prog["url"] else "?"
    return f"{prog['url']}{sep}ref={rid}"


def payable() -> list:
    """Programmes that can actually pay a sanctioned-country affiliate."""
    return [p for p in PROGRAMMES if p["payout"] in ("lightning", "btc", "crypto")]


def pick(n: int = 3, seed: str = "") -> list:
    """Deterministically rotate through programmes so articles vary."""
    import hashlib
    pool = payable()
    if not pool:
        return []
    h = int(hashlib.sha256((seed or "x").encode()).hexdigest(), 16)
    start = h % len(pool)
    return [pool[(start + i) % len(pool)] for i in range(min(n, len(pool)))]
