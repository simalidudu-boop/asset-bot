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
import resilience as rz  # noqa: E402
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
                  image_urls: list[str], description: str,
                  local_files: list | None = None) -> dict:
    """Create product; free -> $0 plan live now, paid -> review Issue.

    file_urls: [{"name", "url"}] from hosting.py (GitHub Releases).
    image_urls: public promo image URLs (gallery)."""
    price = 0.0 if pack.get("free") else price_for(pack)
    local_files = local_files or []

    # FREE products: public GitHub Release links are correct — the whole
    # point is frictionless access, and they double as the funnel.
    if price == 0.0 and file_urls:
        links_txt = "\n".join(f"- [{f['name']}]({f['url']})" for f in file_urls)
        description = (description + "\n\n## Your downloads\n" + links_txt +
                       "\n\n*(Instant delivery — click any file to download.)*")

    # PAID products: NEVER link public release assets. Verified 2026-09-05 that
    # an anonymous stranger could download the $11 pack's PDF/DOCX/ZIP straight
    # from GitHub. Paid deliverables are uploaded to Whop as PRIVATE files and
    # served through signed, expiring URLs (signed 200 / unsigned 403).
    paid_files = []
    if price > 0 and local_files:
        try:
            import whop_files
            up = whop_files.upload_deliverables(local_files, slug)
            paid_files = up.get("files") or []
            if up.get("errors"):
                print(f"[publish] some paid uploads failed: {up['errors'][:2]}")
        except Exception as e:  # noqa: BLE001
            print(f"[publish] private upload skipped: {e}")

    payload = {
        "company_id": COMPANY_ID,
        "title": pack["title"],
        "headline": pack["subtitle"],
        "description": description,
        "visibility": "visible" if price == 0.0 else "hidden",
        "metadata": {"slug": slug, "kind": pack.get("category"),
                     "generated": True, "free": price == 0.0, "price": price},
        # NOTE: `external_identifier` is NO LONGER ACCEPTED by Whop's create
        # endpoint — it 400s for every value tried (plain slug, timestamped,
        # alphanumeric-only), while omitting it succeeds. Verified 2026-09-04.
        # The slug already lives in `metadata`, so nothing is lost.
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
    # Fan out to every configured distribution channel. Enqueue only — no
    # network here; the bounded worker drains it. A dead channel can never
    # stall or fail a publish run.
    # ONLY distribute what is actually buyable. Paid assets sit `hidden` on
    # Whop until /approve, so enqueuing them broadcasts a dead link to every
    # channel. Observed: 4 unapproved products queued 68 posts between them.
    # approve() re-enqueues once the product goes visible.
    if price != 0.0:
        # signed download links live on the product page, behind checkout
        if paid_files:
            try:
                import whop_files
                block = whop_files.delivery_block(paid_files)
                if block:
                    whop._request("PATCH", f"/products/{product_id}",
                                  {"description": (description + block)[:8000]})
                    print(f"[publish] {len(paid_files)} private file(s) attached")
                    result["paid_files"] = [f["file_id"] for f in paid_files]
            except Exception as e:  # noqa: BLE001
                print(f"[publish] delivery block failed: {e}")
        print(f"[dist] {slug}: paid asset pending approval — not enqueued yet")
        return _finish_paid(result, pack, slug, price, image_urls,
                            file_urls, page_url, product_id)

    try:
        import dist_core
        import dist_channels  # noqa: F401  (registers the adapters)
        dist_core.enqueue({
            "slug": slug,
            "title": pack.get("title"),
            "subtitle": pack.get("subtitle"),
            "description": description,
            "keywords": pack.get("keywords") or [],
            "faq": pack.get("faq") or [],
            "price": price,
            "page_url": result.get("page_url") or "",
            "deliverable_url": (file_urls[0]["url"] if file_urls else ""),
            "gallery_images": image_urls or [],
            # public (non-Whop) copies — third parties cannot fetch Whop CDN
            "release_images": image_urls or [],
        })
    except Exception as e:  # noqa: BLE001
        print(f"[dist] enqueue skipped: {e}")
        rz.alert("Distribution enqueue failed", f"`{e}`", level="warn",
                 dedupe="enqueue-fail")

    # Whop-native reach: chat broadcast (+ DMs when explicitly enabled).
    # Members and chat feeds are audience we already have; the forum posts
    # alone were only reaching two empty forums.
    try:
        import whop_reach
        whop_reach.announce(pack.get("title", slug),
                            page_url or result.get("page_url", ""),
                            pack.get("subtitle", ""), asset_slug=slug)
    except Exception as e:  # noqa: BLE001
        print(f"[reach] skipped: {e}")

    # FAQs: no product field exists, so attach the FAQ app as an experience
    # (sidebar item) and print the generated copy for the one manual paste.
    marketplace.faq_report(product_id, pack.get("faq"))
    if os.environ.get("ENABLE_FAQ_APP", "1") not in ("0", "false", "False"):
        try:
            marketplace.ensure_faq_experience(product_id, COMPANY_ID)
        except Exception as e:  # noqa: BLE001
            print(f"[faq] experience step skipped: {e}")

    if price == 0.0:
        # ORDER MATTERS. The $0 plan MUST exist before the marketplace
        # submission: Whop requires "at least one available pricing option",
        # and publishing first produced
        #   "NOT eligible — missing: a visible pricing plan"
        # on every free asset, silently keeping them off Discover.
        plan = whop.create_plan(product_id=product_id, initial_price=0.0)
        result["plan_id"] = plan.get("id")
        result["status"] = "live"

        listing = marketplace.publish(product_id, COMPANY_ID)
        result["marketplace_status"] = listing.get("marketplace_status")
        result["marketplace_missing"] = listing.get("missing")
    else:
        issue = review.open_review_issue(pack, slug, price, image_urls, file_urls,
                                         page_url, product_id)
        result["review_issue"] = issue
        result["status"] = "pending_approval"
    return result


def _finish_paid(result, pack, slug, price, image_urls, file_urls,
                 page_url, product_id):
    """Paid assets: open the review issue, skip distribution until approved."""
    issue = review.open_review_issue(pack, slug, price, image_urls, file_urls,
                                     page_url, product_id)
    result["review_issue"] = issue
    result["status"] = "pending_approval"
    return result


def enqueue_asset(slug: str, pack: dict, price: float, page_url: str,
                  file_urls: list, image_urls: list, description: str) -> None:
    """Queue one asset for distribution. Shared by publish and approve."""
    try:
        import dist_core
        import dist_channels  # noqa: F401
        dist_core.enqueue({
            "slug": slug,
            "title": pack.get("title"),
            "subtitle": pack.get("subtitle"),
            "description": description,
            "keywords": pack.get("keywords") or [],
            "faq": pack.get("faq") or [],
            "price": price,
            "page_url": page_url or "",
            "deliverable_url": (file_urls[0]["url"] if file_urls else ""),
            "gallery_images": image_urls or [],
            "release_images": image_urls or [],
        })
    except Exception as e:  # noqa: BLE001
        print(f"[dist] enqueue skipped: {e}")


def approve(product_id: str, price: float, metadata: dict | None = None) -> dict:
    """Called by approve_from_issue.py on /approve."""
    plan = whop.create_plan(product_id=product_id, initial_price=price)
    upd = update_product(product_id, visibility="visible")
    # Now that it has a visible plan and is visible, it qualifies for the
    # marketplace — submit it so approved paid products are discoverable too.
    listing = marketplace.publish(product_id, COMPANY_ID)

    # NOW distribute: the product is visible and purchasable, so the links we
    # broadcast actually resolve. publish_asset() deliberately skipped this.
    md = (metadata or {})
    if md.get("slug"):
        enqueue_asset(md["slug"], md.get("pack") or {"title": md.get("title")},
                      price, md.get("page_url", ""), md.get("file_urls") or [],
                      md.get("image_urls") or [], md.get("description", ""))

    return {"plan_id": plan.get("id"), "update": upd,
            "marketplace_status": listing.get("marketplace_status"),
            "marketplace_missing": listing.get("missing")}
