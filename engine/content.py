"""
content.py — generate content pieces (text/image/video) for a free asset.

Every piece embeds: (1) the free asset's Whop page link, (2) one upsell CTA
(paid deep-dive pack or custom work). Variants are generated so the same
asset is never posted identically twice.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import textgen  # noqa: E402

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
CTA_FILE = PROMPTS_DIR / "cta_templates.md"
DRY = os.environ.get("DRY_RUN") == "1"
DEFAULT_LINK = os.environ.get("FREE_ASSET_LINK", "{ASSET_LINK}")

FORMATS = ["text", "image", "video", "question"]


def cta_templates() -> list[str]:
    if CTA_FILE.exists():
        return [l.strip("- ").strip() for l in CTA_FILE.read_text().splitlines()
                if l.strip().startswith("-")]
    return [
        "Grab the free pack: {LINK}",
        "This is part of our free '{TITLE}' pack — get it here: {LINK}",
    ]


def system_prompt() -> str:
    sg = PROMPTS_DIR / "style_guide.md"
    voice = sg.read_text() if sg.exists() else "direct, practical, zero fluff"
    return (
        f"You write marketing content for an AI prompt-pack store on Whop. "
        f"Voice: {voice}. "
        "Rules:\n"
        "- No clickbait, no all-caps spam, no emoji walls (max 2 emoji).\n"
        "- Each post MUST include the asset link exactly once, in a natural sentence.\n"
        "- Each post ends with ONE CTA (paid upgrade or custom work), max 2 sentences.\n"
        "- Vary openings across posts; never repeat a hook."
    )


def generate_piece(asset: dict, fmt: str, upsell: dict, link: str,
                   cta_idx: int, lang: str = "en") -> dict:
    """One content piece. Returns dict: {fmt, title, body, image_prompt?,
    narration?, cta, lang}."""
    ctas = cta_templates()
    cta = ctas[cta_idx % len(ctas)].format(LINK=link, TITLE=asset["title"])
    user = (
        f"Asset: {asset['title']} — {asset.get('topic', '')}\n"
        f"Link to use: {link}\n"
        f"CTA to use: {cta}\n"
        f"Upsell hook (optional angle): {upsell.get('pro_teaser', '')}\n"
        f"Format: {fmt}\n"
        + (f"Language: {lang}\n" if lang != "en" else "")
        + f"Output JSON: {{\"title\": \"...\", \"body\": \"...\", \"image_prompt\": \"...\", "
          f"\"narration\": \"...\"}}\n"
        + ("For image: body is the caption, image_prompt describes a square promo graphic. "
           "For video: body is the caption, narration is the voiceover script. "
           "For text/question: body is the full post text." if fmt in ("image", "video") else
           "For text/question: body is the full post; image_prompt and narration may be empty.")
    )
    try:
        data = textgen.get_json([{"role": "system", "content": system_prompt()},
                                 {"role": "user", "content": user}],
                                max_tokens=1200, quality=False)
    except Exception as e:
        print(f"[content] generation failed ({e}) — template fallback")
        data = {"title": asset["title"], "body": f"{asset['title']} — {link} {cta}",
                "image_prompt": "", "narration": ""}
    data.update({"fmt": fmt, "cta": cta, "lang": lang, "link": link})
    return data


def content_set(asset: dict, upsell: dict, link: str,
                n: int = 4, lang: str = "en") -> list[dict]:
    """Generate n pieces, cycling formats so no two posts look alike."""
    pieces = []
    for i in range(n):
        fmt = FORMATS[i % len(FORMATS)]
        pieces.append(generate_piece(asset, fmt, upsell, link, cta_idx=i, lang=lang))
    return pieces


if __name__ == "__main__":
    asset = {"title": "Zero-Click Content Machine", "topic": "content automation"}
    upsell = {"pro_teaser": "Pro adds 30 prompts and video scripts."}
    for p in content_set(asset, upsell, DEFAULT_LINK, n=4):
        print(json.dumps(p, indent=2)[:500], "\n---")
