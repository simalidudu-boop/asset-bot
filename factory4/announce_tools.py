"""Factory 4 announcer — cycles the fixed tool set through the mesh.

An important honesty note about F4
----------------------------------
F1 and F3 are autonomous *producers*: an LLM generates a genuinely new asset
on every run. **F4 is not.** The five tools are hand-written and fixed. The
Worker serves them; nothing invents new ones.

So this script does not "publish new tools" — it **re-announces existing
ones on a rotation**, with fresh angles, so the mesh keeps pointing at them
without spamming the same sentence forever.

Two problems that had to be solved:

  1. `dist_core.enqueue()` dedupes on `(slug, channel)`. A naive rotation
     would post each tool exactly once, ever, then fall permanently silent.
     Fixed by giving each announcement a dated slug.

  2. Repeating one sentence is how an account gets muted. Each tool has
     several angles, and the rotation picks by date so the same tool never
     reads identically twice in a row.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import dist_core  # noqa: E402
import dist_channels  # noqa: E402,F401  registers adapters
import resilience as rz  # noqa: E402

STATE = ROOT / "state"
BASE = (os.environ.get("F4_PAGE_BASE")
        or os.environ.get("PACK_PAGE_BASE")
        or "https://asset-bot-edge.simalidudu.workers.dev").rstrip("/")

# Mirrors workers/src/tools.ts. Kept as data here so the announcer needs no
# TypeScript. If you add a tool there, add it here.
TOOLS = [
    {
        "slug": "prompt-injection-tester",
        "title": "Prompt Injection Tester",
        "dataset": "https://github.com/simalidudu-boop/adversarial-prompt-injection-dataset",
        "angles": [
            "Paste a prompt, see whether it matches known LLM injection "
            "attacks. Runs in your browser against a public CC0 corpus — "
            "nothing you type is sent anywhere.",
            "Most prompt-injection filters are a regex someone wrote once. "
            "This one scores against a real corpus of documented attacks, and "
            "the corpus is public domain so you can just take it.",
            "Free, no signup: check any prompt for injection patterns before "
            "it reaches your model. The dataset behind it is on GitHub and "
            "Hugging Face.",
        ],
        "keywords": ["llm", "security", "promptinjection", "ai"],
    },
    {
        "slug": "llm-refusal-detector",
        "title": "LLM Refusal Detector",
        "dataset": "https://github.com/simalidudu-boop/model-refusal-phrases",
        "angles": [
            "A refusal returns HTTP 200 and a polite paragraph. Your pipeline "
            "scores it as success and ingests nothing. This catches that.",
            "Soft failures are the expensive kind: no error, no alert, just "
            "useless output flowing downstream. Paste model output and find "
            "out if it actually refused.",
            "Free browser tool: detect refusals in LLM output, matched "
            "against a public corpus of real refusal phrasings.",
        ],
        "keywords": ["llm", "evaluation", "ai", "testing"],
    },
    {
        "slug": "llm-cost-calculator",
        "title": "LLM Cost Calculator",
        "dataset": "",
        "angles": [
            "Estimate what a prompt costs across GPT, Claude, Gemini and "
            "Llama before you commit to it. Works offline — no network call "
            "at all.",
            "Per call, per day, per month, across eight models side by side. "
            "Free, no signup, nothing leaves your browser.",
            "The cheapest time to discover an API bill is before you ship. "
            "Free token and cost estimator for every major model.",
        ],
        "keywords": ["llm", "api", "pricing", "tokens"],
    },
    {
        "slug": "json-repair",
        "title": "LLM JSON Repair",
        "dataset": "",
        "angles": [
            "Models truncate JSON mid-string and your parser throws. This "
            "rebalances the brackets and recovers what is there — instead of "
            "burning another API call.",
            "We built this after truncated JSON silently produced zero output "
            "in our own pipeline for a full day. Free, runs in your browser.",
            "Fix unterminated strings, trailing commas, unclosed brackets and "
            "markdown fences in LLM JSON output. No signup.",
        ],
        "keywords": ["json", "llm", "debugging", "devtools"],
    },
    {
        "slug": "prompt-optimizer",
        "title": "Prompt Optimizer",
        "dataset": "",
        "angles": [
            "Rewrites a vague prompt with an explicit role, constraints and "
            "output format. Bring your own free Groq key — it stays in your "
            "browser, we never see it.",
            "Free and genuinely unlimited, because you supply the key. No "
            "account, no quota, no shared-key throttling.",
            "Most underperforming prompts are missing the same four things: "
            "role, constraints, output format, edge cases. This adds them.",
        ],
        "keywords": ["prompt", "ai", "groq", "promptengineering"],
    },
]


def pick_today() -> tuple[dict, str]:
    """One tool + one angle per run, rotating deterministically by date.

    Date-based rather than random so a re-run on the same day announces the
    same thing — which the queue then dedupes, instead of double-posting.
    """
    n = date.today().toordinal()
    tool = TOOLS[n % len(TOOLS)]
    angle = tool["angles"][(n // len(TOOLS)) % len(tool["angles"])]
    return tool, angle


def main() -> None:
    if os.environ.get("F4_ENABLED", "0") != "1":
        print("[f4] DISABLED — set F4_ENABLED=1 to run. Exiting.")
        return

    tool, angle = pick_today()
    url = f"{BASE}/tools/{tool['slug']}"
    today = date.today().isoformat()

    # The queue dedupes on (slug, channel). A bare tool slug would therefore
    # post once and never again — so date-stamp it to make each announcement
    # a distinct job while the destination URL stays the same.
    job_slug = f"tool-{tool['slug']}-{today}"

    desc = angle
    if tool["dataset"]:
        desc += f"\n\nDataset: {tool['dataset']}"

    print(f"[f4] announcing {tool['title']} -> {url}")
    try:
        added = dist_core.enqueue({
            "slug": job_slug,
            "title": f"{tool['title']} — free, no signup",
            "subtitle": angle[:120],
            "description": desc,
            "keywords": tool["keywords"],
            "price": 0.0,
            "page_url": url,
        })
        if not added:
            print("[f4] already queued for today — nothing to do")
    except Exception as e:  # noqa: BLE001
        rz.alert("F4 enqueue failed", f"`{e}`", level="error", dedupe="f4-enqueue")
        raise SystemExit(f"[f4] enqueue failed: {e}")

    try:
        print(f"[f4] distribution: {dist_core.drain()}")
    except Exception as e:  # noqa: BLE001
        print(f"[f4] drain skipped: {e}")

    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "heartbeat.json").write_text(json.dumps({
        "factory4": {"at": datetime.now(timezone.utc)
                     .strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "tool": tool["slug"],
                     "run_id": os.environ.get("GITHUB_RUN_ID", "local")}},
        indent=2))
    print(f"[f4] done — {tool['slug']}")


if __name__ == "__main__":
    main()
