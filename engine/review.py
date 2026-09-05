"""
review.py — paid-asset approval queue built on GitHub Issues.

- open_review_issue(): opens an Issue with previews; the bot comments
  "/approve" or "/reject <reason>" and the review-queue.yml workflow
  publishes or archives accordingly.
- The Issue body carries the full payload (JSON block) so the workflow
  needs no other state.
"""
import json
import os
import urllib.request

REPO = os.environ.get("GITHUB_REPOSITORY", "")  # owner/repo
DRY = os.environ.get("DRY_RUN") == "1"
LABELS = ["asset-review", "paid"]


def _gh(method: str, path: str, payload: dict | None = None) -> dict:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token or not REPO:
        raise RuntimeError("GH_TOKEN / GITHUB_REPOSITORY not set")
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}{path}",
        data=json.dumps(payload).encode() if payload else None,
        method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    if payload:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def open_review_issue(pack: dict, slug: str, price: float,
                      images: list[str], files: list[dict],
                      page_url: str, product_id: str = "") -> dict:
    body = f"""## Paid asset awaiting approval — `{slug}`

| | |
|---|---|
| **Title** | {pack['title']} |
| **Price** | ${price} |
| **Category** | {pack.get('category')} |
| **Prompts** | {len(pack.get('prompts', []))} |
| **Skills** | {len(pack.get('skills', []))} |

**Description:** {pack.get('description', '')}

**Images:**
{chr(10).join(f'- {i}' for i in images) or '- (none)'}

**Deliverables:** {len(files)} file(s)
{chr(10).join(f"- {f['name']}" for f in files) or '- (none)'}

*(Download links are deliberately omitted — this repo is public. Verified
2026-09-05 that published links let anyone download paid products for free.)*

{('**Whop page:** ' + page_url) if page_url else ''}

---
Comment **`/approve`** to publish to Whop, or **`/reject <reason>`** to archive.

```json
{json.dumps({"slug": slug, "pack": pack, "price": price,
             "images": images,
             "files": [{"name": f["name"]} for f in files],
             "page_url": page_url, "product_id": product_id})}
```
"""
    if DRY:
        print(f"[review] DRY issue would be opened: {body[:200]}...")
        return {"dry": True}
    issue = _gh("POST", "/issues", {"title": f"[Review] {pack['title']} (${price})",
                                    "body": body, "labels": LABELS})
    return {"number": issue["number"], "url": issue["html_url"]}


def close_issue(number: int, reason: str = "completed"):
    """Close a review issue. GitHub 422s on a bare {'state':'closed'} for some
    issue types, so send an explicit state_reason and fall back if rejected."""
    try:
        return _gh("PATCH", f"/issues/{number}",
                   {"state": "closed", "state_reason": reason})
    except Exception:
        return _gh("PATCH", f"/issues/{number}", {"state": "closed"})


def comment(number: int, text: str):
    return _gh("POST", f"/issues/{number}/comments", {"body": text})
