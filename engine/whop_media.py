"""Whop media upload: hosted image URL -> attachment -> product cover.

Verified live against the Whop API on 2026-09-02. The working sequence is:

  1. `mediaDirectUpload` GraphQL mutation (api.whop.com/public-graphql) with
     contentType, byteSizeV2, checksum (base64 MD5), filename and
     record: "access_pass"  <- a Whop "product" is an access_pass internally.
     Returns { id (signed blob id), uploadUrl (S3), headers }.
  2. PUT the raw bytes to uploadUrl with exactly the headers returned. -> 200
  3. `mediaAnalyzeAttachment` with { directUploadId, mediaType: "image" }
     (lowercase enum) to finalize the upload. Returns Boolean.
  4. `attachment(id: <blob id>)` query -> resolves to the real **file_ ID**.
     The signed blob id is NOT accepted by galleryImages; the `file_` id is.
  5. `updateAccessPass` with galleryImages: [{ id: "file_..." }].

Requires an **App API key** (WHOP_APP_API_KEY) plus the app id
(WHOP_APP_ID) sent as x-whop-app-id. The plain company key gets 401 on
step 1. Step 3 additionally needs the `access_pass:update` permission on
the app; without it steps 1-2 still succeed and this module reports
"pending_manual" rather than raising.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import urllib.error
import urllib.request

GQL = "https://api.whop.com/public-graphql"
UA = "Mozilla/5.0 (asset-bot)"


def _key() -> str | None:
    return os.environ.get("WHOP_APP_API_KEY") or None


def _headers() -> dict:
    h = {
        "Authorization": f"Bearer {_key()}",
        "Content-Type": "application/json",
        "User-Agent": UA,
    }
    app_id = os.environ.get("WHOP_APP_ID")
    if app_id:
        h["x-whop-app-id"] = app_id
    return h


def _gql(query: str, variables: dict, timeout: int = 60) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(GQL, data=body, method="POST")
    for k, v in _headers().items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read())
    if out.get("errors"):
        raise RuntimeError(out["errors"][0].get("message", "graphql error"))
    return out["data"]


def _fetch(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


UPLOAD_MUT = (
    "mutation($i:DirectUploadInput!){mediaDirectUpload(input:$i)"
    "{id uploadUrl headers}}"
)
ANALYZE_MUT = (
    "mutation($i:AnalyzeAttachmentInput!){mediaAnalyzeAttachment(input:$i)}"
)
ATTACHMENT_Q = (
    "query($id:ID!){attachment(id:$id){id ... on ImageAttachment{source{url}}}}"
)
ATTACH_MUT = (
    "mutation($i:UpdateAccessPassInput!){updateAccessPass(input:$i)"
    "{id title galleryImages{source{url}}}}"
)


def upload_image(url: str, filename: str = "cover.jpg",
                 content_type: str = "image/jpeg") -> str:
    """Mirror a publicly hosted image into Whop. Returns the `file_...` id."""
    data = _fetch(url)
    checksum = base64.b64encode(hashlib.md5(data).digest()).decode()
    up = _gql(UPLOAD_MUT, {"i": {
        "contentType": content_type,
        "byteSizeV2": str(len(data)),
        "checksum": checksum,
        "filename": filename,
        "record": "access_pass",
    }})["mediaDirectUpload"]

    put = urllib.request.Request(up["uploadUrl"], data=data, method="PUT")
    for k, v in (up.get("headers") or {}).items():
        put.add_header(k, v)
    with urllib.request.urlopen(put, timeout=180) as r:
        if r.status not in (200, 201):
            raise RuntimeError(f"S3 upload returned {r.status}")

    # Finalize, then resolve the signed blob id into the persistent file_ id.
    # Whop needs a beat to register the blob, so retry the lookup briefly.
    _gql(ANALYZE_MUT, {"i": {"directUploadId": up["id"], "mediaType": "image"}})
    last = None
    for attempt in range(6):
        try:
            att = _gql(ATTACHMENT_Q, {"id": up["id"]})["attachment"]
            if att and att.get("id"):
                return att["id"]
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(1 + attempt)
    raise RuntimeError(f"attachment did not resolve to a file id ({last})")


def set_product_gallery(product_id: str, image_urls: list[str]) -> dict:
    """Upload images and set them as the product gallery/cover.

    Returns {"status": "set"|"pending_manual"|"skipped", ...}. Never raises:
    a cover image is never worth failing a publish over.
    """
    if not image_urls:
        return {"status": "skipped", "reason": "no images"}
    if not _key():
        return {"status": "pending_manual", "reason": "WHOP_APP_API_KEY not set"}

    ids, errors = [], []
    for i, u in enumerate(image_urls):
        try:
            ids.append(upload_image(u, filename=f"cover-{i + 1}.jpg"))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{u}: {e}")

    if not ids:
        return {"status": "pending_manual", "reason": "; ".join(errors)[:300]}

    try:
        data = _gql(ATTACH_MUT, {"i": {
            "id": product_id,
            "galleryImages": [{"id": i} for i in ids],
        }})
        live = [g["source"]["url"]
                for g in (data["updateAccessPass"].get("galleryImages") or [])
                if g.get("source")]
        return {"status": "set", "attachments": ids, "urls": live}
    except Exception as e:  # noqa: BLE001
        # Most likely the app lacks `access_pass:update`. The bytes are already
        # in Whop, so this is recoverable by granting the scope and re-running.
        return {"status": "pending_manual", "attachments": ids,
                "reason": str(e)[:300]}
