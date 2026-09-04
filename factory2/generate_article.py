"""Factory 2 generator — Bitcoin/Lightning affiliate content.

Different asset, same machine. Factory 1 makes prompt packs sold on Whop;
Factory 2 makes long-form comparison/guide articles monetised by affiliate
links that pay in Bitcoin — the only rail that reaches the operator.

An article must earn its keep three ways:
  1. genuinely useful to a reader who has never heard of us
  2. carries affiliate links that can actually pay us
  3. carries the Lightning address, so value-for-value works even at 0 clicks
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import affiliates
import textgen

ROOT = Path(__file__).resolve().parent
TOPICS_FILE = ROOT / "state" / "topics_done.json"

# Topic seeds. Each is a real question the Bitcoin audience searches for, and
# each has a natural, non-forced place for an affiliate mention.
SEEDS = [
    "how to accept bitcoin payments as a small business without KYC",
    "lightning network payments explained for merchants",
    "self-custody vs exchange custody: what actually goes wrong",
    "how to receive bitcoin when your country is sanctioned",
    "hardware wallet setup mistakes that lose people money",
    "value-for-value monetisation: how creators earn on Nostr",
    "non-custodial crypto payment gateways compared",
    "lightning address vs BOLT12 offer: which to publish",
    "how to swap crypto without an exchange account",
    "bitcoin on-chain fees vs lightning fees: real numbers",
    "running a bitcoin side business from a restricted country",
    "zaps explained: getting paid in sats for what you publish",
]

SCHEMA = """{
  "title": "specific, search-shaped headline (max 70 chars)",
  "subtitle": "one-line promise",
  "slug": "url-safe-slug",
  "summary": "2-3 sentence standfirst",
  "keywords": ["5", "search", "keywords"],
  "sections": [
    {"heading": "section heading",
     "body": "3-5 substantial paragraphs of genuinely useful prose. No filler."}
  ],
  "comparison": [
    {"name": "tool", "best_for": "who", "note": "one honest line incl. a drawback"}
  ],
  "faq": [{"question": "q", "answer": "a"}],
  "takeaway": "the single most useful sentence for the reader"
}"""


def slugify(t: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (t or "").lower()).strip("-")
    return s[:70] or "article"


def _done() -> set:
    try:
        return set(json.loads(TOPICS_FILE.read_text()))
    except Exception:  # noqa: BLE001
        return set()


def _mark(topic: str) -> None:
    d = _done()
    d.add(topic)
    TOPICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOPICS_FILE.write_text(json.dumps(sorted(d), indent=2))


def pick_topic() -> str:
    """Next unused seed; recycles with a variation once all are used."""
    done = _done()
    for s in SEEDS:
        if s not in done:
            return s
    import time
    return f"{SEEDS[int(time.time()) % len(SEEDS)]} (2026 update)"


def system_prompt(topic: str, progs: list) -> str:
    tools = "\n".join(
        f"- {p['name']} ({p['category']}): {p['why']} Best for: {p['audience']}."
        for p in progs)
    return f"""You are a Bitcoin infrastructure writer. Write a genuinely useful
article about: {topic}

You may naturally reference these tools where they are actually relevant:
{tools}

HARD RULES:
- Be specific and technical. Real numbers, real trade-offs, real failure modes.
- Mention a drawback for every tool you praise. Readers trust balance.
- Never invent statistics, prices or features. If unsure, describe the
  mechanism instead of quoting a figure.
- Do not write marketing copy. No hype, no "game-changer", no "in today's
  fast-paced world".
- 4-6 sections, each 3-5 real paragraphs.
- Never claim the reader can evade sanctions or break the law.

Return ONLY valid JSON in exactly this shape:
{SCHEMA}"""


def generate(topic: str | None = None, mock: bool = False) -> dict:
    topic = topic or pick_topic()
    progs = affiliates.pick(3, seed=topic)

    if mock or os.environ.get("MOCK") == "1":
        art = {
            "title": "How to Accept Bitcoin Payments Without KYC",
            "subtitle": "A practical setup for merchants who cannot use Stripe",
            "slug": "accept-bitcoin-without-kyc",
            "summary": "Card processors decline whole regions. Bitcoin does not. "
                       "Here is a working, non-custodial setup and its real costs.",
            "keywords": ["bitcoin", "payments", "no-kyc", "lightning", "merchant"],
            "sections": [
                {"heading": "Why processors decline you",
                 "body": "Payment processors make risk decisions at the country "
                         "level long before they look at your business. " * 3},
                {"heading": "The non-custodial setup",
                 "body": "A non-custodial gateway never holds your funds. " * 3},
            ],
            "comparison": [{"name": p["name"], "best_for": p["audience"],
                            "note": p["commission"]} for p in progs],
            "faq": [{"question": "Do I need KYC?",
                     "answer": "Not with a non-custodial gateway."}],
            "takeaway": "Own the keys, or you do not own the payment.",
        }
    else:
        art = textgen.get_json(
            [{"role": "system", "content": system_prompt(topic, progs)},
             {"role": "user", "content": f"Write the article on: {topic}"}],
            max_tokens=8000, quality=True)

    art.setdefault("sections", [])
    art.setdefault("faq", [])
    art.setdefault("comparison", [])
    art.setdefault("keywords", [])
    art["topic"] = topic
    art["slug"] = slugify(art.get("slug") or art.get("title") or topic)
    art["programmes"] = [
        {**p, "link": affiliates.link_for(p)} for p in progs]
    return art


def render_markdown(a: dict) -> str:
    """Article body. Affiliate links are disclosed — always."""
    L = [f"# {a.get('title','Untitled')}\n"]
    if a.get("subtitle"):
        L.append(f"**{a['subtitle']}**\n")
    if a.get("summary"):
        L.append(a["summary"] + "\n")

    for s in a.get("sections", []):
        L.append(f"## {s.get('heading','')}\n")
        L.append(s.get("body", "") + "\n")

    if a.get("comparison"):
        L.append("## At a glance\n")
        L.append("| Tool | Best for | Notes |")
        L.append("|---|---|---|")
        for c in a["comparison"]:
            L.append(f"| {c.get('name','')} | {c.get('best_for','')} | "
                     f"{c.get('note','')} |")
        L.append("")

    if a.get("programmes"):
        L.append("## Tools mentioned\n")
        for p in a["programmes"]:
            L.append(f"- **[{p['name']}]({p['link']})** — {p['why']}")
        L.append("")

    if a.get("faq"):
        L.append("## FAQ\n")
        for f in a["faq"]:
            L.append(f"**{f.get('question','')}**\n")
            L.append(f"{f.get('answer','')}\n")

    if a.get("takeaway"):
        L.append(f"> {a['takeaway']}\n")

    # Disclosure is non-negotiable: undisclosed affiliate links breach FTC
    # guidance and most platforms' terms, and would get us removed.
    if a.get("programmes"):
        L.append("---\n")
        L.append("*Some links above are affiliate links. They cost you nothing "
                 "extra and I only list tools I would use myself.*\n")

    ln = os.environ.get("LIGHTNING_ADDRESS", "").strip()
    if ln and "@" in ln:
        L.append(f"*Found this useful? Zap it: `{ln}`*\n")

    return "\n".join(L)


if __name__ == "__main__":  # pragma: no cover
    a = generate(mock=os.environ.get("MOCK") == "1")
    print(json.dumps({k: v for k, v in a.items() if k != "sections"}, indent=2)[:900])
    print("\n---\n")
    print(render_markdown(a)[:900])
