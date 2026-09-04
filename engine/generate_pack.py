"""
generate_pack.py — turn a topic into a structured prompt pack / skill set.

Flow: topic -> textgen (quality tier, JSON mode) -> pack dict -> render
markdown -> packaging (md/html/pdf/docx/zip).

MOCK=1 renders a built-in sample pack so the full pipeline can be tested
offline with zero API keys.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import textgen  # noqa: E402

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

SCHEMA = """{
  "title": "catchy pack title",
  "subtitle": "one-line promise",
  "category": "prompt-pack | skill-set",
  "difficulty": "beginner | intermediate | advanced",
  "audience": "who this is for",
  "description": "2-3 sentence product description (used on Whop)",
  "keywords": ["5", "seo", "keywords"],
  "prompts": [
    {"n": 1, "title": "Prompt name", "use_case": "when to use it",
     "prompt": "the full prompt text", "example_output": "what it returns"}
  ],
  "skills": [
    {"n": 1, "title": "Skill name", "summary": "one line",
     "steps": ["step 1", "step 2", "step 3"],
     "code": {"language": "python", "snippet": "print('runnable')",
              "explanation": "what the code does"}}
  ],
  "faq": [
    {"question": "buyer question", "answer": "clear 1-2 sentence answer"}
  ],
  "upsell": {
    "pro_teaser": "what the paid deep-dive adds",
    "custom_work_cta": "one line pitching custom work"
  }
}"""

MOCK_PACK = {
    "faq": [
        {"question": "What exactly do I get?",
         "answer": "Every prompt and skill in this pack as an instant "
                   "download in Markdown, PDF and DOCX."},
        {"question": "Do I need a paid AI subscription?",
         "answer": "No — everything works on free ChatGPT, Claude or Gemini."},
    ],
    "title": "Zero-Click Content Machine",
    "subtitle": "Automate a week of content in one prompt",
    "category": "prompt-pack",
    "difficulty": "intermediate",
    "audience": "creators and solo founders who sell digital products",
    "description": "A curated pack of prompts that turn one topic into a full "
                   "content calendar: hooks, posts, and CTAs. Free starter pack.",
    "keywords": ["content automation", "ai prompts", "content calendar", "whop", "marketing"],
    "prompts": [
        {"n": 1, "title": "The Content Matrix", "use_case": "expand one topic into 5 angles",
         "prompt": "You are a content strategist. Given TOPIC and AUDIENCE, output a 5-cell "
                   "matrix: hook, bridge, value, proof, CTA. Be specific and non-generic.",
         "example_output": "A table with 5 filled rows, each tailored to the audience."},
        {"n": 2, "title": "Voice Cloner", "use_case": "match your brand voice",
         "prompt": "Here are 3 samples of my writing: [SAMPLES]. Extract the voice pattern "
                   "(sentence length, tone, vocabulary) and rewrite: [NEW TEXT] in that voice.",
         "example_output": "Rewritten text + a 3-line voice pattern summary."},
        {"n": 3, "title": "Hook Lab", "use_case": "10 scroll-stopping openers",
         "prompt": "Write 10 opening lines for a post about [TOPIC]. Rules: under 12 words, "
                   "no cliches, each triggers a different emotion. Rank them.",
         "example_output": "10 ranked hooks with the emotion each one triggers."},
    ],
    "skills": [
        {"n": 1, "title": "Auto-title generator", "summary": "mine competitor titles for patterns",
         "steps": ["Paste 3 competitor titles into the prompt.",
                   "Ask the model to find the pattern (power words, numbers, curiosity gaps).",
                   "Generate 10 titles for YOUR topic in that pattern.",
                   "Pick the best with a second model pass."],
         "code": {"language": "python",
                  "snippet": "titles = ['3 titles here']\npattern = llm('what pattern?', titles)\nnew = llm(f'10 titles in this pattern: {pattern}', topic)\nprint(new)",
                  "explanation": "Two-pass generation: pattern extraction, then creation."}},
        {"n": 2, "title": "Daily post batcher", "summary": "one prompt, seven posts",
         "steps": ["Give the model your asset link and one topic.",
                   "Ask for 7 post variants across 4 formats (text, image idea, video script, question).",
                   "Request a different CTA angle per post.",
                   "Post one variant per day, staggered."],
         "code": {"language": "python",
                  "snippet": "posts = llm('7 variants for TOPIC, link: LINK', formats=['text','image','video','q'])\nfor p in posts: post(p)",
                  "explanation": "Batch generation keeps voice consistent across the week."}},
    ],
    "upsell": {
        "pro_teaser": "The Pro version adds 30 prompts, 8 video scripts and a fill-in-the-blank "
                      "content system you can run daily.",
        "custom_work_cta": "Want a pack built for YOUR niche? Custom prompt packs start at $150.",
    },
}


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:60] or "pack"


def system_prompt(topic: str) -> str:
    style_guide = ""
    sg = PROMPTS_DIR / "style_guide.md"
    if sg.exists():
        style_guide = sg.read_text()
    return (
        "You build market-ready AI prompt packs sold on Whop. "
        "Output ONLY valid JSON matching this schema: " + SCHEMA + "\n"
        f"Topic: {topic}\n"
        "Requirements:\n"
        "- prompts: 6-12 for a prompt-pack (3-5 if category is skill-set), each with a "
        "complete copy-paste-ready prompt body.\n"
        "- skills: 2-4, each with 3-6 concrete steps AND a runnable code snippet "
        "(python or apps-script).\n"
        "- upsell.pro_teaser must create genuine desire (what the paid version adds).\n"
        "- upsell.custom_work_cta: one line, price anchored at $150+.\n"
        + (f"- Brand voice: {style_guide}\n" if style_guide else
           "- Voice: direct, practical, zero fluff.\n")
        + "- Do not include the topic title verbatim in prompts unless needed."
    )


def generate(topic: str, mock: bool = False) -> dict:
    if mock or os.environ.get("MOCK") == "1":
        return dict(MOCK_PACK)
    messages = [
        {"role": "system", "content": system_prompt(topic)},
        {"role": "user", "content": f"Create the pack for: {topic}"},
    ]
    # 4000 tokens truncated real packs mid-JSON (production: 0/3 assets on
    # 2026-09-04, all three JSONDecodeError). Packs need ~9k+ chars.
    pack = textgen.get_json(messages, max_tokens=8000, quality=True)
    pack = ensure_shape(pack)

    # Models under-deliver on count (observed: 3 prompts when 10 were asked
    # for), which QC then correctly blocks. Ask once for the shortfall rather
    # than lowering the quality bar or throwing the whole pack away.
    want = 8
    have = len(pack.get("prompts") or [])
    if have < want:
        print(f"[pack] only {have} prompts, requesting {want - have} more")
        try:
            top_up = textgen.get_json(messages + [
                {"role": "assistant", "content": json.dumps(pack)[:4000]},
                {"role": "user", "content":
                 f"That pack has only {have} prompts. Return ONLY valid JSON "
                 f'of the form {{"prompts": [...]}} containing {want - have} '
                 "ADDITIONAL, different prompts in the same shape."}],
                max_tokens=6000, quality=True)
            extra = top_up.get("prompts") or []
            if extra:
                seen = {str(x.get("prompt", ""))[:120].lower()
                        for x in pack["prompts"]}
                for e in extra:
                    if str(e.get("prompt", ""))[:120].lower() not in seen:
                        pack["prompts"].append(e)
                for i, pr in enumerate(pack["prompts"], 1):
                    pr["n"] = i
                print(f"[pack] topped up to {len(pack['prompts'])} prompts")
        except Exception as e:  # noqa: BLE001  a thin pack is better than none
            print(f"[pack] top-up failed ({e}) — QC will decide")

    return ensure_faq(pack)


# Whop's store page has a dedicated FAQ section and it is a real conversion
# lever. The API cannot write it (see docs/MARKETPLACE.md), so we generate the
# copy, ship it in the deliverable, and expose it for one paste into the editor.
DEFAULT_FAQ = [
    {"question": "What exactly do I get?",
     "answer": "An instant download containing every prompt and skill in this "
               "pack, in Markdown, PDF and DOCX so it works wherever you do."},
    {"question": "Do I need a paid AI subscription?",
     "answer": "No. Every prompt works on the free tiers of ChatGPT, Claude "
               "and Gemini."},
    {"question": "How fast do I get access?",
     "answer": "Immediately. The download links are on this page the moment "
               "you check out."},
    {"question": "Do I need any technical skill?",
     "answer": "None. Copy a prompt, paste it into your AI tool, and replace "
               "the bracketed placeholders with your own details."},
    {"question": "Can I use this for client work?",
     "answer": "Yes. Use the outputs in your own business or for clients. "
               "Please don't resell the pack itself."},
]


def ensure_shape(pack: dict) -> dict:
    """Guarantee optional-but-assumed keys exist.

    The LLM legitimately omits `skills` (especially after a truncation
    repair), and three call sites indexed it directly -> KeyError killed an
    otherwise PERFECT pack that had already scored 100/100 at QC.
    """
    pack.setdefault("skills", [])
    pack.setdefault("prompts", [])
    pack.setdefault("keywords", [])
    pack.setdefault("upsell", {"pro_teaser": "", "custom_work_cta": ""})
    return pack


def ensure_faq(pack: dict) -> dict:
    """Guarantee a usable FAQ, whatever the model returned."""
    faq = pack.get("faq")
    clean = []
    if isinstance(faq, list):
        for item in faq:
            if isinstance(item, dict):
                q = (item.get("question") or item.get("q") or "").strip()
                a = (item.get("answer") or item.get("a") or "").strip()
                if q and a:
                    clean.append({"question": q, "answer": a})
    # top up to at least 4 entries without duplicating questions
    have = {c["question"].lower() for c in clean}
    for d in DEFAULT_FAQ:
        if len(clean) >= 4:
            break
        if d["question"].lower() not in have:
            clean.append(dict(d))
    pack["faq"] = clean
    return pack


def render_markdown(pack: dict, topic: str, links: dict) -> str:
    """links: {'pro': url, 'custom_work': url} — placeholder-safe."""
    pro = links.get("pro", "{PRO_LINK}")
    cw = links.get("custom_work", "{CUSTOM_WORK_LINK}")
    L = []
    L.append(f"# {pack['title']}\n")
    L.append(f"**{pack['subtitle']}**\n")
    L.append(f"> {pack['audience']} · Difficulty: {pack['difficulty']}\n")
    L.append(f"{pack['description']}\n")
    L.append("---\n")
    L.append("## Prompts\n")
    for p in pack["prompts"]:
        L.append(f"### {p['n']}. {p['title']}\n")
        L.append(f"**Use when:** {p['use_case']}\n")
        L.append("```text")
        L.append(p["prompt"])
        L.append("```\n")
        L.append(f"**Returns:** {p['example_output']}\n")
    L.append("---\n")
    L.append("## Skills\n")
    for s in (pack.get("skills") or []):
        L.append(f"### {s['n']}. {s['title']}\n")
        L.append(f"*{s['summary']}*\n")
        for i, step in enumerate(s["steps"], 1):
            L.append(f"{i}. {step}")
        if s.get("code", {}).get("snippet"):
            L.append(f"\n```{s['code'].get('language', 'python')}")
            L.append(s["code"]["snippet"])
            L.append("```")
            if s["code"].get("explanation"):
                L.append(f"*{s['code']['explanation']}*\n")
    L.append("---\n")
    L.append("## Level up\n")
    if pack.get("faq"):
        L.append("---\n")
        L.append("## FAQ\n")
        for f in pack["faq"]:
            L.append(f"**{f['question']}**\n")
            L.append(f"{f['answer']}\n")
    L.append(f"{pack['upsell']['pro_teaser']}\n")
    L.append(f"👉 [Get the Pro version]({pro})\n")
    L.append(f"{pack['upsell']['custom_work_cta']}\n")
    L.append(f"👉 [Request custom work]({cw})\n")
    L.append("\n---\n")
    L.append(f"*Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d')} · topic: {topic}*")
    return "\n".join(L)


def build_pack_dir(topic: str, pack: dict, links: dict, base: Path) -> dict:
    slug = slugify(pack["title"])
    d = base / slug
    d.mkdir(parents=True, exist_ok=True)
    md = render_markdown(pack, topic, links)
    (d / "pack.md").write_text(md)
    (d / "pack.json").write_text(json.dumps(pack, indent=2))
    return {"slug": slug, "dir": d, "md": d / "pack.md", "pack": pack}


if __name__ == "__main__":
    # CLI smoke: python3 generate_pack.py "topic" [--mock]
    topic = sys.argv[1] if len(sys.argv) > 1 else "AI content automation"
    mock = "--mock" in sys.argv or os.environ.get("MOCK") == "1"
    pack = generate(topic, mock=mock)
    out = build_pack_dir(topic, pack, {}, Path("out/packs"))
    print(json.dumps({"slug": out["slug"], "prompts": len(pack["prompts"]),
                      "skills": len(pack.get("skills") or []), "md": str(out["md"])}, indent=2))
