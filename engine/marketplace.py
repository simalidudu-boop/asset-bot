"""Whop marketplace listing: validate requirements, then submit for review.

Visible != discoverable. A product with `visibility: "visible"` is reachable
by direct link and shows on your own store page, but it does NOT appear on
whop.com/discover until it is *published* to the marketplace, at which point
`marketplace_status` moves:

    not_available -> pending_review -> live_marketplace

Whop's published requirements for a marketplace listing:

  1. Title
  2. Headline
  3. Description
  4. A logo  (company-level, shared by all products)
  5. Gallery images (at least one; video preferred)
  6. At least one available pricing option (a visible plan)

`POST /api/v1/products/{id}/publish` submits the product. It returns 409 if
the product does not qualify, so we pre-flight every requirement and log
precisely what is missing rather than firing blind.

CAVEAT (verified live): `GET /products/{id}` does NOT return
`marketplace_status` — only the publish response does. So the "already
submitted" short-circuit cannot rely on a fetch; callers should pass
`known_status` from state/manifest.json. Re-publishing is idempotent
(returns 200 and stays `pending_review`), so a duplicate call is harmless.
"""
from __future__ import annotations

import whop_client as whop

# Fields Whop requires on the product itself.
REQUIRED_TEXT = ("title", "headline", "description")


def check_requirements(product_id: str, company_id: str | None = None) -> dict:
    """Return {"ok": bool, "missing": [...], "product": {...}}."""
    missing: list[str] = []
    try:
        p = whop._request("GET", f"/products/{product_id}")
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "missing": [f"product fetch failed: {e}"],
                "product": {}}

    for f in REQUIRED_TEXT:
        if not (p.get(f) or "").strip():
            missing.append(f)

    if not (p.get("gallery_images") or []):
        missing.append("gallery_images")

    # A logo lives on the company, not the product.
    if company_id:
        try:
            c = whop._request("GET", f"/companies/{company_id}")
            logo = c.get("logo") or c.get("image_url")
            if not logo:
                missing.append("company logo")
        except Exception:  # noqa: BLE001
            pass  # don't block on an unreadable company record

    # At least one visible plan == "an available pricing option".
    if company_id:
        try:
            plans = (whop._request(
                "GET", f"/plans?account_id={company_id}&per=50") or {}).get("data") or []
            mine = [pl for pl in plans
                    if (pl.get("product", {}) or {}).get("id") == product_id
                    or pl.get("product") == product_id]
            if not any(pl.get("visibility") == "visible" for pl in mine):
                missing.append("a visible pricing plan")
        except Exception:  # noqa: BLE001
            pass

    if (p.get("visibility") or "") != "visible":
        missing.append(f"visibility is {p.get('visibility')!r}, must be 'visible'")

    return {"ok": not missing, "missing": missing, "product": p}


def publish(product_id: str, company_id: str | None = None,
            force: bool = False, known_status: str | None = None) -> dict:
    """Validate then submit the product to the Whop marketplace.

    Never raises — a failed listing must not fail a publish run.
    """
    status = {"product_id": product_id}
    chk = check_requirements(product_id, company_id)
    # GET omits marketplace_status, so trust the caller's recorded value.
    current = known_status or (chk.get("product") or {}).get("marketplace_status")
    status["was"] = current

    if current in ("pending_review", "live_marketplace"):
        status.update(status="already_submitted", marketplace_status=current)
        print(f"[marketplace] {product_id} already {current}")
        return status

    if not chk["ok"] and not force:
        status.update(status="not_eligible", missing=chk["missing"])
        print(f"[marketplace] {product_id} NOT eligible — missing: "
              f"{', '.join(chk['missing'])}")
        return status

    try:
        res = whop._request("POST", f"/products/{product_id}/publish")
        ms = res.get("marketplace_status")
        status.update(status="submitted", marketplace_status=ms)
        print(f"[marketplace] {product_id} submitted -> {ms}")
    except Exception as e:  # noqa: BLE001
        status.update(status="error", error=str(e)[:300])
        print(f"[marketplace] publish failed for {product_id}: {e}")
    return status
