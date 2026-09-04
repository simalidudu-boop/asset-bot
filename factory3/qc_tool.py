"""Quality gate for Factory 3 datasets/tools.

A developer audience verifies things. Shipping a dataset with 5 rows, or a
tool that does not import, costs more credibility than shipping nothing —
and credibility is the entire product here.

So this gate does something Factory 1 and 2 do not: it **executes the
generated code** in a temp directory against the generated data. If the tool
does not import and run, it does not ship.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

MIN_ROWS = 20
MIN_TOOL_CHARS = 150

_LEAK = re.compile(
    r"\bas an ai\b|\bi'm sorry\b|\blorem ipsum\b|\bplaceholder\b|\bTODO\b"
    r"|\bFIXME\b|\.\.\.\s*$|\byour[_ ]here\b|\{\{.*?\}\}", re.I | re.M)

# Third-party imports break "stdlib only" and will fail for users.
_STDLIB_OK = re.compile(
    r"^\s*(?:import|from)\s+(json|pathlib|os|sys|re|typing|collections|"
    r"itertools|functools|dataclasses|datetime|math|random|csv|hashlib|"
    r"textwrap|unittest|string|enum)\b")


def _check_imports(code: str) -> list:
    bad = []
    for line in code.splitlines():
        if re.match(r"^\s*(?:import|from)\s+", line):
            if not _STDLIB_OK.match(line) and "tool" not in line:
                bad.append(line.strip()[:60])
    return bad


def run_smoke_test(d: dict) -> tuple[bool, str]:
    """Actually execute the generated tool against the generated data."""
    rows = d.get("rows") or []
    code = d.get("tool_code") or ""
    if not code.strip():
        return False, "no tool_code"

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        (p / "data.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        (p / "tool.py").write_text(code)
        probe = (
            "import sys, traceback\n"
            "sys.path.insert(0, '.')\n"
            "try:\n"
            "    import tool\n"
            "    fns = [n for n in dir(tool) if callable(getattr(tool, n))"
            " and not n.startswith('_')]\n"
            "    assert fns, 'tool exposes no public functions'\n"
            "    if hasattr(tool, 'load'):\n"
            "        rows = tool.load()\n"
            "        assert isinstance(rows, list) and rows, 'load() empty'\n"
            "    print('SMOKE_OK', len(fns))\n"
            "except Exception:\n"
            "    traceback.print_exc(); sys.exit(1)\n")
        (p / "_probe.py").write_text(probe)
        try:
            r = subprocess.run([sys.executable, "_probe.py"], cwd=tmp,
                               capture_output=True, text=True, timeout=30)
        except Exception as e:  # noqa: BLE001
            return False, f"smoke test crashed: {e}"
    if r.returncode == 0 and "SMOKE_OK" in r.stdout:
        return True, r.stdout.strip()
    return False, (r.stderr or r.stdout)[-400:]


def check(d: dict) -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(d, dict):
        return {"ok": False, "errors": ["not a dict"], "warnings": [], "score": 0}

    if len((d.get("title") or "").strip()) < 6:
        errors.append("title too short")
    if len((d.get("description") or "").strip()) < 60:
        errors.append("description too short (<60 chars)")

    rows = d.get("rows") or []
    if len(rows) < MIN_ROWS:
        errors.append(f"only {len(rows)} rows (need >= {MIN_ROWS})")

    seen, dupes = set(), 0
    for r in rows:
        if not isinstance(r, dict):
            errors.append("a row is not an object")
            break
        key = json.dumps(r, sort_keys=True)[:200]
        if key in seen:
            dupes += 1
        seen.add(key)
    if dupes:
        errors.append(f"{dupes} duplicate row(s)")

    code = d.get("tool_code") or ""
    if len(code) < MIN_TOOL_CHARS:
        errors.append(f"tool_code too small ({len(code)} chars)")
    bad = _check_imports(code)
    if bad:
        errors.append(f"non-stdlib imports: {bad[:3]}")

    blob = f"{d.get('description','')}\n{code}\n{d.get('tests','')}"
    if m := _LEAK.search(blob):
        errors.append(f"placeholder/leakage: {m.group(0)[:40]!r}")

    if not d.get("tests"):
        warnings.append("no tests supplied")
    if not d.get("usage_example"):
        warnings.append("no usage example")
    if len(d.get("keywords") or []) < 3:
        warnings.append("fewer than 3 keywords (hurts discoverability)")

    # The decisive check: does it actually run?
    if not errors:
        ok, detail = run_smoke_test(d)
        if not ok:
            errors.append(f"SMOKE TEST FAILED — tool does not run: {detail[:200]}")

    score = max(0, 100 - 25 * len(errors) - 5 * len(warnings))
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "score": score}


def gate(d: dict, name: str, strict: bool = True) -> bool:
    r = check(d)
    for w in r["warnings"]:
        print(f"[qc3] WARN  {name}: {w}")
    for e in r["errors"]:
        print(f"[qc3] ERROR {name}: {e}")
    verdict = "PASS" if r["ok"] else ("BLOCK" if strict else "PASS(non-strict)")
    print(f"[qc3] {name}: {verdict} score={r['score']}/100")
    return r["ok"] or not strict
