"""
run_content.py — Phase C of the production cycle (content + posting).

Picks free assets from state/manifest.json (round-robin so every asset gets
promoted), generates 2-4 pieces (rotating formats/languages), attaches media
when available, and posts variant A to the public space + variant B to your
own forum.

Usage: python3 engine/run_content.py [--mock] [--dry-run] [--n 3]
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import content  # noqa: E402
import post  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"
MOCK = "--mock" in sys.argv or os.environ.get("MOCK") == "1"
DRY = "--dry-run" in sys.argv or os.environ.get("DRY_RUN") == "1"
os.environ["MOCK"] = os.environ.get("MOCK", "1" if MOCK else "0")
os.environ["DRY_RUN"] = os.environ.get("DRY_RUN", "1" if DRY else "0")

N = int(os.environ.get("N_POSTS", "3"))
LANGS = os.environ.get("POST_LANGS", "en")  # e.g. "en,fr,es"


def pick_assets(n: int) -> list[dict]:
    mf = STATE / "manifest.json"
    if not mf.exists():
        print("[content] no manifest — nothing to promote")
        return []
    man = json.loads(mf.read_text())
    assets = man.get("assets", [])
    free = [a for a in assets if a.get("free", True)]
    if not free:
        free = assets
    ptr = STATE / "roundrobin.txt"
    idx = int(ptr.read_text().strip()) if ptr.exists() else 0
    chosen = [free[(idx + i) % len(free)] for i in range(min(n, len(free)))]
    ptr.write_text(str((idx + n) % len(free)))
    return chosen


def asset_link(a: dict) -> str:
    if a.get("page_url"):
        return a["page_url"]
    base = os.environ.get("PRODUCT_PAGE_BASE", "").rstrip("/")
    return f"{base}/{a['slug']}" if base else f"{a['slug']}"


def main():
    print(f"[content] MOCK={MOCK} DRY={DRY} n={N} langs={LANGS}")
    assets = pick_assets(N)
    if not assets:
        return
    results = []
    langs = [l.strip() for l in LANGS.split(",") if l.strip()]
    for i, a in enumerate(assets):
        lang = langs[i % len(langs)]
        link = asset_link(a)
        upsell = {"pro_teaser": f"Pro version of {a['title']}: 3x the prompts, "
                                f"video walkthrough, private templates."}
        pieces = content.content_set(a, upsell, link, n=1, lang=lang)
        for p in pieces:
            results.append(post.post_piece(p))
            # persist what we posted (for dedupe/tracking)
            mf = STATE / "manifest.json"
            man = json.loads(mf.read_text())
            man.setdefault("posts", []).append({
                "asset": a["slug"], "fmt": p["fmt"], "lang": lang,
                "title": p["title"],
                "at": os.popen("date -u +%Y-%m-%dT%H:%M:%SZ").read().strip(),
            })
            mf.write_text(json.dumps(man, indent=2))
    print(f"[content] done — {len(results)} posts attempted")


if __name__ == "__main__":
    main()
