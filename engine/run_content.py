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
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import content  # noqa: E402
import preflight  # noqa: E402
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
    # only promote assets that are explicitly free AND actually reachable —
    # an asset with no product_id/page_url was never published (audit P3/P4)
    free = [a for a in assets
            if a.get("free") is True and (a.get("page_url") or a.get("product_id"))]
    if not free:
        print("[content] no published free assets to promote — skipping run")
        return []
    ptr = STATE / "roundrobin.txt"
    idx = int(ptr.read_text().strip()) if ptr.exists() else 0
    chosen = [free[(idx + i) % len(free)] for i in range(min(n, len(free)))]
    ptr.write_text(str((idx + n) % len(free)))
    return chosen


def asset_link(a: dict) -> str:
    """Resolve the asset's public page. Only ever returns a URL we believe
    exists; callers must not fabricate one from a slug (audit P4)."""
    if a.get("page_url"):
        return a["page_url"].rstrip("/")
    base = os.environ.get("PRODUCT_PAGE_BASE", "").rstrip("/")
    if base and a.get("product_id"):
        return f"{base}/{a['slug']}"
    return ""



def attach_media(piece: dict, slug: str) -> str | None:
    """Generate + host a promo image for image/video pieces.

    Whop forum posts render a bare image URL as an embed, so hosting the file
    on GitHub Releases (our free CDN) and appending the URL is enough — no
    direct_upload handshake required.

    Returns the public URL, or None when media is unavailable/not wanted.
    Never raises: a missing image must not lose the post.
    """
    if os.environ.get("ENABLE_POST_MEDIA", "1") not in ("1", "true", "True"):
        return None
    if piece.get("fmt") not in ("image", "video"):
        return None
    if MOCK or DRY:
        print(f"[content] media skipped (mock/dry) for fmt={piece.get('fmt')}")
        return None
    prompt = (piece.get("image_prompt") or "").strip()
    if not prompt:
        # Vary the fallback too — the old fixed template made every text-less
        # post look identical. Seeded on slug+title so it is stable per post.
        import hashlib
        styles = [
            ("isometric 3d render", "deep indigo and coral"),
            ("flat vector illustration", "forest green and warm cream"),
            ("editorial collage", "black, white and electric yellow"),
            ("soft gradient mesh", "sunset orange to violet"),
            ("technical blueprint", "cyan on dark slate"),
            ("bold retro poster", "mustard, brick red and off-white"),
        ]
        seed = f"{slug}{piece.get('title','')}"
        st, pal = styles[int(hashlib.sha256(seed.encode()).hexdigest(), 16) % len(styles)]
        prompt = (f"{st} promo graphic about {piece.get('title', slug)}. "
                  f"Colour palette: {pal}. No text or lettering anywhere. "
                  f"Square, high contrast, generous negative space.")
    # Image models reliably mangle rendered words (observed: "AICCHIMICTSKOA"),
    # so suppress typography unless the piece explicitly asked for it.
    if "text" not in prompt.lower():
        prompt += " No text, no words, no lettering."
    try:
        import media  # local import: heavy deps only when actually needed
        import hosting
        from pathlib import Path as _P
        name = f"post-{slug}-{int(time.time())}"
        img = media.gen_image(prompt, name)
        url = hosting.upload_images(slug, [_P(str(img))])
        if url:
            print(f"[content] media hosted: {url[0]}")
            return url[0]
    except Exception as e:
        print(f"[content] media generation failed ({e}) — posting text-only")
    return None


def _drain_distribution():
    """Drain the distribution queue. Runs on the 3-hourly content cadence."""
    try:
        import dist_core
        import dist_channels  # noqa: F401
        return dist_core.drain()
    except Exception as e:  # noqa: BLE001
        print(f"[dist] drain skipped: {e}")
        return {}


def _heartbeat(phase: str, count: int):
    """Write a run receipt so the dashboard can detect a stalled cron."""
    from datetime import datetime, timezone
    hb = STATE / "heartbeat.json"
    try:
        data = json.loads(hb.read_text()) if hb.exists() else {}
    except Exception:
        data = {}
    data[phase] = {"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "count": count,
                   "run_id": os.environ.get("GITHUB_RUN_ID", "local")}
    hb.write_text(json.dumps(data, indent=2))


def main():
    print(f"[content] MOCK={MOCK} DRY={DRY} n={N} langs={LANGS}")
    preflight.check("content")
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
        # rotate formats ACROSS runs (N_POSTS=1 means within-run index is
        # always 0, so every post was 'text' — audit P7)
        fmt_ptr = STATE / "fmt_rotation.txt"
        try:
            fmt_idx = int(fmt_ptr.read_text().strip())
        except Exception:
            fmt_idx = 0
        pieces = content.content_set(a, upsell, link, n=1, lang=lang,
                                     start_index=fmt_idx)
        fmt_ptr.write_text(str((fmt_idx + 1) % len(content.FORMATS)))
        for p in pieces:
            media_url = attach_media(p, a["slug"])
            results.append(post.post_piece(p, media_url=media_url))
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
    _drain_distribution()
    _heartbeat("content", len(results))


if __name__ == "__main__":
    main()
