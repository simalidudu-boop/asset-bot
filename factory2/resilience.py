"""Resilience primitives: alerting, retry, circuit breaking, safe fallback.

Why this exists
---------------
On 2026-09-04 the daily cycle produced 0/3 assets and reported SUCCESS. The
engine had **no alerting whatsoever** — every failure was a line in a log
nobody reads. This module makes failure loud and recoverable.

Four primitives, deliberately small:

  `alert()`      — critical errors to Discord. Deduplicated, never raises.
  `retry()`      — exponential backoff with jitter for transient faults.
  `first_ok()`   — try providers in order, return the first that works.
  `safe()`       — run something optional; log and continue on failure.

Design rules:
  * Nothing here may EVER raise into the caller. A broken alerting system
    must not break the factory.
  * Transient (5xx, timeout, 429) retries; permanent (4xx) does not.
  * Alerts are deduplicated within a run so one bad loop cannot spam Discord.
"""
from __future__ import annotations

import json
import os
import random
import time
import traceback
import urllib.error
import urllib.request

_SEEN: set[str] = set()          # dedupe key -> already alerted this run
_BREAKERS: dict[str, dict] = {}  # name -> {"fails": int, "until": float}

# Transient conditions worth retrying. 429 included: it means "later", not "no".
RETRYABLE_CODES = {408, 425, 429, 500, 502, 503, 504}
BREAKER_THRESHOLD = 3     # consecutive failures before a provider is skipped
BREAKER_COOLDOWN = 300    # seconds to leave it open


# ------------------------------------------------------------- alerting ---
def alert(title: str, detail: str = "", *, level: str = "error",
          dedupe: str | None = None) -> bool:
    """Send a critical alert to Discord. Never raises, never blocks a run."""
    key = dedupe or f"{level}:{title}"
    if key in _SEEN:
        return False
    _SEEN.add(key)

    hooks = [h.strip() for h in
             (os.environ.get("DISCORD_ALERT_WEBHOOK")
              or os.environ.get("DISCORD_PROMO_WEBHOOKS") or "").split(",")
             if h.strip()]
    colour = {"error": 0xE74C3C, "warn": 0xF39C12, "info": 0x3498DB}.get(
        level, 0xE74C3C)
    icon = {"error": "🚨", "warn": "⚠️", "info": "ℹ️"}[level] \
        if level in ("error", "warn", "info") else "🚨"

    run = os.environ.get("GITHUB_RUN_ID")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if run and repo:
        detail = f"{detail}\n\n[run log](https://github.com/{repo}/actions/runs/{run})"

    payload = {"embeds": [{
        "title": f"{icon} {title}"[:250],
        "description": (detail or "_no detail_")[:3800],
        "color": colour,
    }]}
    sent = False
    for hook in hooks:
        try:
            req = urllib.request.Request(
                hook, data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json",
                         "User-Agent": "asset-bot/1.0"}, method="POST")
            with urllib.request.urlopen(req, timeout=15):
                sent = True
        except Exception:  # noqa: BLE001  alerting must never break the caller
            continue
    print(f"[alert:{level}] {title} — {detail[:200]}")
    return sent


def alert_exc(title: str, exc: BaseException, *, dedupe: str | None = None) -> None:
    """Alert with a trimmed traceback attached."""
    tb = "".join(traceback.format_exception_type(type(exc))
                 if hasattr(traceback, "format_exception_type")
                 else traceback.format_exception(exc)[-4:])
    alert(title, f"`{type(exc).__name__}: {exc}`\n```\n{tb[-1200:]}\n```",
          level="error", dedupe=dedupe or f"{title}:{type(exc).__name__}")


# ---------------------------------------------------------------- retry ---
def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in RETRYABLE_CODES
    if isinstance(exc, (TimeoutError, ConnectionError, urllib.error.URLError)):
        return True
    msg = str(exc).lower()
    return any(w in msg for w in
               ("timed out", "timeout", "temporarily", "connection reset",
                "rate limit", "429", "503", "502", "504"))


