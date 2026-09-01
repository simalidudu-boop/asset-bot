"""
hosting.py — $0 media & deliverable hosting on GitHub Releases.

Replaces R2 (which Cloudflare gates behind a payment method): public repos
host release assets for free with stable public download URLs and correct
content types. One rolling release per ISO week.

Usage (from run_daily.py, GitHub Actions env):
    urls = upload_files(slug, [pdf, docx, zip, html paths])  # -> [{name,url}]
    img  = upload_images(slug, [image paths])                # -> [url]
    vid  = upload_asset(...)                                 # -> url
"""
import json
import os
import urllib.parse
import urllib.request
import urllib.error
from datetime import date
from pathlib import Path

REPO = os.environ.get("GITHUB_REPOSITORY", "simalidudu-boop/asset-bot")

CTYPES = {
    ".pdf": "application/pdf",
    ".zip": "application/zip",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".html": "text/html",
    ".md": "text/markdown",
    ".mp4": "video/mp4",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".txt": "text/plain",
}


def _token() -> str:
    t = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not t:
        raise RuntimeError("GH_TOKEN not set (needed for release uploads)")
    return t


def _gh(method: str, path: str, payload: dict | None = None,
        host: str = "https://api.github.com") -> dict:
    req = urllib.request.Request(
        f"{host}{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method)
    req.add_header("Authorization", f"Bearer {_token()}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "asset-bot")
    if payload is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read()) if r.status != 204 else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"GitHub {method} {path} -> {e.code}: {body[:300]}")


def weekly_tag() -> str:
    today = date.today()
    iso = today.isocalendar()
    return f"deliveries-{iso.year}-W{iso.week:02d}"


def ensure_release(tag: str) -> int:
    """Get-or-create the rolling weekly release. Returns release id."""
    try:
        rel = _gh("GET", f"/repos/{REPO}/releases/tags/{tag}")
        return rel["id"]
    except RuntimeError as e:
        if "404" not in str(e):
            raise
    rel = _gh("POST", f"/repos/{REPO}/releases", {
        "tag_name": tag,
        "name": tag,
        "body": "Auto-generated deliverable & media hosting for the asset bot.",
        "draft": False,
    })
    return rel["id"]


def upload_asset(release_id: int, path: Path, name: str | None = None,
                 content_type: str | None = None) -> str:
    """Upload one file; returns its public download URL."""
    name = name or path.name
    ctype = content_type or CTYPES.get(path.suffix.lower(),
                                       "application/octet-stream")
    data = path.read_bytes()
    for attempt in range(2):
        url = ("https://uploads.github.com/repos/" + REPO +
               f"/releases/{release_id}/assets?name={urllib.parse.quote(name)}")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Authorization", f"Bearer {_token()}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", "asset-bot")
        req.add_header("Content-Type", ctype)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read())["browser_download_url"]
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            if e.code == 422 and attempt == 0:  # name collision -> suffix
                stem = Path(name).stem
                name = f"{stem}-v2{Path(name).suffix}"
                continue
            raise RuntimeError(f"asset upload failed ({e.code}): {body[:300]}")


def upload_files(slug: str, paths: list[Path]) -> list[dict]:
    """Upload deliverable files; returns [{name, url}]."""
    if not paths:
        return []
    tag = weekly_tag()
    rid = ensure_release(tag)
    out = []
    for p in paths:
        if not p.exists():
            continue
        url = upload_asset(rid, p, name=f"{slug}/{p.name}")
        out.append({"name": p.name, "url": url})
    return out


def upload_images(slug: str, image_paths: list[Path]) -> list[str]:
    """Upload promo images; returns list of public URLs."""
    if not image_paths:
        return []
    tag = weekly_tag()
    rid = ensure_release(tag)
    out = []
    for i, p in enumerate(image_paths):
        if not p.exists():
            continue
        out.append(upload_asset(rid, p, name=f"{slug}/{slug}-img-{i + 1}.jpg"))
    return out


def upload_video(slug: str, video_path: Path) -> str | None:
    if not video_path or not video_path.exists():
        return None
    rid = ensure_release(weekly_tag())
    return upload_asset(rid, video_path, name=f"{slug}/{video_path.name}")
