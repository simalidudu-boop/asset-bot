"""
post.py — forum posting.

For each content piece: variant A goes to the PUBLIC space
(experience_id='public', company_id=WHOP_COMPANY_ID), variant B (a variation)
goes to your own forum (OWN_FORUM_ID). Posts are staggered (POST_STAGGER_SEC)
to avoid spam patterns. DRY_RUN=1 prints instead of posting.
"""
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import whop_client as whop  # noqa: E402

DRY = os.environ.get("DRY_RUN") == "1"
COMPANY_ID = os.environ.get("WHOP_COMPANY_ID", "")
OWN_FORUM_ID = os.environ.get("OWN_FORUM_ID", "")           # members-only forum
PUBLIC_FORUM_ID = os.environ.get("PUBLIC_FORUM_ID", "")     # explicit exp_ of public forum
PUBLIC_EXPERIENCE = os.environ.get("PUBLIC_EXPERIENCE", "public")
STAGGER = int(os.environ.get("POST_STAGGER_SEC", "600"))
MAX_POSTS_PER_RUN = int(os.environ.get("MAX_POSTS_PER_RUN", "4"))


_URL_RE = re.compile(r"(https?://[^\s<>\)\]]+?)([.,;:!?]+)(?=\s|$)")


def fix_links(text: str) -> str:
    """Whop 404s on a URL with a glued trailing period (audit P4).

    'see https://whop.com/x/y.' -> the '.' becomes part of the path. Move any
    trailing sentence punctuation outside the link by inserting a space.
    """
    return _URL_RE.sub(lambda m: f"{m.group(1)} {m.group(2)}", text)


def _variation(body: str, title: str) -> tuple[str, str]:
    """Small structural variation for the second forum so the two posts
    aren't byte-identical (same content, different wrapper)."""
    if body.startswith(("🔥", "🚀")):
        body = body[2:].lstrip()
    t2 = title.rstrip("?") + " — what would you add?"
    return body + "\n\nWhich one of these would you use first?", t2


def _post(target: dict, piece: dict) -> dict | None:
    label = target["label"]
    try:
        payload = dict(experience_id=target["experience_id"],
                       content=fix_links(piece["body"]),
                       title=piece["title"])
        if target.get("company_id"):
            payload["company_id"] = target["company_id"]
        # TODO(spike): media attachment path — upload image/video via Whop
        # direct upload, pass direct_upload_id in attachments=[].
        if DRY:
            print(f"[post] DRY -> {label}: {json_dump(payload)}")
            return {"dry": True, "forum": label}
        res = whop.create_forum_post(**payload)
        print(f"[post] LIVE -> {label}: {res.get('id', res)}")
        return res
    except Exception as e:
        print(f"[post] FAIL -> {label}: {e}")
        return None


def json_dump(p):
    import json
    return json.dumps(p, ensure_ascii=False)[:300]


def post_piece(piece: dict, media_url: str | None = None) -> dict:
    """Post the piece to both forums. media_url is attached as a link line
    (image/video embed) when available."""
    body = piece["body"]
    if media_url and piece["fmt"] in ("image", "video"):
        body = f"{body}\n\n{media_url}"

    targets = []
    pub_exp = PUBLIC_FORUM_ID or PUBLIC_EXPERIENCE
    pub_target = {"label": "public-space", "experience_id": pub_exp}
    if pub_exp == "public":
        # the special 'public' experience id needs the company context
        pub_target["company_id"] = COMPANY_ID
    targets.append(pub_target)
    if OWN_FORUM_ID:
        vbody, vtitle = _variation(body, piece["title"])
        targets.append({"label": "own-forum", "experience_id": OWN_FORUM_ID})
        variant_piece = dict(piece, body=vbody, title=vtitle)
    else:
        variant_piece = piece

    out = {}
    out["public"] = _post(targets[0], piece)
    if len(targets) > 1:
        out["own"] = _post(targets[1], variant_piece)
    return out


def run(pieces: list[dict], stagger: bool = True) -> list[dict]:
    results = []
    for i, p in enumerate(pieces[:MAX_POSTS_PER_RUN]):
        results.append(post_piece(p))
        if stagger and i < len(pieces[:MAX_POSTS_PER_RUN]) - 1:
            time.sleep(STAGGER)
    return results
