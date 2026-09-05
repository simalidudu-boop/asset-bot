"""
reject_from_issue.py — runs inside review-queue.yml when you comment
/reject on a paid-asset review Issue. Closes the issue; the product stays
hidden on Whop (no plan, not visible).
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import review  # noqa: E402


def main() -> None:
    """Process reject comment event from review queue."""
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not event_path:
        print("no event path")
        return
    event = json.loads(Path(event_path).read_text())
    issue = event.get("issue", {})
    number = issue.get("number")

    try:
        issue_data = review._gh("GET", f"/issues/{number}")
        if issue_data.get("state") == "closed":
            print(f"issue #{number} is already closed — skipping reject")
            return
    except Exception as e:
        print(f"could not fetch issue state ({e}) — continuing reject")

    try:
        review.close_issue(number, reason="completed")
        review.comment(number, "Rejected — product stays hidden on Whop. "
                               "You can re-open this issue and /approve later.")
        print(f"issue #{number} closed (product stays hidden)")
    except Exception as e:
        review.comment(number, f"❌ Reject failed: {e}")
        raise


if __name__ == "__main__":
    main()
