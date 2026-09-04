"""Factory 2 runner — Bitcoin/Lightning affiliate content.

Standalone. Shares no state, no manifest and no queue with Factory 1; it only
happens to use the same channel adapters, which it owns its own copy of.

Flow:
    pick topic -> generate article -> QC gate -> render -> host
              -> enqueue to distribution -> drain
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import affiliates  # noqa: E402
import dist_core  # noqa: E402
import dist_channels  # noqa: E402,F401  (registers adapters)
import generate_article  # noqa: E402
import qc_article  # noqa: E402
import resilience as rz  # noqa: E402

STATE = ROOT / "state"
OUT = ROOT / "out"
MANIFEST = STATE / "manifest.json"
MOCK = os.environ.get("MOCK") == "1"
DRY = os.environ.get("DRY_RUN") == "1"
N_ARTICLES = int(os.environ.get("F2_ARTICLES", "1"))
PAGE_BASE = (os.environ.get("F2_PAGE_BASE")
             or os.environ.get("PACK_PAGE_BASE", "")).rstrip("/")


def _manifest() -> dict:
    try:
        return json.loads(MANIFEST.read_text())
    except Exception:  # noqa: BLE001
        return {"articles": []}


def _save(m: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(m, indent=2))


def one_article(i: int) -> dict | None:
    try:
        art = generate_article.generate(mock=MOCK)
        slug = art["slug"]
        print(f"[f2] generated: {slug}")

        if not qc_article.gate(art, slug,
                               strict=(not MOCK
                                       and os.environ.get("QC_STRICT", "1") != "0")):
            print(f"[f2] {slug}: BLOCKED by QC — not publishing")
            rz.alert(f"F2 QC blocked: {slug}",
                     "Article failed the quality gate; see run log.",
                     level="warn", dedupe=f"f2qc:{slug}")
            return None

        md = generate_article.render_markdown(art)
        OUT.mkdir(parents=True, exist_ok=True)
        md_path = OUT / f"{slug}.md"
        md_path.write_text(md)
        print(f"[f2] rendered {len(md)} chars -> {md_path.name}")

        page_url = f"{PAGE_BASE}/a/{slug}" if PAGE_BASE else ""

        if DRY:
            print(f"[f2] DRY — would publish {slug}")
            return {"slug": slug, "title": art["title"], "status": "dry"}

        # Distribute. Articles are free content: nothing is hidden, so unlike
        # Factory 1's paid packs there is no approval gate to respect.
        dist_core.enqueue({
            "slug": slug,
            "title": art["title"],
            "subtitle": art.get("subtitle", ""),
            "description": art.get("summary", ""),
            "keywords": art.get("keywords") or [],
            "faq": art.get("faq") or [],
            "price": 0.0,
            "page_url": page_url,
            "body_markdown": md,
        })

        generate_article._mark(art["topic"])
        return {
            "slug": slug,
            "title": art["title"],
            "topic": art["topic"],
            "page_url": page_url,
            "programmes": [p["key"] for p in art.get("programmes", [])],
            "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "live",
        }
    except Exception as e:  # noqa: BLE001
        print(f"[f2] ARTICLE FAILED: {e}\n{traceback.format_exc()}")
        rz.alert("F2 article generation failed",
                 f"`{type(e).__name__}: {e}`\n```\n"
                 f"{traceback.format_exc()[-900:]}\n```",
                 level="error", dedupe=f"f2asset:{type(e).__name__}")
        return None


def main() -> None:
    print(f"[f2] MOCK={MOCK} DRY={DRY} articles={N_ARTICLES} "
          f"payable_programmes={len(affiliates.payable())}")

    results = []
    for i in range(N_ARTICLES):
        r = one_article(i)
        if r:
            results.append(r)

    if results:
        m = _manifest()
        m.setdefault("articles", []).extend(results)
        _save(m)

    # Same guard as Factory 1: a run that produced nothing must go RED, not
    # green — that failure mode cost Factory 1 a full day of silent downtime.
    if N_ARTICLES and not results:
        rz.alert("FACTORY 2 IDLE — 0 articles produced",
                 f"Attempted {N_ARTICLES}, produced 0.",
                 level="error", dedupe="f2-idle")
        raise SystemExit(f"[f2] produced 0/{N_ARTICLES} articles — failing loudly")

    if not DRY:
        try:
            stats = dist_core.drain()
            print(f"[f2] distribution: {stats}")
        except Exception as e:  # noqa: BLE001
            print(f"[f2] drain skipped: {e}")

    hb = STATE / "heartbeat.json"
    hb.write_text(json.dumps({
        "factory2": {"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "count": len(results),
                     "run_id": os.environ.get("GITHUB_RUN_ID", "local")}}, indent=2))
    print(f"[f2] done. {len(results)}/{N_ARTICLES} articles.")


if __name__ == "__main__":
    main()
