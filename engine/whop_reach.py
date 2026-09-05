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
            whop._request("POST", "/messages",
                          {"channel_id": cid, "content": text[:2000]})
            sent.append(cid)
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
def dm_members(text: str, asset_slug: str,
               company_id: str | None = None) -> dict:
    """DM members about ONE asset, at most once each, ever.

    Off by default. Unsolicited repeat DMs are how a Whop account gets
    reported, and we would lose the only storefront we have.
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
        try:
            # A DM is a message to a channel scoped to that user.
            whop._request("POST", "/messages",
                          {"user_id": m["user_id"], "content": text[:2000]})
            done.add(m["user_id"])
            sent += 1
        except Exception as e:  # noqa: BLE001
            errs.append(f"{m['user_id']}: {str(e)[:120]}")

    led[asset_slug] = sorted(done)
    _save(led)
    print(f"[reach] DM: {sent} sent, {len(errs)} failed, "
          f"{len(targets) - sent} left for next run")
    for e in errs[:3]:
        print(f"[reach] dm failed {e}")
    return {"sent": sent, "errors": errs}


def announce(title: str, url: str, blurb: str = "",
             asset_slug: str = "") -> dict:
    """One call from publish.py: chat broadcast + optional DMs."""
    msg = f"**{title}**\n\n{blurb}\n\n{url}".strip()
    out = {"chat": broadcast_chat(msg)}
    if asset_slug:
        out["dm"] = dm_members(msg, asset_slug)
    return out
