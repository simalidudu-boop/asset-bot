"""Whop reach: chat broadcast + member DMs.

Verified against the live API 2026-09-04.

What actually exists
--------------------
  GET  /api/v1/members?company_id=…        -> our members (3 today)
  GET  /api/v1/chat_channels?company_id=…  -> chat feeds we own
  POST /api/v1/messages {channel_id, …}    -> send into a channel
  POST /api/v1/forum_posts {experience_id: "public", company_id}

Permission required
-------------------
Chat and DM both need **`chat:message:create`**, which neither the company key
nor the app key has today (verified: both return
"Unauthorized: Actor is missing all required permissions: chat:message:create").

To enable: add `chat:message:create` to the app's requested permissions, then
**re-install the app** — Whop freezes grants at install time, so adding a
permission to an existing install does nothing.

Until then these functions degrade quietly rather than failing a run.

What does NOT work — do not retry
---------------------------------
  Posting to ANOTHER company's forum. Verified against two foreign biz ids:
      400 "Unauthorized: Actor is missing all required permissions:
           forum:post:create"
  A company API key is scoped to its own company. Joining someone's whop as a
  human does not grant your key posting rights there. There is no API path to
  other people's forums; that is a manual, human action.

Restraint is deliberate
-----------------------
DMing members is the highest-risk channel we have: it is the one that gets an
account reported. So this module:
  * never DMs the same member about the same asset twice (persisted ledger)
  * skips admins and no_access members
  * caps sends per run
  * is OFF unless WHOP_DM_ENABLED=1
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import whop_client as whop


def _app_request(method: str, path: str, payload: dict | None = None):
    """Chat/DM endpoints authenticate with the APP key, not the company key.

    Verified 2026-09-05: with chat:message:create granted, the app key sends
    successfully (200, post_1CekGjt…) while the company key still returns
    "missing all required permissions: chat:message:create". The grant lives
    on the app, so requests must be made as the app.
    """
    import json as _j
    import urllib.error
    import urllib.request

    key = os.environ.get("WHOP_APP_API_KEY", "")
    app_id = os.environ.get("WHOP_APP_ID", "")
    if not key:
        raise RuntimeError("WHOP_APP_API_KEY not set — chat/DM need the app key")
    req = urllib.request.Request(
        f"https://api.whop.com/api/v1{path}",
        data=_j.dumps(payload).encode() if payload is not None else None,
        method=method)
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    if app_id:
        req.add_header("x-whop-app-id", app_id)
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return _j.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"whop {e.code}: {e.read().decode(errors='replace')[:200]}")

STATE = Path(__file__).resolve().parent.parent / "state"
DM_LEDGER = STATE / "dm_sent.json"

COMPANY = os.environ.get("WHOP_COMPANY_ID", "")
MAX_DMS = int(os.environ.get("WHOP_DM_MAX_PER_RUN", "10"))


def _ledger() -> dict:
    try:
        return json.loads(DM_LEDGER.read_text())
    except Exception:  # noqa: BLE001
        return {}


def _save(d: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    DM_LEDGER.write_text(json.dumps(d, indent=2))


# ------------------------------------------------------------- members ---
def members(company_id: str | None = None) -> list:
    cid = company_id or COMPANY
    try:
        r = whop._request("GET", f"/members?company_id={cid}")
        return r.get("data") or []
    except Exception as e:  # noqa: BLE001
        print(f"[reach] members fetch failed: {e}")
        return []


def mailable(company_id: str | None = None) -> list:
    """Members worth messaging: real users, joined, not admins.

    Admins are us. no_access members never completed a purchase.
    """
    out = []
    for m in members(company_id):
        u = m.get("user")
        uid = u.get("id") if isinstance(u, dict) else u
        if not uid:
            continue
        if m.get("access_level") == "admin":
            continue
        if m.get("status") != "joined":
            continue
        out.append({"member_id": m.get("id"), "user_id": uid})
    return out


# --------------------------------------------------------- chat channels ---
def chat_channels(company_id: str | None = None) -> list:
    cid = company_id or COMPANY
    try:
        r = whop._request("GET", f"/chat_channels?company_id={cid}")
        return r.get("data") or []
    except Exception as e:  # noqa: BLE001
        print(f"[reach] chat_channels failed: {e}")
        return []


def broadcast_chat(text: str, company_id: str | None = None) -> dict:
    """Post into every chat feed we own. Members already opted in, so this is
    low-risk compared with DMs."""
    sent, errs = [], []
    for c in chat_channels(company_id):
        cid = c.get("id")
        if not cid:
            continue
        try:
            _app_request("POST", "/messages",
                         {"channel_id": cid, "content": text[:2000]})
            sent.append(cid)
        except Exception as e0:  # noqa: BLE001
            # Chats can have "Posting URLs is not allowed" enabled. Rather
            # than lose the announcement entirely, retry without the link —
            # a message that lands beats one that 400s.
            if "URLs is not allowed" in str(e0):
                import re as _re
                stripped = _re.sub(r"https?://\S+", "", text).strip()
                stripped = _re.sub(r"\s{2,}", " ", stripped)
                try:
                    _app_request("POST", "/messages",
                                 {"channel_id": cid,
                                  "content": stripped[:2000]})
                    sent.append(cid)
                    print(f"[reach] {cid}: posted without URL "
                          "(chat blocks links)")
                    continue
                except Exception as e1:  # noqa: BLE001
                    errs.append(f"{cid}: {str(e1)[:120]}")
                    continue
            raise e0
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if "chat:message:create" in msg:
                errs.append("needs chat:message:create — add it to the app "
                            "and RE-INSTALL (grants freeze at install time)")
                break
            errs.append(f"{cid}: {msg[:120]}")
    if sent:
        print(f"[reach] chat broadcast -> {len(sent)} channel(s)")
    for e in errs:
        print(f"[reach] chat failed {e}")
    return {"sent": sent, "errors": errs}


# ------------------------------------------------------------------ DMs ---
def dm_channel_for(user_id: str) -> str:
    """Get (or create) the DM channel with one user. Returns "" on failure.

    The parameter is **`with_user_ids`**, not `user_ids`. That is not
    documented anywhere and is not in the OpenAPI spec — every wrong name
    echoes back "Missing required parameter: <your name>", which makes the
    error useless. Sending an EMPTY body is what reveals the true name.
    """
    try:
        r = _app_request("POST", "/dm_channels",
                         {"with_user_ids": [user_id]})
        return r.get("id", "")
    except Exception as e:  # noqa: BLE001
        print(f"[reach] dm channel failed for {user_id}: {str(e)[:120]}")
        return ""


def dm_members(text: str, asset_slug: str,
               company_id: str | None = None) -> dict:
    """DM members about ONE asset, at most once each, ever.

    Verified working 2026-09-05 (channel feed_1CekKpAnc…, message post_…).

    Deliberately conservative. This is the only channel here that lands in
    someone's inbox uninvited, and a report against the account would cost us
    the storefront. So: opt-in flag, one message per member per asset ever,
    admins excluded, hard per-run cap.
    """
    if os.environ.get("WHOP_DM_ENABLED", "0") != "1":
        return {"skipped": "WHOP_DM_ENABLED != 1"}

    led = _ledger()
    done = set(led.get(asset_slug, []))
    targets = [m for m in mailable(company_id) if m["user_id"] not in done]
    if not targets:
        print(f"[reach] no new members to DM about {asset_slug}")
        return {"sent": 0, "skipped": "all already messaged"}

    sent, errs = 0, []
    for m in targets[:MAX_DMS]:
        cid = dm_channel_for(m["user_id"])
        if not cid:
            errs.append(f"{m['user_id']}: no channel")
            continue
        try:
            _app_request("POST", "/messages",
                         {"channel_id": cid, "content": text[:2000]})
            done.add(m["user_id"])
            sent += 1
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if "URLs is not allowed" in msg:
                import re as _re
                plain = _re.sub(r"https?://\S+", "", text).strip()
                try:
                    _app_request("POST", "/messages",
                                 {"channel_id": cid, "content": plain[:2000]})
                    done.add(m["user_id"])
                    sent += 1
                    continue
                except Exception as e2:  # noqa: BLE001
                    msg = str(e2)
            errs.append(f"{m['user_id']}: {msg[:110]}")

    led[asset_slug] = sorted(done)
    _save(led)
    print(f"[reach] DM: {sent} sent, {len(errs)} failed, "
          f"{max(0, len(targets) - sent - len(errs))} left for next run")
    for e in errs[:3]:
        print(f"[reach] dm failed {e}")
    return {"sent": sent, "errors": errs}


def announce(title: str, url: str, blurb: str = "",
             asset_slug: str = "") -> dict:
    """One call from publish.py — every Whop-native surface we can reach.

    Ordered by value: notifications reach members inside the app and have no
    URL restriction; chat is opt-in but link-limited; DMs are gated behind a
    permission we do not have and are off by default anyway.
    """
    msg = f"**{title}**\n\n{blurb}\n\n{url}".strip()
    out = {
        "notification": notify(title, f"{blurb}\n\n{url}".strip()),
        "chat": broadcast_chat(msg),
    }
    if asset_slug:
        out["dm"] = dm_members(msg, asset_slug)
    return out


# ---------------------------------------------------- notifications ---
def notify(title: str, content: str, subtitle: str = "",
           experience_id: str = "", company_id: str | None = None) -> dict:
    """Push a notification to members. Verified 2026-09-05: 200 {"success":true}.

    This is the highest-value permission that was granted, because it reaches
    members in the Whop app itself rather than a forum nobody visits. Unlike
    chat it has no URL restriction, and unlike DMs it needs no channel.

    Scope: `experience_id` targets an experience's users; otherwise it goes to
    the account's team. Keep it to genuine releases — a notification is more
    intrusive than a forum post, and the fastest way to get muted.
    """
    body = {"title": title[:120], "content": content[:500]}
    if subtitle:
        body["subtitle"] = subtitle[:120]
    if experience_id:
        body["experience_id"] = experience_id
    else:
        body["account_id"] = company_id or COMPANY
    try:
        r = _app_request("POST", "/notifications", body)
        ok = bool(r.get("success"))
        print(f"[reach] notification {'sent' if ok else 'rejected'}: {title[:50]}")
        return {"ok": ok}
    except Exception as e:  # noqa: BLE001
        print(f"[reach] notification failed: {str(e)[:140]}")
        return {"ok": False, "error": str(e)[:200]}


# ------------------------------------------------------- promo codes ---
def create_promo(code: str, percent_off: int = 30, product_id: str = "",
                 months: int = 1, company_id: str | None = None) -> dict:
    """Create a discount code. Verified live (promo_eNslWWwdyOam).

    A launch discount is the one conversion lever we can pull without an
    audience — it makes an announcement worth acting on now rather than later.

    Required by the API: account_id, code, promo_type, amount_off,
    base_currency, new_users_only, promo_duration_months.
    """
    body = {
        "account_id": company_id or COMPANY,
        "code": code[:40],
        "promo_type": "percentage",
        "amount_off": percent_off,
        "base_currency": "usd",
        "new_users_only": False,
        "promo_duration_months": months,
        "unlimited_stock": True,
        "one_per_customer": True,
    }
    if product_id:
        body["product_id"] = product_id
    try:
        r = _app_request("POST", "/promo_codes", body)
        if r.get("id"):
            print(f"[reach] promo {r.get('code')} created ({percent_off}% off)")
            return {"ok": True, "id": r["id"], "code": r.get("code")}
        return {"ok": False, "error": str(r)[:200]}
    except Exception as e:  # noqa: BLE001
        # a duplicate code is not a failure worth alerting on
        if "already" in str(e).lower() or "taken" in str(e).lower():
            return {"ok": True, "code": code, "note": "already exists"}
        print(f"[reach] promo failed: {str(e)[:140]}")
        return {"ok": False, "error": str(e)[:200]}


# ------------------------------------------------------------- stats ---
def revenue_stats(company_id: str | None = None) -> dict:
    """Read Whop's own revenue metrics — the honest scoreboard.

    Our dashboard counts assets and posts, which measure activity, not
    success. These measure whether any of it worked.
    """
    try:
        r = _app_request("GET", "/stats") or {}
        keep = {"account_balance", "annual_recurring_revenue",
                "average_revenue_per_user", "affiliate_fees"}
        return {s.get("key"): s.get("value")
                for s in (r.get("data") or []) if s.get("key") in keep}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:150]}
