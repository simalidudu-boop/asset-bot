"""
react_webhook.py — Phase D reactions to Whop events (via Worker dispatch).

payment.succeeded        -> record sale; trigger upsell message (TODO spike:
                            confirm Whop messaging endpoint for bot->user DM;
                            fallback = forum post + email via Files-app notice).
membership.activated     -> record activation; append deliverable-links note.
All events are also appended to state/events.jsonl (permanent audit log).
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"
STATE.mkdir(exist_ok=True)
LOG = STATE / "events.jsonl"


def log_event(kind: str, payload: dict):
    entry = {"at": datetime.now(timezone.utc).isoformat(), "kind": kind,
             "payload": payload}
    with LOG.open("a") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    print(f"[webhook] {kind} logged: {json.dumps(payload, default=str)[:200]}")


def on_payment_succeeded(payload: dict):
    # TODO(spike): confirm the messaging API (POST /messages or similar).
    # Intent: DM the buyer with an upsell for the Pro version / custom work.
    data = payload.get("data", {})
    log_event("payment_succeeded", data)


def on_membership_activated(payload: dict):
    data = payload.get("data", {})
    # Deliverables are attached to the product (Files app / R2 links in
    # description). Add license-key ack here once messaging is confirmed.
    log_event("membership_activated", data)


HANDLERS = {
    "whop_payment_succeeded": on_payment_succeeded,
    "whop_membership_activated": on_membership_activated,
    "whop_membership_went_invalid": lambda p: log_event("membership_went_invalid", p.get("data", {})),
    "whop_payout_completed": lambda p: log_event("payout_completed", p.get("data", {})),
    "whop_unknown": lambda p: log_event("unknown", p),
}


def main():
    kind = os.environ.get("EVENT_TYPE", "whop_unknown")
    raw = os.environ.get("EVENT_PAYLOAD", "{}")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = {"raw": raw}
    handler = HANDLERS.get(kind, HANDLERS["whop_unknown"])
    handler(payload)


if __name__ == "__main__":
    main()
