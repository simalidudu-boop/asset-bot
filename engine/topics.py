"""
topics.py — topic engine.

Sources: seed topics (topics/seed_topics.md) + bot-suggested topics (LLM).
Selection: Cohere rerank for relevance-vs-dedupe (fallback: Mistral embed
cosine). Persists a JSON index of used topics in state/topics_index.json so
the bot never repeats itself.
"""
import json
import math
import os
import re
from datetime import datetime, timezone
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import textgen  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"
STATE.mkdir(exist_ok=True)
INDEX = STATE / "topics_index.json"
SEEDS = ROOT / "topics" / "seed_topics.md"


def load_seeds() -> list[str]:
    if not SEEDS.exists():
        return []
    return [l.strip("- ").strip() for l in SEEDS.read_text().splitlines()
            if l.strip().startswith("-")]


def suggest(n: int = 5) -> list[str]:
    """Bot-suggested trending topics in the AI niche."""
    try:
        msgs = [{"role": "user",
                 "content": f"Suggest {n} high-demand topics for sellable AI prompt packs "
                            "in 2026. One topic per line, no numbering, no explanation. "
                            "Focus on practical, evergreen, monetisable skills."}]
        text = textgen.chat(msgs, max_tokens=300, temperature=0.9)[0]
        return [t.strip("- ").strip() for t in text.splitlines()
                if t.strip() and len(t) > 5][:n]
    except Exception as e:
        print(f"[topics] suggestion failed ({e}) — seeds only")
        return []


# ---------------- embedding helpers ----------------
def _cohere_embed(texts: list[str]) -> list[list[float]]:
    key = os.environ.get("COHERE_API_KEY")
    if not key:
        raise RuntimeError("no cohere key")
    req = urllib.request.Request(
        "https://api.cohere.com/v1/embed",
        data=json.dumps({"texts": texts, "model": "embed-english-v3.0",
                         "input_type": "search_document"}).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())["embeddings"]


def _mistral_embed(texts: list[str]) -> list[list[float]]:
    key = os.environ.get("MISTRAL_API_KEY")
    if not key:
        raise RuntimeError("no mistral key")
    req = urllib.request.Request(
        "https://api.mistral.ai/v1/embeddings",
        data=json.dumps({"model": "mistral-embed", "inputs": texts}).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return [d["embedding"] for d in json.loads(r.read())["data"]]


def embed(texts: list[str]) -> list[list[float]]:
    for name, fn in (("cohere", _cohere_embed), ("mistral", _mistral_embed)):
        try:
            return fn(texts)
        except Exception as e:
            print(f"[topics] {name} embed failed: {e}")
    return []


def _cos(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _load_index() -> dict:
    if INDEX.exists():
        return json.loads(INDEX.read_text())
    return {"used": [], "vectors": {}}


def _save_index(idx: dict):
    INDEX.write_text(json.dumps(idx, indent=2))


def is_dup(topic: str, threshold: float = 0.85) -> bool:
    idx = _load_index()
    used_texts = idx["used"]
    # cheap first pass: exact/near-exact match
    norm = re.sub(r"[^a-z0-9]+", "", topic.lower())
    for u in used_texts:
        if re.sub(r"[^a-z0-9]+", "", u.lower())[:30] == norm[:30]:
            return True
    if not used_texts:
        return False
    # reuse cached vectors for already-used topics; only embed what's new
    # (the 'vectors' cache was never populated before — audit P14)
    cache = idx.setdefault("vectors", {})
    missing = [t for t in used_texts if t not in cache]
    to_embed = [topic] + missing
    vecs = embed(to_embed)
    if not vecs:
        print("[topics] no embedder available — skipping semantic dedupe")
        return False
    topic_vec = vecs[0]
    for t, v in zip(missing, vecs[1:]):
        cache[t] = v
    _save_index(idx)
    used_vecs = [cache[t] for t in used_texts if t in cache]
    if not used_vecs:
        return False
    sim = max(_cos(topic_vec, v) for v in used_vecs)
    print(f"[topics] '{topic}' max similarity vs used: {sim:.3f}")
    return sim >= threshold


def pick_daily(n_free: int = 1, n_paid: int = 2) -> list[dict]:
    """Pick today's topics, avoiding duplicates. Returns
    [{'topic': ..., 'free': bool}, ...]."""
    idx = _load_index()
    candidates = [t for t in load_seeds() if not is_dup(t)] + \
                 [t for t in suggest(8) if not is_dup(t)]
    seen, chosen = set(), []
    for t in candidates:
        if t in seen:
            continue
        seen.add(t)
        chosen.append(t)
        if len(chosen) >= n_free + n_paid:
            break
    if not chosen:  # fallback: allow seeds even if sim-check flagged them
        chosen = load_seeds()[: n_free + n_paid]
    out = [{"topic": t, "free": i < n_free} for i, t in
           enumerate(chosen[: n_free + n_paid])]
    for o in out:
        idx["used"].append(o["topic"])
    _save_index(idx)
    return out


def unique_slug(slug: str, manifest: dict) -> str:
    """Never reuse a slug: append -2, -3 ... so each asset maps to one product."""
    existing = {a.get("slug") for a in manifest.get("assets", [])}
    if slug not in existing:
        return slug
    n = 2
    while f"{slug}-{n}" in existing:
        n += 1
    return f"{slug}-{n}"


def record_asset(slug: str, title: str, topic: str, kind: str,
                 free: bool = False, price: float | None = None,
                 product_id: str | None = None, status: str = "staged",
                 extra: dict | None = None) -> str:
    """Append to the manifest that content.py reads.

    Persists free/price/product_id/status so the content engine and the
    dashboard can tell free from paid and live from pending. Returns the
    (possibly de-duplicated) slug actually recorded.
    """
    mf = STATE / "manifest.json"
    manifest = json.loads(mf.read_text()) if mf.exists() else {"assets": [], "posts": []}
    slug = unique_slug(slug, manifest)
    record = {
        "slug": slug, "title": title, "topic": topic, "kind": kind,
        "free": bool(free),
        "price": price,
        "product_id": product_id,
        "status": status,
        "page_url": "",  # filled by publish.py after creation
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if extra:
        record.update(extra)
    manifest["assets"].append(record)
    mf.write_text(json.dumps(manifest, indent=2))
    return slug
