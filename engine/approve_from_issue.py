"""approve_from_issue.py — runs inside review-queue.yml when you comment
/approve on a paid-asset review Issue.

Reads the Issue body (GITHUB_EVENT_PATH), extracts the JSON payload block,
creates the plan at the proposed price, and sets the product visible.
Then comments the outcome on the Issue.
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import publish  # noqa: E402
import review  # noqa: E402


def extract_payload(body: str) -> dict | None:
    """Extract and parse the JSON payload block from an issue body.

    Args:
        body: Markdown body of the GitHub issue.

    Returns:
        Dictionary representation of the payload or None if extraction fails.
    """
    m = re.search(r"```json\s*([\s\S]*?)\s*```", body)
    if not m:
        return None
    try:
        return json.loads(m.group(1).strip())
    except json.JSONDecodeError:
        return None


def update_manifest_asset(slug: str, updates: dict) -> None:
    """Reconcile and persist asset record updates in state/manifest.json.

    Args:
        slug: Product slug identifier.
        updates: Key-value updates to apply to the matching asset dictionary.
    """
    manifest_path = Path(__file__).resolve().parent.parent / "state" / "manifest.json"
    if not manifest_path.exists():
        return
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        for asset in data.get("assets", []):
            if asset.get("slug") == slug:
                asset.update(updates)
                break
        manifest_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except Exception as e:
        print(f"[manifest] update failed ({e}) — continuing")


def main() -> None:
    """Process approve comment event from review queue."""
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not event_path:
        print("no event path")
        return
    event = json.loads(Path(event_path).read_text())
    issue = event.get("issue", {})
    number = issue.get("number")
    comment_body = (event.get("comment", {}) or {}).get("body", "")
    if "/approve" not in comment_body:
        print("no /approve in comment")
        return

    payload = extract_payload(issue.get("body", ""))
    if not payload:
        review.comment(number, "❌ Could not read the payload block from the "
                               "issue body. Nothing was published.")
        return

    try:
        issue_data = review._gh("GET", f"/issues/{number}")
        if issue_data.get("state") == "closed":
            print(f"issue #{number} is already closed — skipping duplicate")
            return
    except Exception as e:
        print(f"could not fetch issue state ({e}) — checking comments")

    comments = review._gh("GET", f"/issues/{number}/comments")
    if any("✅ Published!" in (c.get("body") or "") for c in comments):
        print(f"issue #{number} already published — skipping duplicate")
        return

    try:
        metadata = {
            "slug": payload.get("slug"),
            "pack": payload.get("pack"),
            "page_url": payload.get("page_url"),
            "file_urls": payload.get("files") or payload.get("file_urls"),
            "image_urls": payload.get("images") or payload.get("image_urls"),
            "description": (payload.get("pack") or {}).get("description", ""),
        }
        res = publish.approve(payload["product_id"], payload["price"], metadata)
        review.comment(number, f"✅ Published! Plan `{res['plan_id']}` created at "
                               f"${payload['price']} and product is now visible.")

        update_manifest_asset(payload.get("slug"), {
            "status": "live",
            "price": float(payload["price"]),
            "marketplace_status": res.get("marketplace_status") or "pending_review",
            "files": payload.get("files", []),
            "release_images": payload.get("images", []),
        })

        try:
            review.close_issue(number)
        except Exception as e:
            print(f"[approve] publish OK but issue close failed ({e}) — ignoring")
    except Exception as e:
        review.comment(number, f"❌ Publish failed: {e}")
        raise


if __name__ == "__main__":
    main()
