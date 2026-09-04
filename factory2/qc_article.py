"""Quality gate for Factory 2 articles.

Factory 1's QC checks prompt counts and pack shape — meaningless here. An
article fails for different reasons: it is thin, it is hype, it invented a
statistic, or it forgot the affiliate disclosure.

Deterministic only. No LLM judging an LLM.
"""
from __future__ import annotations

import re

MIN_SECTIONS = 3
MIN_SECTION_CHARS = 400
MIN_TOTAL_CHARS = 2000
MIN_TITLE = 15
MAX_TITLE = 90

# Model leakage / placeholder text.
_LEAK = re.compile(
    r"\bas an ai\b|\bi'm sorry\b|\bi cannot\b|\blorem ipsum\b|\bplaceholder\b"
    r"|\bTODO\b|\[insert|\{\{.*?\}\}|\byour (?:topic|title) here\b", re.I)

# Hype that destroys credibility with a technical Bitcoin audience.
_HYPE = re.compile(
    r"\bgame[- ]chang\w+|\brevolutionis\w+|\brevoluti(?:on|onize)\w*\b"
    r"|\bin today's fast[- ]paced\b|\bunlock the power\b|\bsupercharge\b"
    r"|\bdelve into\b|\bin conclusion,", re.I)

# Claims we must never make from a sanctioned jurisdiction.
_DANGER = re.compile(
    r"\bevade sanctions\b|\bbypass sanctions\b|\bavoid detection\b"
    r"|\blaunder\b|\bhide (?:your )?(?:funds|identity) from\b", re.I)


def _text_of(a: dict) -> str:
    parts = [a.get("title", ""), a.get("subtitle", ""), a.get("summary", "")]
    parts += [s.get("heading", "") + " " + s.get("body", "")
              for s in (a.get("sections") or [])]
    parts += [f.get("question", "") + " " + f.get("answer", "")
              for f in (a.get("faq") or [])]
    return "\n".join(parts)


def check(a: dict) -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(a, dict):
        return {"ok": False, "errors": ["article is not a dict"],
                "warnings": [], "score": 0}

    title = (a.get("title") or "").strip()
    if not (MIN_TITLE <= len(title) <= MAX_TITLE):
        errors.append(f"title length {len(title)} outside {MIN_TITLE}-{MAX_TITLE}")

    sections = a.get("sections") or []
    if len(sections) < MIN_SECTIONS:
        errors.append(f"only {len(sections)} sections (need >= {MIN_SECTIONS})")

    for i, s in enumerate(sections):
        body = (s.get("body") or "").strip()
        if len(body) < MIN_SECTION_CHARS:
            errors.append(f"section[{i}] '{(s.get('heading') or '')[:24]}' thin "
                          f"({len(body)} < {MIN_SECTION_CHARS} chars)")
        # a paragraph repeated to pad length
        paras = [p.strip() for p in body.split("\n") if p.strip()]
        if len(paras) > 1 and len(set(paras)) == 1:
            errors.append(f"section[{i}] is one paragraph repeated")

    text = _text_of(a)
    if len(text) < MIN_TOTAL_CHARS:
        errors.append(f"article too short overall ({len(text)} < {MIN_TOTAL_CHARS})")

    if m := _LEAK.search(text):
        errors.append(f"model leakage/placeholder: {m.group(0)!r}")
    if m := _DANGER.search(text):
        errors.append(f"UNSAFE CLAIM: {m.group(0)!r} — must never be published")

    hype = _HYPE.findall(text)
    if len(hype) >= 3:
        errors.append(f"hype language x{len(hype)}: {hype[:3]}")
    elif hype:
        warnings.append(f"hype language: {hype}")

    if not a.get("faq"):
        warnings.append("no FAQ section")
    if not a.get("comparison"):
        warnings.append("no comparison table")
    if not a.get("programmes"):
        warnings.append("no affiliate programmes attached — article cannot earn")

    # Every praised tool should carry a caveat somewhere.
    if a.get("comparison"):
        no_note = [c.get("name") for c in a["comparison"]
                   if not (c.get("note") or "").strip()]
        if no_note:
            warnings.append(f"no honest note for: {no_note}")

    score = max(0, 100 - 25 * len(errors) - 5 * len(warnings))
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "score": score}


def gate(a: dict, slug: str, strict: bool = True) -> bool:
    r = check(a)
    for w in r["warnings"]:
        print(f"[qc2] WARN  {slug}: {w}")
    for e in r["errors"]:
        print(f"[qc2] ERROR {slug}: {e}")
    verdict = "PASS" if r["ok"] else ("BLOCK" if strict else "PASS(non-strict)")
    print(f"[qc2] {slug}: {verdict} score={r['score']}/100")
    return r["ok"] or not strict
