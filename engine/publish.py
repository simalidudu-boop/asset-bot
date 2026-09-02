"""
publish.py — Whop storefront ops.

Flow:
- FREE asset  -> product (visible) + $0 plan, live immediately.
- PAID asset  -> product created HIDDEN (no plan) + review Issue opened.
                 /approve  -> PATCH visible + plan at price (approve_from_issue.py)
                 /reject   -> stays hidden / archived manually.
- Deliverable files are uploaded to GitHub Releases (free public CDN, no
  card required) so the review Issue can link real files and approval needs
  no rebuild. R2 remains an optional later upgrade via upload_to_edge().

Pricing: prompt packs $5-29, skill sets $19-49, custom work $150-1000.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import whop_client as whop
import whop_media
import marketplace  # noqa: E402
import review  # noqa: E402

DRY = os.environ.get("DRY_RUN") == "1" or "--dry-run" in sys.argv
COMPANY_ID = os.environ.get("WHOP_COMPANY_ID", "")
EDGE = os.environ.get("EDGE_URL", "").rstrip("/")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
PRODUCT_PAGE = os.environ.get("PRODUCT_PAGE_BASE", "").rstrip("/")
CUSTOM_WORK_PRODUCT = os.environ.get("CUSTOM_WORK_PRODUCT_URL", "")


def price_for(pack: dict) -> float:
    cat = pack.get("category", "prompt-pack")
    n = len(pack.get("prompts", []))
    if cat == "skill-set":
        return min(49, max(19, 19 + (n - 3) * 5))
    return min(29, max(5, 5 + (n - 6) * 3))


def upload_to_edge(path: Path, prefix: str) -> str:
    """Legacy R2 path — only used if Cloudflare R2 is enabled later.
    The default delivery layer is GitHub Releases (see hosting.py)."""
    if not EDGE or not BOT_TOKEN:
        raise RuntimeError("EDGE_URL / BOT_TOKEN not set")
    name = f"{prefix}/{path.name}"
    req = urllib.request.Request(f"{EDGE}/upload/{name}", data=path.read_bytes(),
                                 method="PUT")
    req.add_header("X-Bot-Token", BOT_TOKEN)
    req.add_header("Content-Type", "application/octet-stream")
    req.add_header("User-Agent", "Mozilla/5.0 (asset-bot)")
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read())
    return f"{EDGE}{data['url']}"


def _log(action: str, payload: dict):
    print(f"[publish]{' DRY ' if DRY else ' LIVE '} {action}: {json.dumps(payload)[:400]}")


def update_product(product_id: str, visibility: str = "visible") -> dict:
    return whop._request("PATCH", f"/products/{product_id}", {"visibility": visibility})


def publish_asset(pack: dict, slug: str, file_urls: list[dict],
                  image_urls: list[str], description: str) -> dict:
    """Create product; free -> $0 plan live now, paid -> review Issue.

    file_urls: [{"name", "url"}] from hosting.py (GitHub Releases).
    image_urls: public promo image URLs (gallery)."""
    price = 0.0 if pack.get("free") else price_for(pack)

    # free products: buyers must get the files — append download links to
    # the description (release URLs are stable public CDN links)
    if price == 0.0 and file_urls:
        links_txt = "\n".join(f"- [{f['name']}]({f['url']})" for f in file_urls)
        description = (description + "\n\n## Your downloads\n" + links_txt +
                       "\n\n*(Instant delivery — click any file to download.)*")

    payload = {
        "company_id": COMPANY_ID,
        "title": pack["title"],
        "headline": pack["subtitle"],
        "description": description,
        "visibility": "visible" if price == 0.0 else "hidden",
        "metadata": {"slug": slug, "kind": pack.get("category"),
                     "generated": True, "free": price == 0.0, "price": price},
        "external_identifier": f"bot-{slug}",
    }
    if image_urls:
        # gallery_images is not accepted by product create in all API
        # versions — set after creation via PATCH when supported
        payload.pop("gallery_images", None)

    if DRY:
        _log("product", payload)
        _log("plan(paid: deferred)", {"price": price})
        return {"dry_run": True, "slug": slug, "price": price,
                "files": file_urls, "status": "dry"}

    product = whop.create_product(**payload)
    product_id = product.get("id")
    page_url = f"{PRODUCT_PAGE}/{product.get('route')}" if PRODUCT_PAGE and product.get("route") else ""
    result = {"slug": slug, "product_id": product_id, "page_url": page_url,
              "files": file_urls, "price": price}

    if image_urls:
        # Cover images: Whop rejects external URLs, so the bytes must be
        # mirrored in via the mediaDirectUpload -> S3 PUT -> updateAccessPass
        # sequence. See engine/whop_media.py for the verified call shapes.
        result["gallery_images"] = image_urls
        cover = whop_media.set_product_gallery(product_id, image_urls)
        result["cover_status"] = cover.get("status")
        if cover.get("status") == "set":
            print(f"[publish] cover image set on {product_id}")
        else:
            print(f"[publish] cover pending ({cover.get('reason')}) — "
                  f"{len(image_urls)} image(s) hosted: {image_urls[0]}")

    # Visible != discoverable. Submit to the whop.com marketplace so the
    # product appears on Discover, not just via direct link. Free products
    # are visible immediately; paid ones are hidden until /approve, so only
    # submit the ones that are actually visible.
    # FAQs: no product field exists, so attach the FAQ app as an experience
    # (sidebar item) and print the generated copy for the one manual paste.
    marketplace.faq_report(product_id, pack.get("faq"))
    if os.environ.get("ENABLE_FAQ_APP", "1") not in ("0", "false", "False"):
        try:
            marketplace.ensure_faq_experience(product_id, COMPANY_ID)
        except Exception as e:  # noqa: BLE001
            print(f"[faq] experience step skipped: {e}")

    if price == 0.0:
        listing = marketplace.publish(product_id, COMPANY_ID)
        result["marketplace_status"] = listing.get("marketplace_status")
        result["marketplace_missing"] = listing.get("missing")

    if price == 0.0:
        plan = whop.create_plan(product_id=product_id, initial_price=0.0)
        result["plan_id"] = plan.get("id")
        result["status"] = "live"
    else:
        issue = review.open_review_issue(pack, slug, price, image_urls, file_urls,
                                         page_url, product_id)
        result["review_issue"] = issue
        result["status"] = "pending_approval"
    return result


def approve(product_id: str, price: float, metadata: dict | None = None) -> dict:
    """Called by approve_from_issue.py on /approve."""
    plan = whop.create_plan(product_id=product_id, initial_price=price)
    upd = update_product(product_id, visibility="visible")
    # Now that it has a visible plan and is visible, it qualifies for the
    # marketplace — submit it so approved paid products are discoverable too.
    listing = marketplace.publish(product_id, COMPANY_ID)
    return {"plan_id": plan.get("id"), "update": upd,
            "marketplace_status": listing.get("marketplace_status"),
            "marketplace_missing": listing.get("missing")}
