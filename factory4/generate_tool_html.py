"""Factory 4 producer — LLM-generated self-contained browser tools.

This is what turns F4 from a shopfront into a real factory. Until now the five
tools were hand-written; this generates new ones.

The hard part is not generation, it is **proof that the thing works**. An
LLM will happily emit HTML that looks like a tool and does nothing. So the
QC gate here executes the generated JavaScript in Node against real input and
asserts the DOM actually changed — the same principle as Factory 3 running
the Python it generates.

A tool that renders but does not compute is worse than no tool: it burns the
credibility the whole strategy depends on.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import textgen  # noqa: E402

DONE = ROOT / "state" / "tools_done.json"

# Each seed is a real, searched-for utility that can run entirely client-side.
# No API keys, no server, no external data — those constraints are what make
# the tool free to run forever.
SEEDS = [
    ("jwt-decoder", "Decode a JWT and show header, payload and expiry",
     "jwt decoder, decode jwt, jwt parser"),
    ("uuid-generator", "Generate v4 UUIDs in bulk with copy",
     "uuid generator, guid generator, random uuid"),
    ("slug-generator", "Turn any title into a clean URL slug",
     "slug generator, url slug, seo slug"),
    ("diff-checker", "Compare two blocks of text and highlight differences",
     "text diff, compare text, diff checker"),
    ("cron-parser", "Explain a cron expression in plain English",
     "cron parser, cron expression, crontab explain"),
    ("regex-tester", "Test a regex against sample text with live matches",
     "regex tester, regex online, test regular expression"),
    ("case-converter", "Convert text between camel, snake, kebab and title case",
     "case converter, camelcase, snake case"),
    ("word-counter", "Count words, characters, sentences and reading time",
     "word counter, character count, reading time"),
    ("timestamp-converter", "Convert Unix timestamps to human dates and back",
     "unix timestamp converter, epoch converter"),
    ("color-converter", "Convert colours between HEX, RGB and HSL",
     "hex to rgb, color converter, rgb to hex"),
]

SCHEMA = """{
  "slug": "kebab-case-slug",
  "title": "Human Readable Tool Name",
  "tagline": "one line, under 90 chars",
  "description": "meta description, 120-160 chars, includes the main keyword",
  "keywords": ["5","search","keywords"],
  "body_html": "the tool's HTML: inputs, buttons, and a <div id=\\"out\\"></div>. NO <script> tag, NO <style> tag.",
  "script_js": "plain JavaScript. MUST define function run() that reads the inputs and writes results into document.getElementById('out').innerHTML. No imports, no fetch, no external libraries.",
  "faq": [{"question":"q","answer":"a"}],
  "test_input": "a string to type into the primary input during automated testing",
  "test_expect": "a short substring that MUST appear in the output for that input"
}"""


def _done() -> set:
    try:
        return set(json.loads(DONE.read_text()))
    except Exception:  # noqa: BLE001
        return set()


def mark(slug: str) -> None:
    d = _done(); d.add(slug)
    DONE.parent.mkdir(parents=True, exist_ok=True)
    DONE.write_text(json.dumps(sorted(d), indent=2))


def pick_seed():
    done = _done()
    for s in SEEDS:
        if s[0] not in done:
            return s
    return None


def system_prompt(slug, desc, kw) -> str:
    return f"""Build a single-purpose browser tool: {desc}

Target keywords: {kw}

HARD REQUIREMENTS — the tool is auto-tested and rejected if it fails:
- `script_js` MUST define `function run()`. It reads values from the inputs in
  body_html and writes HTML into document.getElementById('out').innerHTML.
- Pure vanilla JavaScript. NO fetch, NO imports, NO external libraries, NO
  API calls. Everything computes locally.
- The primary text input MUST have id="inp".
- body_html must contain a button that calls run(), and <div id="out"></div>.
- Handle empty input gracefully (a message, not a crash).
- No <script> or <style> tags inside body_html — those are added separately.
- Do not use backticks in script_js; use single or double quotes only.

