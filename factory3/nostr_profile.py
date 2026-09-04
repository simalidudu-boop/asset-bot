"""Publish the Nostr profile (kind 0) with the Lightning address.

Zaps do NOT work from a note alone — a client shows the zap button only when
the AUTHOR'S PROFILE carries `lud16` (lightning address) or `lud12` (BOLT12
offer). This publishes/refreshes that profile.

Run after changing LIGHTNING_ADDRESS:
    python3 engine/nostr_profile.py
"""
from __future__ import annotations

import hashlib
import json
import os
import time

from dist_core import env

RELAYS = ("wss://nos.lol", "wss://relay.damus.io",
          "wss://nostr.mom", "wss://relay.nostr.band")


def publish(dry: bool = False) -> dict:
    import secp256k1
    from websocket import create_connection

    from dist_channels import _bech32_decode_to_hex

    sk = _bech32_decode_to_hex(env("NOSTR_NSEC"))
    if len(sk) != 64:
        return {"ok": False, "error": "bad NOSTR_NSEC"}
    priv = secp256k1.PrivateKey(bytes.fromhex(sk))
    pub = priv.pubkey.serialize()[1:].hex()

    profile = {
        "name": env("NOSTR_NAME") or "assetbot",
        "display_name": env("NOSTR_DISPLAY") or "The Algorithmic Daemon Concern",
        "about": env("NOSTR_ABOUT")
        or "Free AI prompt packs, shipped daily. Zaps appreciated.",
        "website": env("PACK_PAGE_BASE",
                       ) or "https://asset-bot-edge.simalidudu.workers.dev/p",
    }
    ln = env("LIGHTNING_ADDRESS")
    if ln and "@" in ln:
        profile["lud16"] = ln          # LUD-16 — what enables zaps
    if env("BOLT12_OFFER"):
        profile["lud12"] = env("BOLT12_OFFER")

    if dry:
        return {"ok": True, "dry": True, "profile": profile}

    created = int(time.time())
    ser = json.dumps([0, pub, created, 0, [], json.dumps(profile)],
                     separators=(",", ":"), ensure_ascii=False)
    eid = hashlib.sha256(ser.encode()).hexdigest()
    sig = priv.schnorr_sign(bytes.fromhex(eid), None, raw=True).hex()
    ev = {"id": eid, "pubkey": pub, "created_at": created, "kind": 0,
          "tags": [], "content": json.dumps(profile), "sig": sig}

    ok = 0
    for r in RELAYS:
        try:
            ws = create_connection(r, timeout=12)
            ws.send(json.dumps(["EVENT", ev]))
            resp = ws.recv()
            ws.close()
            if '"OK"' in resp and "true" in resp:
                ok += 1
        except Exception:  # noqa: BLE001
            continue
    print(f"[nostr] profile published to {ok}/{len(RELAYS)} relays "
          f"(lud16={'yes' if 'lud16' in profile else 'NO'})")
    return {"ok": ok > 0, "relays": ok, "pubkey": pub, "profile": profile}


if __name__ == "__main__":  # pragma: no cover
    print(json.dumps(publish(), indent=2))