def retry(fn, *, attempts: int = 3, base: float = 1.5, label: str = "op",
          on_fail=None):
    """Call fn() with exponential backoff + jitter on TRANSIENT failures only.

    A permanent error (4xx that is not 408/425/429) fails immediately —
    retrying a 403 five times just wastes the run's time budget.
    """
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            if not _is_retryable(e):
                print(f"[retry] {label}: permanent error, not retrying — {e}")
                break
            if i < attempts - 1:
                delay = base ** i + random.uniform(0, 0.6)
                print(f"[retry] {label}: attempt {i+1}/{attempts} failed "
                      f"({str(e)[:80]}), retrying in {delay:.1f}s")
                time.sleep(delay)
    if on_fail is not None:
        return on_fail(last)
    raise last  # type: ignore[misc]


# ------------------------------------------------------- circuit breaker ---
def breaker_open(name: str) -> bool:
    """True while a provider is being skipped.

    NOTE: only clear the record once the cooldown has actually STARTED
    (until > 0). Clearing on `time() >= until` when until is still 0 reset the
    failure count on every call, so the breaker could never trip.
    """
    b = _BREAKERS.get(name)
    if not b:
        return False
    if b["until"] and time.time() >= b["until"]:
        _BREAKERS.pop(name, None)     # cooled down, give it another chance
        return False
    return b["fails"] >= BREAKER_THRESHOLD


def breaker_record(name: str, ok: bool) -> None:
    if ok:
        _BREAKERS.pop(name, None)
        return
    b = _BREAKERS.setdefault(name, {"fails": 0, "until": 0.0})
    b["fails"] += 1
    if b["fails"] >= BREAKER_THRESHOLD:
        b["until"] = time.time() + BREAKER_COOLDOWN
        alert(f"Provider circuit opened: {name}",
              f"{b['fails']} consecutive failures — skipping for "
              f"{BREAKER_COOLDOWN}s.", level="warn", dedupe=f"breaker:{name}")


# ------------------------------------------------------------ fallbacks ---
def first_ok(providers, *, label: str = "provider", alert_on_exhaust: bool = True):
    """Try (name, callable) pairs in order; return (name, result) of the first
    that succeeds. Skips providers whose circuit is open.

    Raises RuntimeError only when EVERY provider failed — and alerts, because
    total exhaustion means the pipeline just lost a capability.
    """
    errs = []
    for name, fn in providers:
        if breaker_open(name):
            print(f"[fallback] {label}: skipping {name} (circuit open)")
            continue
        try:
            out = fn()
            breaker_record(name, True)
            if errs:
                print(f"[fallback] {label}: recovered via {name} "
                      f"after {len(errs)} failure(s)")
            return name, out
        except Exception as e:  # noqa: BLE001
            breaker_record(name, False)
            errs.append(f"{name}: {str(e)[:120]}")
            print(f"[fallback] {label}: {name} failed — {str(e)[:120]}")
    detail = "\n".join(f"- {e}" for e in errs) or "no providers configured"
    if alert_on_exhaust:
        alert(f"ALL {label} providers failed", detail, level="error",
              dedupe=f"exhaust:{label}")
    raise RuntimeError(f"all {label} providers failed: {errs}")


def safe(fn, *, label: str, default=None, warn: bool = True):
    """Run an OPTIONAL step. Never raises; returns `default` on failure.

    Use for anything that must not be able to fail the run — distribution,
    analytics, cosmetic extras.
    """
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        msg = f"{type(e).__name__}: {e}"
        print(f"[safe] {label} failed (continuing): {msg[:200]}")
        if warn:
            alert(f"Non-fatal: {label}", f"`{msg[:400]}`", level="warn",
                  dedupe=f"safe:{label}:{type(e).__name__}")
        return default
