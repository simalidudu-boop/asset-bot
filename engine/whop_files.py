"""Whop-hosted delivery for PAID products.

Why this exists
---------------
Deliverables were hosted as public GitHub Release assets and the links were
printed in public review issues. Verified 2026-09-05: an anonymous stranger
could download the $11 product's PDF, DOCX and ZIP with no token. 177 files
were exposed that way.

Free products *should* be public — that is the funnel. Paid products must not
be. This module uploads paid deliverables to Whop as **private** files, which
Whop serves via signed, expiring URLs.

Verified live against the API (2026-09-05):

    POST /files {filename, byte_size, visibility:"private"}
      -> {id, upload_url, upload_headers, upload_status:"pending"}
    PUT  bytes to upload_url with the returned headers      -> 200
    GET  /files/{id}   -> upload_status:"ready", url = signed
    signed URL   -> 200
    unsigned URL -> 403          <-- the whole point

Signed URLs carry `X-Amz-Expires=86400` (24h), so they are re-fetched from
`GET /files/{id}` rather than stored.

Files >5MB should use the multipart path (`multipart: true` +
`POST /files/{id}/complete`); our packs are far smaller, so single-part only.
"""
from __future__ import annotations

import mimetypes
import os
import urllib.request
from pathlib import Path

import whop_client as whop

MAX_SINGLE_PART = 5 * 1024 * 1024   # Whop requires multipart above this


def upload_private(path: Path | str, filename: str | None = None) -> dict:
    """Upload one local file to Whop as a private (signed-URL) file."""
    p = Path(path)
    if not p.exists():
        return {"ok": False, "error": f"missing file: {p}"}
    data = p.read_bytes()
    name = filename or p.name
    if len(data) > MAX_SINGLE_PART:
        return {"ok": False,
                "error": f"{name} is {len(data)}b — needs the multipart flow"}

    try:
        f = whop._request("POST", "/files", {
            "filename": name,
            "byte_size": len(data),
            "visibility": "private",
        })
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"create failed: {e}"}

    fid, url = f.get("id"), f.get("upload_url")
    if not (fid and url):
        return {"ok": False, "error": f"no upload_url in response: {str(f)[:150]}"}

    req = urllib.request.Request(url, data=data, method="PUT")
    for k, v in (f.get("upload_headers") or {}).items():
        req.add_header(k, v)
    if "Content-Type" not in (f.get("upload_headers") or {}):
        req.add_header("Content-Type",
                       mimetypes.guess_type(name)[0] or "application/octet-stream")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            if r.status not in (200, 201):
                return {"ok": False, "error": f"PUT returned {r.status}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"PUT failed: {e}"}

    return {"ok": True, "file_id": fid, "filename": name}


def signed_url(file_id: str, wait_ready: bool = True) -> str:
    """Fetch a fresh signed URL. They expire in 24h, so never cache them.

    A file is `pending` for a moment after the PUT — asking too early returns
    no url at all, which silently produced an empty download block in testing.
    """
    import time as _t
    for attempt in range(6 if wait_ready else 1):
        try:
            f = whop._request("GET", f"/files/{file_id}") or {}
        except Exception:  # noqa: BLE001
            return ""
        if f.get("upload_status") == "ready" and f.get("url"):
            return f["url"]
        if not wait_ready:
            return f.get("url") or ""
        _t.sleep(1 + attempt)
    return ""


def upload_deliverables(paths: list, slug: str) -> dict:
    """Upload every paid deliverable. Never raises — delivery must not break
    a publish run, and a partial upload is still better than none."""
    files, errs = [], []
    for p in paths:
        r = upload_private(p, f"{slug}-{Path(p).name}")
        if r.get("ok"):
            files.append({"file_id": r["file_id"], "filename": r["filename"]})
            print(f"[files] uploaded {r['filename']} -> {r['file_id']}")
        else:
            errs.append(r.get("error", "?"))
            print(f"[files] FAILED {Path(p).name}: {r.get('error')}")
    return {"files": files, "errors": errs,
            "ok": bool(files) and not errs}


def delivery_block(files: list) -> str:
    """Markdown for the product description, using fresh signed URLs.

    NOTE: these expire in 24h. A buyer who returns later needs a refreshed
    link — the durable fix is Whop's own attachment/delivery UI, but this at
    least stops the files being world-readable.
    """
    if not files:
        return ""
    lines = ["\n\n## Your downloads\n"]
    for f in files:
        u = signed_url(f["file_id"])
        if u:
            lines.append(f"- [{f['filename']}]({u})")
    lines.append("\n*Links are private to this product and refresh "
                 "periodically. Re-open this page if one expires.*")
    return "\n".join(lines)
