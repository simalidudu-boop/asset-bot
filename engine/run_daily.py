"""
run_daily.py — Phases A+B of the production cycle.

1. Pick today's topics (1 free + 2 paid), deduped.
2. Per topic: generate pack -> package (md/html/pdf/docx/zip) -> promo
   images + slideshow video -> publish (free auto / paid review Issue).
3. Update state/manifest.json for the content engine.

Usage: python3 engine/run_daily.py [--mock] [--dry-run] [--assets-only]
"""
import json
import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import preflight  # noqa: E402
import qc  # noqa: E402
import resilience as rz  # noqa: E402
import topics  # noqa: E402
import generate_pack  # noqa: E402
import packaging  # noqa: E402
import publish  # noqa: E402
import media  # noqa: E402
import hosting  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
MOCK = "--mock" in sys.argv or os.environ.get("MOCK") == "1"
DRY = "--dry-run" in sys.argv or os.environ.get("DRY_RUN") == "1"
os.environ["MOCK"] = os.environ.get("MOCK", "1" if MOCK else "0")
os.environ["DRY_RUN"] = os.environ.get("DRY_RUN", "1" if DRY else "0")

N_FREE = int(os.environ.get("N_FREE", "1"))
N_PAID = int(os.environ.get("N_PAID", "2"))
N_IMAGES = int(os.environ.get("N_IMAGES", "2"))
MAKE_VIDEO = os.environ.get("MAKE_VIDEO", "1") == "1"
FREE_ASSET_LINK = os.environ.get("FREE_ASSET_LINK", "")


# Distinct art per asset. The old version used two fixed templates, so every
# pack came out looking the same: dark navy, one accent, centred bold type.
# We vary the *visual treatment* deterministically per slug (so a given asset
# is stable across reruns) and feed in the topic/category, not just the title.
# Abstract/graphic styles only. Anything evoking characters or scenes (e.g.
# "neon cyberpunk") makes the model produce portraits, which are useless as
# product covers — verified: it returned an anime face.
_STYLES = [
    ("isometric 3d illustration", "deep indigo and coral", "floating geometric shapes and cubes"),
    ("flat vector illustration", "forest green and warm cream", "layered paper-cutout depth"),
    ("editorial graphic collage", "black, white and one electric yellow", "torn-paper texture"),
    ("soft gradient mesh abstract", "sunset orange to violet", "translucent glassmorphic cards"),
    ("technical blueprint diagram", "cyan lines on dark slate", "thin grid lines and callouts"),
    ("bold retro geometric poster", "mustard, brick red and off-white", "chunky 70s shapes"),
    ("minimal product still life", "muted greys with one teal accent", "soft studio shadows on plain objects"),
    ("abstract data visualisation", "deep blue with lime accents", "flowing nodes and connecting lines"),
]


