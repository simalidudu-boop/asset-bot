"""Quality control — reject bad assets BEFORE they reach customers.

Why this exists
---------------
On 2026-09-04 the daily cycle reported **success** while producing **0/3
assets** (every pack died on truncated LLM JSON). Nothing noticed. That is the
real failure mode of this factory: it fails silently and green-lights itself.

Worse, the opposite is equally possible — a pack that *parses* but is garbage
(placeholder text, 2 prompts instead of 10, a title the model apologised in)
would sail straight to a paying customer.

QC is two gates:

  1. `check_pack()`   — structural + content validation of a generated pack.
                        Blocks publication of anything broken.
  2. `check_run()`    — run-level assertion. If a cycle produced nothing when
                        it was supposed to produce something, FAIL LOUDLY so
                        the workflow goes red instead of lying.

Design rules:
  * Deterministic. No LLM judges an LLM — that just adds a second thing to
    debug and costs money.
  * Every failure names the field and the reason.
  * `severity`: "error" blocks publication, "warn" is logged and shipped.
"""
from __future__ import annotations

import re

# Phrases that mean the model talked to us instead of producing a product.
_LEAK_PATTERNS = [
    r"\bas an ai\b", r"\bi'm sorry\b", r"\bi cannot\b", r"\bi apologi[sz]e\b",
    r"\bhere (?:is|are) (?:the|your)\b", r"\bcertainly[!,]", r"\bsure[!,] here\b",
    r"\blorem ipsum\b", r"\bplaceholder\b", r"\byour (?:topic|title) here\b",
    r"\bTODO\b", r"\bXXX\b", r"\[insert\b", r"\{\{.*?\}\}",
]
_LEAK_RE = re.compile("|".join(_LEAK_PATTERNS), re.I)

# Minimums for a pack we would be willing to charge for.
MIN_PROMPTS = 5
MIN_PROMPT_CHARS = 80
MIN_DESC_CHARS = 120
MIN_TITLE_CHARS = 8
MAX_TITLE_CHARS = 90


def _txt(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def check_pack(pack: dict, *, paid: bool = False) -> dict:
    """Validate a generated pack. Returns {ok, errors[], warnings[], score}."""
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(pack, dict):
        return {"ok": False, "errors": ["pack is not a dict"],
                "warnings": [], "score": 0}

    # ---- required top-level fields
    title = _txt(pack.get("title"))
    subtitle = _txt(pack.get("subtitle"))
    desc = _txt(pack.get("description"))

    if len(title) < MIN_TITLE_CHARS:
        errors.append(f"title too short ({len(title)} < {MIN_TITLE_CHARS})")
    if len(title) > MAX_TITLE_CHARS:
        warnings.append(f"title very long ({len(title)} chars)")
    if not subtitle:
        errors.append("subtitle missing")
    if len(desc) < MIN_DESC_CHARS:
        errors.append(f"description too short ({len(desc)} < {MIN_DESC_CHARS})")

    # ---- model leakage / placeholders anywhere in the text
    for field, val in (("title", title), ("subtitle", subtitle),
                       ("description", desc)):
        m = _LEAK_RE.search(val)
        if m:
            errors.append(f"{field} contains model leakage/placeholder: "
                          f"{m.group(0)!r}")

    # ---- prompts: the actual product
    prompts = pack.get("prompts")
    if not isinstance(prompts, list):
        errors.append("prompts missing or not a list")
        prompts = []
    elif len(prompts) < MIN_PROMPTS:
        errors.append(f"only {len(prompts)} prompts (need >= {MIN_PROMPTS})")

    seen: set[str] = set()
    for i, p in enumerate(prompts):
        if not isinstance(p, dict):
            errors.append(f"prompt[{i}] is not an object")
            continue
        body = _txt(p.get("prompt"))
        ptitle = _txt(p.get("title"))
        if len(body) < MIN_PROMPT_CHARS:
            errors.append(f"prompt[{i}] '{ptitle[:24]}' too short "
                          f"({len(body)} < {MIN_PROMPT_CHARS} chars)")
        if not ptitle:
            warnings.append(f"prompt[{i}] has no title")
        m = _LEAK_RE.search(body)
        if m:
            errors.append(f"prompt[{i}] contains {m.group(0)!r}")
        key = body[:120].lower()
        if key and key in seen:
            errors.append(f"prompt[{i}] duplicates an earlier prompt")
        seen.add(key)

    # ---- FAQ (we generate it; it should exist)
    faq = pack.get("faq") or []
    if len(faq) < 3:
        warnings.append(f"only {len(faq)} FAQ entries")

    # ---- paid products are held to a higher bar
    if paid:
        if len(prompts) < MIN_PROMPTS + 3:
            warnings.append(f"paid pack has only {len(prompts)} prompts")
        if not pack.get("skills"):
            warnings.append("paid pack has no skills section")

    score = max(0, 100 - 25 * len(errors) - 5 * len(warnings))
    return {"ok": not errors, "errors": errors,
            "warnings": warnings, "score": score}


def gate(pack: dict, slug: str, *, paid: bool = False,
         strict: bool = True) -> bool:
    """Log the QC verdict. Returns False when the asset must NOT be published."""
    r = check_pack(pack, paid=paid)
    for w in r["warnings"]:
        print(f"[qc] WARN  {slug}: {w}")
    for e in r["errors"]:
        print(f"[qc] ERROR {slug}: {e}")
    verdict = "PASS" if r["ok"] else ("BLOCK" if strict else "PASS(non-strict)")
    print(f"[qc] {slug}: {verdict} score={r['score']}/100 "
          f"({len(r['errors'])} error(s), {len(r['warnings'])} warning(s))")
    return r["ok"] or not strict


def check_run(produced: int, attempted: int, *, phase: str = "daily") -> None:
    """Fail the process when a run silently produced nothing.

    This is the guard that was missing: the 2026-09-04 cycle attempted 3
    assets, produced 0, and still exited 0 — so the workflow went green and
    nobody knew the factory had stopped.
    """
    if attempted and produced == 0:
        try:
            import resilience as rz
            rz.alert("FACTORY IDLE — 0 assets produced",
                     f"Attempted {attempted}, produced 0. The run is being "
                     "failed deliberately so this is visible.",
                     level="error", dedupe="factory-idle")
        except Exception:  # noqa: BLE001
            pass
        raise SystemExit(
            f"[qc] {phase}: produced 0/{attempted} assets — failing the run "
            "so this is visible instead of a green tick on an idle factory")
    if attempted and produced < attempted:
        print(f"[qc] {phase}: partial run {produced}/{attempted} "
              "— check logs for the failed assets")
