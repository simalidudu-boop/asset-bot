"""
preflight.py — fail fast, fail loud.

Historically the bot degraded silently: a missing secret meant an image was
skipped, a dead provider meant a template fallback, a stale manifest meant
posts pointed at products that never existed. Every one of those looked like
a green run.

This module runs before the real work and classifies the environment:
  FATAL   -> the run cannot do its job; raise and let the workflow go red.
  WARN    -> degraded but useful; log loudly and continue.

Usage:
    import preflight
    preflight.check("daily")     # or "content"
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"

# secret -> (required_for, human hint)
REQUIRED = {
    "daily": ["WHOP_API_KEY", "WHOP_COMPANY_ID", "GH_TOKEN", "GITHUB_REPOSITORY"],
    "content": ["WHOP_API_KEY", "WHOP_COMPANY_ID"],
}
RECOMMENDED = {
    "daily": ["CF_API_TOKEN", "CF_ACCOUNT_ID", "PRODUCT_PAGE_BASE", "OWN_FORUM_ID"],
    "content": ["CF_API_TOKEN", "CF_ACCOUNT_ID", "GH_TOKEN",
                "PRODUCT_PAGE_BASE", "OWN_FORUM_ID", "PUBLIC_FORUM_ID"],
}
LLM_KEYS = ["MISTRAL_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY",
            "XAI_API_KEY", "CF_API_TOKEN"]


class PreflightError(RuntimeError):
    pass


def _log(level: str, msg: str):
    prefix = {"FATAL": "::error::", "WARN": "::warning::", "OK": ""}[level]
    print(f"{prefix}[preflight] {level}: {msg}")


def _check_secrets(phase: str) -> list[str]:
    problems = []
    for k in REQUIRED.get(phase, []):
        if not os.environ.get(k):
            problems.append(f"missing required secret {k}")
    for k in RECOMMENDED.get(phase, []):
        if not os.environ.get(k):
            _log("WARN", f"{k} not set — related features are disabled")
    return problems


def _check_llm() -> list[str]:
    present = [k for k in LLM_KEYS if os.environ.get(k)]
    if not present:
        if os.environ.get("MOCK") == "1":
            _log("WARN", "no LLM keys, but MOCK=1 — using canned content")
            return []
        return ["no LLM provider keys at all — every generation would "
                "fall back to templates"]
    _log("OK", f"LLM providers available: {', '.join(present)}")
    if len(present) == 1:
        _log("WARN", f"only one LLM provider ({present[0]}) — no failover")
    return []


def _check_manifest() -> list[str]:
    """The manifest drives what gets promoted. Catch the exact corruption
    classes we have actually been bitten by."""
    mf = STATE / "manifest.json"
    if not mf.exists():
        _log("WARN", "no manifest yet — first run?")
        return []
    try:
        m = json.loads(mf.read_text())
    except json.JSONDecodeError as e:
        return [f"manifest.json is not valid JSON: {e}"]

    assets = m.get("assets", [])
    problems = []
    slugs = [a.get("slug") for a in assets]
    dupes = {s for s in slugs if slugs.count(s) > 1}
    if dupes:
        problems.append(f"duplicate slugs in manifest: {sorted(dupes)} "
                        "(one slug must map to exactly one product)")

    missing_fields = [a.get("slug") for a in assets
                      if not all(k in a for k in ("free", "status", "product_id"))]
    if missing_fields:
        problems.append(f"assets missing free/status/product_id: {missing_fields}")

    orphans = [a.get("slug") for a in assets if a.get("status") == "orphaned"]
    if orphans:
        _log("WARN", f"{len(orphans)} orphaned asset(s) excluded from promotion: "
                     f"{orphans}")

    promotable = [a for a in assets
                  if a.get("free") is True
                  and (a.get("page_url") or a.get("product_id"))]
    if not promotable:
        _log("WARN", "no promotable free assets — content runs will no-op")
    else:
        _log("OK", f"{len(promotable)} promotable free asset(s)")
    return problems


def _check_links(timeout: int = 20) -> list[str]:
    """A post that links to a 404 is worse than no post. Verify live pages."""
    if os.environ.get("SKIP_LINK_CHECK") == "1" or os.environ.get("MOCK") == "1":
        return []
    mf = STATE / "manifest.json"
    if not mf.exists():
        return []
    try:
        assets = json.loads(mf.read_text()).get("assets", [])
    except Exception:
        return []
    for a in assets:
        url = a.get("page_url")
        if not url or a.get("free") is not True:
            continue
        try:
            req = urllib.request.Request(url, method="HEAD",
                                         headers={"User-Agent": "Mozilla/5.0 (asset-bot)"})
            code = urllib.request.urlopen(req, timeout=timeout).status
            if code >= 400:
                _log("WARN", f"asset page returned {code}: {url}")
            else:
                _log("OK", f"asset page {code}: {url}")
        except urllib.error.HTTPError as e:
            _log("WARN", f"asset page HTTP {e.code}: {url}")
        except Exception as e:
            _log("WARN", f"could not verify {url}: {e}")
    return []


def check(phase: str, strict: bool | None = None) -> dict:
    """Run all checks. Raises PreflightError on FATAL unless strict=False."""
    if strict is None:
        strict = os.environ.get("PREFLIGHT_STRICT", "1") == "1"
    print(f"[preflight] phase={phase} strict={strict}")
    problems: list[str] = []
    problems += _check_secrets(phase)
    problems += _check_llm()
    problems += _check_manifest()
    problems += _check_links()

    for p in problems:
        _log("FATAL", p)
    if problems and strict:
        try:
            import resilience as rz
            rz.alert("PREFLIGHT FAILED — run aborted",
                     "\n".join(f"- {p}" for p in problems)[:1500],
                     level="error", dedupe="preflight")
        except Exception:  # noqa: BLE001
            pass
        raise PreflightError(f"{len(problems)} fatal problem(s); aborting before "
                             "doing damage. See ::error:: lines above.")
    if not problems:
        _log("OK", "all checks passed")
    return {"phase": phase, "problems": problems}


if __name__ == "__main__":
    ph = sys.argv[1] if len(sys.argv) > 1 else "content"
    try:
        check(ph)
    except PreflightError as e:
        print(f"preflight failed: {e}")
        sys.exit(1)
