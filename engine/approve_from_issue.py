"""
approve_from_issue.py — runs inside review-queue.yml when you comment
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
    m = re.search(r"```json\s*(\{.*?\})\s*```", body, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def main():
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
    # dedup: if a previous /approve already published this issue, don't
    # create a second plan / duplicate publish
    comments = review._gh("GET", f"/issues/{number}/comments")
    if any("✅ Published!" in (c.get("body") or "") for c in comments):
        print(f"issue #{number} already published — skipping duplicate")
        return
    try:
        res = publish.approve(payload["product_id"], payload["price"],
                              payload.get("pack", {}).get("metadata"))
        review.comment(number, f"✅ Published! Plan `{res['plan_id']}` created at "
                               f"${payload['price']} and product is now visible.")
        # close the issue
        review._gh("PATCH", f"/issues/{number}", {"state": "closed"})
    except Exception as e:
        review.comment(number, f"❌ Publish failed: {e}")
        raise


if __name__ == "__main__":
    main()
