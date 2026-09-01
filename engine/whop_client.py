"""
whop_client.py — minimal Whop REST client for the asset bot.

Base URLs:  prod    https://api.whop.com/api/v1
            sandbox https://sandbox-api.whop.com/api/v1
Auth: Bearer key. Rate limit: 600 req/min per operation per credential.
"""
import json
import os
import time
import urllib.request
import urllib.error

BASE = os.environ.get("WHOP_API_BASE", "https://api.whop.com/api/v1")


class WhopError(Exception):
    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"Whop HTTP {status}: {body[:300]}")


def _request(method: str, path: str, payload: dict | None = None,
             retries: int = 3):
    url = f"{BASE}{path}"
    key = os.environ.get("WHOP_API_KEY")
    if not key:
        raise RuntimeError("WHOP_API_KEY not set")
    data = json.dumps(payload).encode() if payload is not None else None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {key}")
        req.add_header("User-Agent", "Mozilla/5.0 (asset-bot)")
        if data:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            if e.code == 429 and attempt < retries - 1:
                time.sleep(2 ** attempt * 5)
                continue
            raise WhopError(e.code, body)
        except urllib.error.URLError as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt * 5)
                continue
            raise


# ---------- account / identity ----------
def me():
    return _request("GET", "/accounts/me")


def my_companies():
    return _request("GET", "/companies")


# ---------- products & plans ----------
def create_product(company_id: str, title: str, description: str = "",
                   headline: str = "", visibility: str = "visible",
                   metadata: dict | None = None, external_identifier: str | None = None,
                   gallery_images: list | None = None, **extra):
    payload = {
        "company_id": company_id,
        "title": title,
        "description": description,
        "headline": headline or title,
        "visibility": visibility,
        "metadata": metadata or {},
    }
    if external_identifier:
        payload["external_identifier"] = external_identifier  # idempotent upsert
    if gallery_images:
        payload["gallery_images"] = gallery_images
    payload.update({k: v for k, v in extra.items() if v is not None})
    return _request("POST", "/products", payload)


def list_products(company_id: str):
    return _request("GET", f"/products?company_id={company_id}")


def create_plan(product_id: str, plan_type: str = "one_time",
                initial_price: float = 0.0, renewal_price: float | None = None,
                billing_period: int | None = None, metadata: dict | None = None):
    payload = {
        "product_id": product_id,
        "plan_type": plan_type,
        "initial_price": initial_price,
        "metadata": metadata or {},
    }
    if renewal_price is not None:
        payload["renewal_price"] = renewal_price
    if billing_period is not None:
        payload["billing_period"] = billing_period
    return _request("POST", "/plans", payload)


# ---------- forum posts ----------
def create_forum_post(experience_id: str, content: str, title: str = "",
                      company_id: str | None = None, attachments: list | None = None,
                      poll: dict | None = None):
    """experience_id 'public' + company_id -> company's public forum.
    experience_id 'exp_xxx' -> specific forum experience."""
    payload = {
        "experience_id": experience_id,
        "content": content,
    }
    if title:
        payload["title"] = title
    if company_id:
        payload["company_id"] = company_id
    if attachments:
        payload["attachments"] = [{"direct_upload_id": a} for a in attachments]
    if poll:
        payload["poll"] = poll
    return _request("POST", "/forum_posts", payload)


# ---------- memberships / webhook consumers ----------
def list_memberships(company_id: str = "", limit: int = 50):
    q = f"?company_id={company_id}&limit={limit}" if company_id else f"?limit={limit}"
    return _request("GET", f"/memberships{q}")
