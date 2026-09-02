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

import os

import whop_client as whop

# Fields Whop requires on the product itself.
REQUIRED_TEXT = ("title", "headline", "description")


def faq_report(product_id: str, faq: list[dict] | None) -> dict:
    """FAQs cannot be written through the API (verified: `faq` is rejected by
    v1 PATCH exactly like an unknown parameter, and UpdateAccessPassInput has
    no faq field — AccessPass.faq is read-only). So emit the generated copy in
    a paste-ready form and report whether the live product has any.
    """
    out = {"product_id": product_id, "generated": faq or [], "live_count": 0}
    try:
        p = whop._request("GET", f"/products/{product_id}")
        out["live_count"] = len(p.get("faq") or [])
    except Exception:  # noqa: BLE001
        pass
    if faq and not out["live_count"]:
        print(f"[faq] {product_id} has no FAQ on Whop. "
              f"{len(faq)} generated Q&A ready to paste "
              f"(Product editor -> FAQs):")
        for f in faq:
            print(f"   Q: {f['question']}")
            print(f"   A: {f['answer']}")
    return out


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


# --- FAQ via experience (app) -------------------------------------------
# There is no FAQ field on the Product API (verified: 0 occurrences of "faq"
# in the entire 3MB OpenAPI spec, no faq input in the GraphQL schema). FAQs
# are delivered as an *experience* — an app attached to the product.
#
# Whop's first-party FAQs app. Installing a THIRD-PARTY app via the API needs
# `app_authorization:create`, which a company/app key does not get — so this
# one must be added from the dashboard (product -> Add app -> FAQs).
FAQ_APP_ID = "app_PsBytos2S7vFcG"

# Our own app. `experience:create` covers creating experiences for THIS app,
# so this path is fully automatable. It renders whatever our app hosts.
OWN_APP_ID = os.environ.get("WHOP_APP_ID", "app_aJFKUT7MnR5730")


def ensure_faq_experience(product_id: str, company_id: str,
                          app_id: str | None = None,
                          name: str = "FAQ") -> dict:
    """Create the FAQ experience once, then attach it to `product_id`.

    Requires `experience:create` on the App key (and `app_authorization:create`
    for a company key). Never raises. NOTE: this creates the sidebar item only —
    the FAQs app has no public write API, so the questions themselves are still
    entered in the app UI. The generated copy is printed by faq_report().
    """
    app_id = app_id or OWN_APP_ID
    out = {"product_id": product_id, "app_id": app_id}
    try:
        existing = (whop._request(
            "GET", f"/experiences?company_id={company_id}") or {}).get("data") or []
    except Exception as e:  # noqa: BLE001
        out.update(status="error", error=f"list failed: {e}")
        return out

    def _app_of(e):
        a = e.get("app")
        return a.get("id") if isinstance(a, dict) else e.get("app_id")

    # match on app AND name so our app can own more than one experience
    exp = next((e for e in existing
                if _app_of(e) == app_id and (e.get("name") or "") == name), None)

    if exp is None:
        try:
            exp = whop._request("POST", "/experiences", {
                "app_id": app_id, "company_id": company_id, "name": name})
            out["created"] = True
        except Exception as e:  # noqa: BLE001
            out.update(status="needs_permission", error=str(e)[:200])
            if "experience:create" in str(e):
                print("[faq] experience:create denied. NOTE: Whop freezes an "
                      "app's grants at INSTALL time — adding a permission to "
                      "the app afterwards does not apply to an existing "
                      "install. Re-install the app to pick it up: "
                      "https://whop.com/apps/app_aJFKUT7MnR5730/install/")
            else:
                print(f"[faq] cannot create FAQ experience: {e}")
            return out

    exp_id = exp.get("id")
    out["experience_id"] = exp_id
    try:
        whop._request("POST", f"/experiences/{exp_id}/attach",
                      {"product_id": product_id})
        out["status"] = "attached"
        print(f"[faq] FAQ experience {exp_id} attached to {product_id}")
    except Exception as e:  # noqa: BLE001
        out.update(status="attach_failed", error=str(e)[:200])
        print(f"[faq] attach failed for {product_id}: {e}")
    return out