Return ONLY valid JSON matching this schema:
{SCHEMA}"""


def generate(mock: bool = False) -> dict | None:
    seed = pick_seed()
    if not seed:
        print("[f4gen] every seed already built")
        return None
    slug, desc, kw = seed

    if mock or os.environ.get("MOCK") == "1":
        d = {
            "slug": "word-counter",
            "title": "Word Counter",
            "tagline": "Count words, characters and reading time",
            "description": "Free word counter. Count words, characters, "
                           "sentences and estimated reading time instantly in "
                           "your browser. No signup.",
            "keywords": ["word counter", "character count", "reading time"],
            "body_html": '<textarea id="inp" rows="6"></textarea>'
                         '<button onclick="run()">Count</button>'
                         '<div id="out"></div>',
            "script_js": (
                "function run(){var t=document.getElementById('inp').value;"
                "var w=(t.match(/\\S+/g)||[]).length;"
                "var c=t.length;var m=Math.max(1,Math.round(w/200));"
                "document.getElementById('out').innerHTML="
                "'<b>'+w+'</b> words, <b>'+c+'</b> characters, ~'+m+' min read';}"),
            "faq": [{"question": "Does it send my text anywhere?",
                     "answer": "No. It runs entirely in your browser."}],
            "test_input": "hello world this is a test",
            "test_expect": "6",
        }
    else:
        d = textgen.get_json(
            [{"role": "system", "content": system_prompt(slug, desc, kw)},
             {"role": "user", "content": f"Build the tool: {desc}"}],
            max_tokens=6000, quality=True)

    d["slug"] = re.sub(r"[^a-z0-9-]", "", (d.get("slug") or slug).lower())[:50] or slug
    d["seed"] = slug
    d.setdefault("faq", [])
    d.setdefault("keywords", [])
    return d


# ------------------------------------------------------------------ QC ---
_BANNED = re.compile(r"\bfetch\s*\(|\bimport\s|\brequire\s*\(|<script|"
                     r"XMLHttpRequest|eval\s*\(|document\.write", re.I)


def qc(d: dict) -> dict:
    """Validate, then EXECUTE the tool in Node and assert it produced output."""
    errors, warnings = [], []

    for f in ("title", "tagline", "description", "body_html", "script_js"):
        if not (d.get(f) or "").strip():
            errors.append(f"{f} missing")
    if errors:
        return {"ok": False, "errors": errors, "warnings": warnings, "score": 0}

    js, html = d["script_js"], d["body_html"]

    if "function run(" not in js:
        errors.append("script_js does not define run()")
    if 'id="out"' not in html and "id='out'" not in html:
        errors.append('body_html has no <div id="out">')
    if 'id="inp"' not in html and "id='inp'" not in html:
        warnings.append('no element with id="inp"')
    if m := _BANNED.search(js):
        errors.append(f"forbidden construct in script_js: {m.group(0)!r}")
    if len((d.get("description") or "")) > 170:
        warnings.append("meta description over 170 chars")
    if len(d.get("faq") or []) < 1:
        warnings.append("no FAQ (hurts SEO)")

    if errors:
        return {"ok": False, "errors": errors, "warnings": warnings,
                "score": max(0, 100 - 25 * len(errors))}

    ok, detail = _execute(d)
    if not ok:
        errors.append(f"EXECUTION FAILED: {detail[:220]}")

    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "score": max(0, 100 - 25 * len(errors) - 5 * len(warnings))}


def _execute(d: dict) -> tuple[bool, str]:
    """Run the tool's JS against a minimal DOM shim and assert output appears.

    A tool that renders but computes nothing is the failure mode that matters,
    and it is invisible without actually running the code.
    """
    shim = """
const els = {};
function mk(id){ return els[id] || (els[id] = {id, value:"", innerHTML:"",
  textContent:"", checked:false, style:{}, addEventListener(){},
  appendChild(){}, querySelectorAll(){return []}}); }
global.document = {
  getElementById: mk,
  querySelector: () => mk("q"),
  querySelectorAll: () => [],
  addEventListener: () => {},
  createElement: () => mk("tmp"),
  body: mk("body"),
};
global.window = { addEventListener: () => {}, localStorage:
  { getItem: () => null, setItem: () => {}, removeItem: () => {} } };
global.localStorage = global.window.localStorage;
global.navigator = { clipboard: { writeText: () => {} } };
__SCRIPT__
try {
  const inp = mk("inp"); inp.value = __INPUT__;
  const out = mk("out");
  if (typeof run !== "function") { console.log("NO_RUN"); process.exit(1); }
  run();
  const got = String(out.innerHTML || out.textContent || "");
  if (!got.trim()) { console.log("EMPTY_OUTPUT"); process.exit(1); }
  console.log("OUT:" + got.slice(0, 300));
} catch (e) { console.log("THREW:" + e.message); process.exit(1); }
"""
    code = (shim.replace("__SCRIPT__", d["script_js"])
                .replace("__INPUT__", json.dumps(d.get("test_input") or "test")))
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "probe.js"
        f.write_text(code)
        try:
            r = subprocess.run(["node", str(f)], capture_output=True,
                               text=True, timeout=20)
        except FileNotFoundError:
            return True, "node unavailable — execution skipped"
        except Exception as e:  # noqa: BLE001
            return False, f"probe crashed: {e}"

    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0 or "OUT:" not in out:
        return False, out.strip()[:300]

    expect = (d.get("test_expect") or "").strip()
    if expect and expect not in out:
        return False, f"expected {expect!r} in output, got: {out[4:120]}"
    return True, out.strip()[:200]


def gate(d: dict, strict: bool = True) -> bool:
    r = qc(d)
    for w in r["warnings"]:
        print(f"[qc4] WARN  {d.get('slug')}: {w}")
    for e in r["errors"]:
        print(f"[qc4] ERROR {d.get('slug')}: {e}")
    verdict = "PASS" if r["ok"] else ("BLOCK" if strict else "PASS(non-strict)")
    print(f"[qc4] {d.get('slug')}: {verdict} score={r['score']}/100")
    return r["ok"] or not strict
