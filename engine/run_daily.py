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
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
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
        built = generate_pack.build_pack_dir(topic, pack, links, OUT / "packs")
        slug, d = built["slug"], built["dir"]

        # package: md -> html/pdf/docx/zip
        title = slug
        artifacts = packaging.pack_all(str(d), title, str(OUT / "deliverables"))

        # promo images
        images = []
        ip = pack.get("upsell", {}).get("pro_teaser", pack["subtitle"])
        prompts = [
            f"Minimal flat cover art for an AI prompt pack titled '{pack['title']}'. "
            "Bold typography, dark background, one accent color, no clutter.",
            f"Square social graphic advertising '{pack['title']}'. Modern SaaS style, "
            f"product mockup, text '{pack['subtitle']}'.",
        ][:N_IMAGES]
        for pi, p in enumerate(prompts):
            try:
                images.append(str(media.gen_image(p, f"{slug}-{pi}")))
            except Exception as e:
                print(f"[daily] image failed: {e}")

        # slideshow video
        video = None
        if MAKE_VIDEO and images:
            try:
                narration = (f"{pack['title']}. {pack['subtitle']}. "
                             "Get the free pack now — link below.")
                video = str(media.slideshow_video(
                    [Path(i) for i in images], narration, slug, duration_per=3.0))
            except Exception as e:
                print(f"[daily] video failed: {e}")

        # description (product page)
        description = (f"{pack['description']}\n\n"
                       f"📦 {len(pack['prompts'])} copy-paste prompts, "
                       f"{len(pack['skills'])} step-by-step skills with code.")

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

        # upload video too (used by content engine later)
        video_url = None
        if video and not DRY:
            try:
                video_url = hosting.upload_video(slug, Path(video))
                print(f"[daily] video hosted: {video_url}")
            except Exception as e:
                print(f"[daily] video upload failed: {e}")

        res = publish.publish_asset(pack, slug, file_urls, image_urls, description)

        # record for content engine
        topics.record_asset(slug, pack["title"], topic, pack.get("category"),
                            extra={"video_url": video_url, "free": is_free,
                                   "status": res.get("status", "live" if is_free else "pending_approval"),
                                   "price": res.get("price", 0.0)})
        if res.get("page_url"):
            mf = ROOT / "state" / "manifest.json"
            man = json.loads(mf.read_text())
            for a in man["assets"]:
                if a["slug"] == slug:
                    a["page_url"] = res["page_url"]
                    if "status" in res:
                        a["status"] = res["status"]
            mf.write_text(json.dumps(man, indent=2))
        return res
    except Exception as e:
        print(f"[daily] ASSET FAILED: {e}\n{traceback.format_exc()}")
        return None


def main():
    print(f"[daily] MOCK={MOCK} DRY={DRY} free={N_FREE} paid={N_PAID}")
    picks = topics.pick_daily(n_free=N_FREE, n_paid=N_PAID)
    print(f"[daily] topics: {json.dumps(picks, indent=2)}")
    results = []
    for i, item in enumerate(picks):
        r = one_asset(item, i)
        if r:
            results.append(r)
    summary = ROOT / "out" / "daily_summary.json"
    summary.parent.mkdir(exist_ok=True)
    summary.write_text(json.dumps({"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                                   "results": results}, indent=2, default=str))
    print(f"\n[daily] done. {len(results)}/{len(picks)} assets. summary: {summary}")


if __name__ == "__main__":
    main()
