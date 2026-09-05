"""Distribution core — durable queue, channel registry, retry semantics.

Design borrowed from Grain Works Factory v3.3.0 (see docs/DISTRIBUTION_V2.md).

Three ideas, all of which we were missing:

  1. **Durable queue.** Enqueue is cheap and does no network I/O. A bounded
     worker drains jobs with persisted backoff, so a crashed run never
     double-posts and never loses work. Posting inline (what we did before)
     means one slow channel stalls the whole daily run.

  2. **Permanent vs retryable.** Every adapter returns the same shape and
     says whether a failure is worth retrying. A 403 on a missing permission
     must never be retried 5 times; a 502 should be.

  3. **Channel registry.** Adding a channel = write an adapter + add one line.
     Channels whose credentials are absent are SKIPPED silently, never failed,
     so the operator can switch them on one key at a time.

Posting mode is per-channel and defaults to DRAFT (queue only, never post).
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

STATE = Path(__file__).resolve().parent.parent / "state"
QUEUE = STATE / "dist_queue.jsonl"

MAX_ATTEMPTS = 5
DEFAULT_MAX_PER_RUN = int(os.environ.get("DIST_MAX_PER_RUN", "25"))

# HTTP codes that mean "this will never succeed — stop trying".
# 429 is explicitly NOT here: it is the canonical retryable code.
PERMANENT_CODES = {400, 401, 403, 404, 405, 409, 410, 422}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts() -> float:
    return time.time()


# ---------------------------------------------------------------- result ---
def result(ok: bool, remote_id: str = "", remote_url: str = "",
           error: str = "", permanent: bool = False,
           skipped: bool = False) -> dict:
    """Uniform adapter return value.

    `skipped` means "this channel does not apply to this asset" — e.g. a
    YouTube job for an asset with no video. That is NOT a failure, and
    counting it as one buried three real problems in the dashboard.
    """
    return {"ok": bool(ok), "remote_id": remote_id or "",
            "remote_url": remote_url or "", "error": (error or "")[:300],
            "permanent": bool(permanent), "skipped": bool(skipped)}


def is_permanent(code: int) -> bool:
    return code in PERMANENT_CODES


# ------------------------------------------------------------------ http ---
def http(method: str, url: str, *, headers: dict | None = None,
         json_body: dict | None = None, form: dict | None = None,
         data: bytes | None = None, timeout: int = 60) -> tuple[int, str]:
    """One HTTP call. Returns (status, body). Never raises on HTTP errors."""
    hdrs = {"User-Agent": "asset-bot/1.0"}
    hdrs.update(headers or {})
    body = data
    if json_body is not None:
        body = json.dumps(json_body).encode()
        hdrs.setdefault("Content-Type", "application/json")
    elif form is not None:
        body = urllib.parse.urlencode(form).encode()
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")

    if not url or not str(url).startswith(("http://", "https://")):
        # A missing/blank endpoint must be a clean failure, not a ValueError
        # that escapes the adapter.
        return 0, f"invalid url: {url!r}"
    req = urllib.request.Request(url, data=body, method=method.upper())
    for k, v in hdrs.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except Exception as e:  # noqa: BLE001  (DNS, TLS, timeout -> retryable)
        return 0, str(e)


def jbody(text: str) -> dict:
    try:
        v = json.loads(text)
        return v if isinstance(v, dict) else {"_": v}
    except Exception:  # noqa: BLE001
        return {}


def from_http(code: int, text: str, *, ok_codes=(200, 201, 202),
              id_key: str = "id", url_key: str = "url") -> dict:
    """Map a raw HTTP response onto a uniform result."""
    b = jbody(text)
    if code in ok_codes:
        return result(True, str(b.get(id_key, "")), str(b.get(url_key, "")))
    msg = (b.get("error") or b.get("message") or text or "")
    if isinstance(msg, dict):
        msg = msg.get("message") or json.dumps(msg)
    return result(False, error=f"http_{code}: {msg}", permanent=is_permanent(code))


# ------------------------------------------------------------------ mode ---
def mode(channel: str) -> str:
    """DRAFT (queue only) or LIVE, per channel then global. Default DRAFT."""
    v = (os.environ.get(f"DIST_MODE_{channel.upper()}")
         or os.environ.get("DIST_POSTING_MODE") or "DRAFT")
    return "LIVE" if str(v).strip().upper() == "LIVE" else "DRAFT"


def env(*names: str) -> str:
    for n in names:
        v = os.environ.get(n, "").strip()
        if v:
            return v
    return ""


def has_keys(channel: str) -> bool:
    """True only if every credential the channel declares is present."""
    spec = CHANNELS.get(channel)
    if not spec:
        return False
    return all(env(*k) if isinstance(k, tuple) else env(k)
               for k in spec["keys"])


# ----------------------------------------------------------------- queue ---
def _read() -> list[dict]:
    if not QUEUE.exists():
        return []
    rows = []
    for line in QUEUE.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except Exception:  # noqa: BLE001  skip a corrupt line, keep the rest
                continue
    return rows


def _write(rows: list[dict]) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    QUEUE.write_text("".join(json.dumps(r) + "\n" for r in rows))


def enqueue(asset: dict, channels: list[str] | None = None) -> int:
    """Queue one asset for every eligible channel. No network I/O."""
    rows = _read()
    seen = {(r["slug"], r["channel"]) for r in rows}
    want = channels or list(CHANNELS)
    added = 0
    for ch in want:
        if ch not in CHANNELS:
            print(f"[dist] unknown channel {ch!r} — skipped")
            continue
        if not has_keys(ch):
            continue  # not configured: skip silently, never fail
        key = (asset.get("slug", ""), ch)
        if key in seen:
            continue
        rows.append({
            "slug": asset.get("slug", ""),
            "channel": ch,
            "status": "pending",
            "attempts": 0,
            "next_at": 0,
            "queued_at": _now(),
            "remote_url": "",
            "error": "",
            "asset": asset,
        })
        seen.add(key)
        added += 1
    _write(rows)
    print(f"[dist] queued {added} job(s) for {asset.get('slug')}")
    return added


def drain(max_jobs: int | None = None) -> dict:
    """Run due jobs. Bounded, resumable, never raises."""
    cap = max_jobs or DEFAULT_MAX_PER_RUN
    rows = _read()
    stats = {"posted": 0, "failed": 0, "skipped": 0, "drafted": 0}
    now = _ts()
    done = 0

    for r in rows:
        if done >= cap:
            break
        if r.get("status") not in ("pending", "retry"):
            continue
        if r.get("next_at", 0) > now:
            continue
        ch = r["channel"]
        spec = CHANNELS.get(ch)
        if not spec or not has_keys(ch):
            r["status"] = "skipped"
            stats["skipped"] += 1
            continue

        if mode(ch) != "LIVE":
            # DRAFT: leave the job queued so a later LIVE run picks it up.
            stats["drafted"] += 1
            continue

        done += 1
        r["attempts"] = r.get("attempts", 0) + 1
        try:
            res = spec["fn"](r["asset"])
        except Exception as e:  # noqa: BLE001  an adapter must never kill the run
            res = result(False, error=f"adapter raised: {e}")

        if res.get("skipped"):
            r.update(status="skipped", error=res.get("error", ""))
            stats["skipped"] += 1
            print(f"[dist] {ch}: n/a for {r['slug']} — {res.get('error','')[:60]}")
        elif res.get("ok"):
            r.update(status="posted", remote_url=res.get("remote_url", ""),
                     remote_id=res.get("remote_id", ""), error="",
                     posted_at=_now())
            stats["posted"] += 1
            print(f"[dist] {ch}: posted {r['slug']} -> {res.get('remote_url','')}")
        else:
            r["error"] = res.get("error", "")
            if res.get("permanent") or r["attempts"] >= MAX_ATTEMPTS:
                r["status"] = "failed"
                stats["failed"] += 1
                why = "permanent" if res.get("permanent") else "max attempts"
                print(f"[dist] {ch}: FAILED ({why}) {r['slug']}: {r['error']}")
                try:
                    import resilience as rz
                    rz.alert(f"Channel dead: {ch}",
                             f"`{r['slug']}` failed ({why})\n`{r['error'][:300]}`",
                             level="warn", dedupe=f"chan:{ch}:{why}")
                except Exception:  # noqa: BLE001
                    pass
            else:
                # exponential backoff: 1, 2, 4, 8 minutes
                r["status"] = "retry"
                r["next_at"] = now + 60 * (2 ** (r["attempts"] - 1))
                print(f"[dist] {ch}: retry {r['attempts']}/{MAX_ATTEMPTS} "
                      f"{r['slug']}: {r['error']}")
        time.sleep(0.4)  # be polite to every host

    _write(rows)
    print(f"[dist] drain: {stats}")
    # Every live channel failing at once means a systemic problem (network,
    # secrets wiped, clock skew) rather than one flaky provider.
    if stats["failed"] and not stats["posted"] and stats["failed"] >= 3:
        try:
            import resilience as rz
            rz.alert("Distribution wholly failing",
                     f"{stats['failed']} channel jobs failed and none "
                     "succeeded in this drain.", level="error",
                     dedupe="dist-total-failure")
        except Exception:  # noqa: BLE001
            pass
    return stats


def queue_stats() -> dict:
    from collections import Counter
    rows = _read()
    return {"total": len(rows),
            "by_status": dict(Counter(r.get("status") for r in rows)),
            "by_channel": dict(Counter(r.get("channel") for r in rows))}


# Registry is populated by dist_channels.py to avoid a circular import.
CHANNELS: dict[str, dict] = {}


def register(name: str, fn, keys: list) -> None:
    CHANNELS[name] = {"fn": fn, "keys": keys}


def _cli() -> None:  # pragma: no cover
    """CLI entry. Lives in a function so `python dist_core.py` and
    `import dist_core` share ONE module object — running the file directly
    creates a second `__main__` copy whose CHANNELS dict is empty."""
    import sys
    import dist_channels  # noqa: F401  registers adapters
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        print(json.dumps(queue_stats(), indent=2))
        print("\nchannels:")
        for name in sorted(CHANNELS):
            print(f"  {name:10} keys={'yes' if has_keys(name) else 'NO '}  "
                  f"mode={mode(name)}")
    elif cmd == "drain":
        drain(int(sys.argv[2]) if len(sys.argv) > 2 else None)
    elif cmd == "retry-failed":
        rows = _read()
        n = 0
        for r in rows:
            if r.get("status") == "failed":
                r.update(status="pending", attempts=0, next_at=0)
                n += 1
        _write(rows)
        print(f"reset {n} failed job(s)")
    else:
        print("usage: dist_core.py [status|drain [n]|retry-failed]")


if __name__ == "__main__":  # pragma: no cover
    from importlib import import_module
    import_module("dist_core")._cli()
