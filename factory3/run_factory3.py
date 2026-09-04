"""Factory 3 runner — developer datasets and tools.

Standalone: own state, own queue, own manifest, own copy of the shared infra.

Flow:
    pick seed -> generate dataset+tool -> QC (incl. EXECUTING the tool)
              -> GitHub repo -> Hugging Face dataset
              -> enqueue to distribution -> drain

Monetisation is zaps + sponsors, both of which need no approval from anyone —
which is the whole reason this factory exists alongside the other two.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import dist_core  # noqa: E402
import dist_channels  # noqa: E402,F401  registers adapters
import generate_tool as gen  # noqa: E402
import publish_targets as pt  # noqa: E402
import qc_tool  # noqa: E402
import resilience as rz  # noqa: E402

STATE = ROOT / "state"
OUT = ROOT / "out"
MANIFEST = STATE / "manifest.json"
MOCK = os.environ.get("MOCK") == "1"
DRY = os.environ.get("DRY_RUN") == "1"
N = int(os.environ.get("F3_ASSETS", "1"))


def _manifest() -> dict:
    try:
        return json.loads(MANIFEST.read_text())
    except Exception:  # noqa: BLE001
        return {"datasets": []}


def one_asset() -> dict | None:
    try:
        d = gen.generate(mock=MOCK)
        name = d["name"]
        print(f"[f3] generated: {name} ({len(d.get('rows', []))} rows)")

        strict = not MOCK and os.environ.get("QC_STRICT", "1") != "0"
        if not qc_tool.gate(d, name, strict=strict):
            print(f"[f3] {name}: BLOCKED by QC — not publishing")
            rz.alert(f"F3 QC blocked: {name}",
                     "Dataset failed the gate (see run log). Most likely the "
                     "generated tool did not execute.",
                     level="warn", dedupe=f"f3qc:{name}")
            return None

        jsonl = gen.to_jsonl(d.get("rows", []))
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"{name}.jsonl").write_text(jsonl)

        if DRY:
            print(f"[f3] DRY — would publish {name}")
            return {"name": name, "status": "dry",
                    "rows": len(d.get("rows", []))}

        gh_url = hf_url = ""

        # --- GitHub ---
        repo = pt.ensure_repo(name, d.get("description", ""),
                              (d.get("keywords") or []) + ["dataset",
                                                           d.get("category", "")])
        if repo.get("ok"):
            owner = repo["owner"]
            gh_url = repo["url"]
            files = {
                "data.jsonl": jsonl,
                "tool.py": d.get("tool_code", ""),
                "test_tool.py": d.get("tests", ""),
                "LICENSE": "CC0 1.0 Universal — public domain dedication.\n"
                           "https://creativecommons.org/publicdomain/zero/1.0/\n",
            }
            for path, content in files.items():
                if content.strip():
                    r = pt.put_file(owner, name, path, content,
                                    f"add {path}")
                    if not r.get("ok"):
                        print(f"[f3] {r.get('error')}")
            pt.add_funding(owner, name)
            print(f"[f3] github: {gh_url}")
        else:
            print(f"[f3] github failed: {repo.get('error')}")
            rz.alert("F3 GitHub publish failed", str(repo.get("error"))[:300],
                     level="warn", dedupe="f3-gh")

        # --- Hugging Face ---
        readme = gen.render_readme(d, gh_url, "")
        hf = pt.publish_hf_dataset(name, readme,
                                   {"data.jsonl": jsonl,
                                    "tool.py": d.get("tool_code", "")})
        if hf.get("ok"):
            hf_url = hf["url"]
            print(f"[f3] huggingface: {hf_url}")
            # refresh the GitHub README now that we know the HF url
            if repo.get("ok"):
                pt.put_file(repo["owner"], name, "README.md",
                            gen.render_readme(d, gh_url, hf_url),
                            "update readme")
        else:
            print(f"[f3] hf failed: {hf.get('error')}")

        # --- distribution ---
        landing = hf_url or gh_url
        dist_core.enqueue({
            "slug": name,
            "title": d.get("title", name),
            "subtitle": d.get("description", "")[:120],
            "description": d.get("description", ""),
            "keywords": d.get("keywords") or [],
            "price": 0.0,
            "page_url": landing,
            "deliverable_url": f"{gh_url}/raw/main/data.jsonl" if gh_url else "",
        })

        gen.mark(d["seed"])
        return {"name": name, "title": d.get("title"),
                "rows": len(d.get("rows", [])), "github": gh_url,
                "huggingface": hf_url,
                "created": datetime.now(timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%SZ"),
                "status": "live"}

    except Exception as e:  # noqa: BLE001
        print(f"[f3] ASSET FAILED: {e}\n{traceback.format_exc()}")
        rz.alert("F3 asset generation failed",
                 f"`{type(e).__name__}: {e}`\n```\n"
                 f"{traceback.format_exc()[-900:]}\n```",
                 level="error", dedupe=f"f3asset:{type(e).__name__}")
        return None


def main() -> None:
    if os.environ.get("F3_ENABLED", "0") != "1":
        print("[f3] DISABLED — set F3_ENABLED=1 to run. Exiting.")
        return

    print(f"[f3] MOCK={MOCK} DRY={DRY} assets={N}")
    results = [r for r in (one_asset() for _ in range(N)) if r]

    if results:
        m = _manifest()
        m.setdefault("datasets", []).extend(results)
        STATE.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(json.dumps(m, indent=2))

    if N and not results:
        rz.alert("FACTORY 3 IDLE — 0 datasets produced",
                 f"Attempted {N}, produced 0.", level="error",
                 dedupe="f3-idle")
        raise SystemExit(f"[f3] produced 0/{N} — failing loudly")

    if not DRY:
        try:
            print(f"[f3] distribution: {dist_core.drain()}")
        except Exception as e:  # noqa: BLE001
            print(f"[f3] drain skipped: {e}")

    (STATE / "heartbeat.json").write_text(json.dumps({
        "factory3": {"at": datetime.now(timezone.utc)
                     .strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "count": len(results),
                     "run_id": os.environ.get("GITHUB_RUN_ID", "local")}},
        indent=2))
    print(f"[f3] done. {len(results)}/{N} datasets.")


if __name__ == "__main__":
    main()