def _image_prompts(pack: dict, slug: str) -> list[str]:
    """Two visually different prompts, varied per asset."""
    import hashlib
    h = int(hashlib.sha256(slug.encode()).hexdigest(), 16)
    style, palette, motif = _STYLES[h % len(_STYLES)]
    alt, alt_pal, alt_motif = _STYLES[(h // 7 + 3) % len(_STYLES)]
    topic = pack.get("topic") or pack.get("category") or "AI productivity"
    subject = pack.get("audience") or "creators"

    return [
        f"{style}, abstract conceptual cover art representing {topic}. "
        f"Colour palette: {palette}. Featuring {motif}. No people, no faces, "
        f"no characters. No text, no lettering, no words. Square, clean, "
        f"generous negative space, professional business aesthetic.",

        f"{alt}, abstract graphic representing {topic} for {subject}. "
        f"Colour palette: {alt_pal}. Featuring {alt_motif}. No people, no "
        f"faces. No text or typography. Square, striking, high contrast, "
        f"professional business aesthetic.",
    ]


def one_asset(item: dict, idx: int) -> dict | None:
    topic = item["topic"]
    is_free = item["free"]
    print(f"\n=== asset {idx}: {topic} ({'FREE' if is_free else 'PAID'}) ===")
    try:
        pack = generate_pack.generate(topic, mock=MOCK)
        pack["free"] = is_free
        links = {}
        if is_free and FREE_ASSET_LINK:
            links["free"] = FREE_ASSET_LINK
        # QC gate: block broken packs BEFORE they reach a customer.
        # NOTE: the canonical slug is assigned later by topics.record_asset(),
        # so derive a label here purely for logging.
        qc_label = generate_pack.slugify(pack.get("title") or topic)
        # MOCK packs are deliberately tiny fixtures — gate them non-strictly
        # so a dry run still exercises the whole pipeline.
        if not qc.gate(pack, qc_label, paid=not item.get("free", True),
                       strict=(not MOCK
                               and os.environ.get("QC_STRICT", "1") != "0")):
            print(f"[daily] {qc_label}: BLOCKED by QC — not publishing")
            rz.alert(f"QC blocked asset: {qc_label}",
                     "Pack failed quality gate; see run log for the field-level "
                     "errors.", level="warn", dedupe=f"qc:{qc_label}")
            return None

        built = generate_pack.build_pack_dir(topic, pack, links, OUT / "packs")
        slug, d = built["slug"], built["dir"]

        # package: md -> html/pdf/docx/zip
        title = slug
        artifacts = packaging.pack_all(str(d), title, str(OUT / "deliverables"))

        # promo images
        images = []
        prompts = _image_prompts(pack, slug)[:N_IMAGES]
        for pi, p in enumerate(prompts):
            try:
                images.append(str(media.gen_image(p, f"{slug}-{pi}")))
            except Exception as e:
                print(f"[daily] image failed: {e}")

        # slideshow video. Prefer the server-side renderer: the local path
        # needs ffmpeg, which is one CI apt-get failure away from silently
        # killing video for every asset. Falls back to ffmpeg automatically.
        video = None
        video_url = None
        if MAKE_VIDEO and images:
            narration = (f"{pack['title']}. {pack['subtitle']}. "
                         "Get the free pack now — link below.")
            if os.environ.get("JSON2VIDEO_API_KEY"):
                try:
                    # the renderer fetches these, so they must be public
                    pub = hosting.upload_images(slug, [Path(i) for i in images])
                    if pub:
                        video_url = media.json2video_slideshow(
                            pub, pack["title"], pack.get("subtitle", ""),
                            narration)
                except Exception as e:
                    print(f"[daily] json2video failed ({e}) — trying ffmpeg")
                    rz.alert("Video: JSON2Video failed, falling back to ffmpeg",
                             f"`{e}`", level="warn", dedupe="j2v-fallback")
            if not video_url:
                try:
                    video = str(media.slideshow_video(
                        [Path(i) for i in images], narration, slug,
                        duration_per=3.0))
                except Exception as e:
                    print(f"[daily] video failed: {e}")
                    rz.alert("Video generation failed (both renderers)",
                             f"`{e}` — asset ships without video.",
                             level="warn", dedupe="video-dead")

        # description (product page)
        description = (f"{pack['description']}\n\n"
                       f"📦 {len(pack['prompts'])} copy-paste prompts, "
                       f"{len(pack.get('skills') or [])} step-by-step skills with code.")

        # hosting: GitHub Releases = free public CDN (no R2/card needed)
        deliverable_paths = [Path(v) for k, v in artifacts.items()
                             if k in ("pdf", "docx", "zip", "html")]
        if not DRY:
            file_urls = hosting.upload_files(slug, deliverable_paths)
            image_urls = hosting.upload_images(slug, [Path(i) for i in images])
        else:
            file_urls = [{"name": p.name, "url": f"(dry)/{slug}/{p.name}"}
                         for p in deliverable_paths]
            image_urls = images

        # upload video too (used by content engine later).
        # NOTE: do NOT reset video_url here — json2video may already have set
        # it, and re-initialising would silently discard the rendered URL.
        if video and not video_url and not DRY:
            try:
                video_url = hosting.upload_video(slug, Path(video))
                print(f"[daily] video hosted: {video_url}")
            except Exception as e:
                print(f"[daily] video upload failed: {e}")

        # local_files lets paid deliverables be uploaded to Whop privately
        # instead of served from public GitHub Releases.
        res = publish.publish_asset(pack, slug, file_urls, image_urls,
                                    description,
                                    local_files=[str(x) for x in deliverable_paths])

        # record for content engine — persist free/price/product_id/status so
        # pick_assets() and the dashboard stop guessing (see audit P3)
        slug = topics.record_asset(
            slug, pack["title"], topic, pack.get("category"),
            free=bool(is_free),
            price=res.get("price"),
            product_id=res.get("product_id"),
            status=res.get("status", "staged"),
            extra={"video_url": video_url,
                   "cover_status": res.get("cover_status"),
                   "gallery_images": res.get("gallery_images") or [],
                   "marketplace_status": res.get("marketplace_status"),
                   "faq": pack.get("faq") or []})
        if res.get("page_url"):
            mf = ROOT / "state" / "manifest.json"
            man = json.loads(mf.read_text())
            for a in man["assets"]:
                if a["slug"] == slug:
                    a["page_url"] = res["page_url"]
            mf.write_text(json.dumps(man, indent=2))
        return res
    except Exception as e:
        print(f"[daily] ASSET FAILED: {e}\n{traceback.format_exc()}")
        # Was a silent log line — the 0/3 outage went unnoticed for a day.
        rz.alert(f"Asset generation failed: {str(item.get('topic', '?'))[:60]}",
                 f"`{type(e).__name__}: {e}`\n```\n"
                 f"{traceback.format_exc()[-1000:]}\n```",
                 level="error", dedupe=f"asset:{type(e).__name__}")
        return None


def main():
    print(f"[daily] MOCK={MOCK} DRY={DRY} free={N_FREE} paid={N_PAID}")
    preflight.check("daily")
    picks = topics.pick_daily(n_free=N_FREE, n_paid=N_PAID)
    print(f"[daily] topics: {json.dumps(picks, indent=2)}")
    results = []
    for i, item in enumerate(picks):
        r = one_asset(item, i)
        if r:
            results.append(r)
    # Fail loudly on a silent no-op run (see qc.check_run docstring).
    qc.check_run(len(results), len(picks), phase="daily")

    # Chase up listings still in Whop's MANUAL review queue. Submission is
    # autonomous; the review is not, and GET never returns the status — so
    # without this poll the manifest says pending_review forever.
    try:
        import marketplace as _mk
        _mk.poll_marketplace_status()
    except Exception as e:  # noqa: BLE001
        print(f"[daily] marketplace poll skipped: {e}")

    summary = ROOT / "out" / "daily_summary.json"
    summary.parent.mkdir(exist_ok=True)
    summary.write_text(json.dumps({"date": os.popen("date -u +%Y-%m-%d").read().strip(),
                                   "results": results}, indent=2, default=str))
    print(f"\n[daily] done. {len(results)}/{len(picks)} assets. summary: {summary}")
    from datetime import datetime, timezone
    hb = ROOT / "state" / "heartbeat.json"
    try:
        data = json.loads(hb.read_text()) if hb.exists() else {}
    except Exception:
        data = {}
    data["daily"] = {"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "count": len(results),
                     "run_id": os.environ.get("GITHUB_RUN_ID", "local")}
    hb.write_text(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
