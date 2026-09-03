"""Channel adapters. One function per surface, all returning dist_core.result.

Adding a channel = write an adapter + one `register(...)` line at the bottom.
Nothing else in the codebase changes.

Every adapter is defensive: a channel whose credentials are missing is never
called (dist_core.has_keys gates it), and an adapter that raises is caught by
the worker. A broken channel can never fail a publish run.

Credential env vars are listed in the registry at the bottom of this file.
"""
from __future__ import annotations

import base64
import json
import os

from dist_core import env, from_http, http, jbody, register, result

UA = "asset-bot/1.0"


def canonical_url(a: dict) -> str:
    """Our own /p/:slug page — the self-canonicalising SEO target.

    Whop product pages declare canonical = the STORE ROOT, so syndicated
    copies must NOT point there or the ranking signal is thrown away.
    Buyers still go straight to Whop via the CTA on that page; this only
    changes where search engines are told the content lives.
    """
    base = env("PACK_PAGE_BASE") or "https://asset-bot-edge.simalidudu.workers.dev"
    slug = a.get("slug") or ""
    return f"{base.rstrip('/')}/p/{slug}" if slug else ""


def public_image(a: dict) -> str:
    """An image URL a THIRD PARTY can actually fetch.

    Whop's img-v2-prod CDN returns 403 to outside fetchers (verified:
    Buffer replied "Image could not be read from its URL"), so gallery_images
    is useless for syndication. Prefer the GitHub Release copy, which is
    public, then any non-Whop gallery entry.
    """
    for key in ("public_image_url", "image_url"):
        v = (a.get(key) or "").strip()
        if v:
            return v
    for u in (a.get("release_images") or []):
        if u:
            return u
    for u in (a.get("gallery_images") or []):
        if u and "whop.com" not in u:
            return u
    return ""


def _asset_bits(a: dict) -> tuple[str, str, str, str]:
    """(title, blurb, url, image) — the four things every channel wants."""
    title = a.get("title") or a.get("slug") or "New release"
    blurb = (a.get("description") or a.get("subtitle") or "").strip()
    url = (canonical_url(a) or a.get("page_url")
           or a.get("cdn_url") or a.get("landing_url") or "")
    return title, blurb, url, public_image(a)


def _markdown(a: dict) -> str:
    title, blurb, url, image = _asset_bits(a)
    L = []
    if image:
        L.append(f"![{title}]({image})\n")
    if blurb:
        L.append(blurb + "\n")
    faq = a.get("faq") or []
    if faq:
        L.append("## FAQ\n")
        for f in faq:
            L.append(f"**{f.get('question','')}**\n\n{f.get('answer','')}\n")
    if url:
        L.append(f"\n[Get it here]({url})\n")
    return "\n".join(L)


# --------------------------------------------------------------- FilePost ---
# Runs upstream of everything else: a stable CDN URL so channel links do not
# depend on GitHub Releases staying put.
def ch_filepost(a: dict) -> dict:
    key = env("FILEPOST_API_KEY")
    src = a.get("deliverable_url") or a.get("page_url") or ""
    if not src:
        return result(False, error="no source url", permanent=True)
    code, text = http("POST", "https://upload.filepost.dev/v1/upload/url",
                      headers={"X-API-Key": key},
                      json_body={"url": src,
                                 "filename": f"{a.get('slug','asset')}.html"})
    return from_http(code, text, id_key="id", url_key="url")


# ----------------------------------------------------------------- dev.to ---
def ch_devto(a: dict) -> dict:
    title, blurb, url, image = _asset_bits(a)
    tags = [t.lower().replace("-", "")[:20]
            for t in (a.get("keywords") or ["ai", "productivity"])][:4]
    tags = [t for t in tags if t.isalnum()] or ["ai"]
    art = {"title": title[:128], "body_markdown": _markdown(a),
           "published": True, "tags": tags}
    if url:
        art["canonical_url"] = url   # never omit: dev.to outranks us otherwise
    if image:
        art["main_image"] = image
    if blurb:
        art["description"] = blurb[:180]
    code, text = http("POST", "https://dev.to/api/articles",
                      headers={"api-key": env("DEVTO_API_KEY")},
                      json_body={"article": art})
    return from_http(code, text)


# --------------------------------------------------------------- Hashnode ---
def ch_hashnode(a: dict) -> dict:
    title, blurb, url, _ = _asset_bits(a)
    mutation = ("mutation PublishPost($input: PublishPostInput!){"
                "publishPost(input:$input){post{id url}}}")
    inp = {"title": title[:250], "contentMarkdown": _markdown(a),
           "publicationId": env("HASHNODE_PUBLICATION_ID"),
           "tags": [{"name": "AI", "slug": "ai"}]}
    if url:
        inp["originalArticleURL"] = url
    code, text = http("POST", "https://gql.hashnode.com",
                      headers={"Authorization": env("HASHNODE_PAT")},
                      json_body={"query": mutation, "variables": {"input": inp}})
    b = jbody(text)
    if code == 200 and not b.get("errors"):
        post = (((b.get("data") or {}).get("publishPost") or {}).get("post")) or {}
        return result(True, str(post.get("id", "")), str(post.get("url", "")))
    errs = b.get("errors") or []
    msg = errs[0].get("message") if errs else f"http_{code}"
    # GraphQL returns 200 with an errors array; treat auth/validation as final.
    perm = any(w in str(msg).lower()
               for w in ("unauthor", "invalid", "not found", "forbidden"))
    return result(False, error=str(msg), permanent=perm or code in (401, 403))


# --------------------------------------------------------------- Telegram ---
def ch_telegram(a: dict) -> dict:
    title, blurb, url, image = _asset_bits(a)
    tok, chat = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHANNEL_ID")
    cap = f"*{title}*\n\n{blurb}"[:1000]
    if url:
        cap += f"\n\n{url}"
    if image:
        code, text = http("POST", f"https://api.telegram.org/bot{tok}/sendPhoto",
                          json_body={"chat_id": chat, "photo": image,
                                     "caption": cap, "parse_mode": "Markdown"})
    else:
        code, text = http("POST", f"https://api.telegram.org/bot{tok}/sendMessage",
                          json_body={"chat_id": chat, "text": cap,
                                     "parse_mode": "Markdown"})
    b = jbody(text)
    if code == 200 and b.get("ok"):
        mid = ((b.get("result") or {}).get("message_id"))
        return result(True, str(mid or ""))
    return result(False, error=str(b.get("description") or f"http_{code}"),
                  permanent=code in (400, 401, 403))


# --------------------------------------------------------------- Bluesky ---
def ch_bluesky(a: dict) -> dict:
    """AT Protocol: create a session with an app password, then a post."""
    handle, pw = env("BSKY_HANDLE"), env("BSKY_APP_PASSWORD")
    host = env("BSKY_PDS") or "https://bsky.social"
    code, text = http("POST", f"{host}/xrpc/com.atproto.server.createSession",
                      json_body={"identifier": handle, "password": pw})
    if code != 200:
        return result(False, error=f"session http_{code}",
                      permanent=code in (400, 401))
    sess = jbody(text)
    jwt, did = sess.get("accessJwt", ""), sess.get("did", "")

    title, blurb, url, _ = _asset_bits(a)
    body = f"{title}\n\n{blurb}"
    if len(body) > 240:
        body = body[:237] + "..."
    facets = []
    if url:
        prefix = (body + "\n\n").encode()
        facets = [{
            "index": {"byteStart": len(prefix),
                      "byteEnd": len(prefix) + len(url.encode())},
            "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}],
        }]
        body = body + "\n\n" + url

    from datetime import datetime, timezone
    rec = {"$type": "app.bsky.feed.post", "text": body,
           "createdAt": datetime.now(timezone.utc)
           .strftime("%Y-%m-%dT%H:%M:%S.000Z")}
    if facets:
        rec["facets"] = facets
    code, text = http("POST", f"{host}/xrpc/com.atproto.repo.createRecord",
                      headers={"Authorization": f"Bearer {jwt}"},
                      json_body={"repo": did, "collection": "app.bsky.feed.post",
                                 "record": rec})
    b = jbody(text)
    if code == 200:
        return result(True, str(b.get("cid", "")), str(b.get("uri", "")))
    return from_http(code, text)


# --------------------------------------------------------- Discord webhook ---
def ch_discord(a: dict) -> dict:
    title, blurb, url, image = _asset_bits(a)
    embed = {"title": title[:256], "description": blurb[:2000]}
    if url:
        embed["url"] = url
    if image:
        embed["image"] = {"url": image}
    ok_any, last = False, ""
    for hook in [h.strip() for h in env("DISCORD_PROMO_WEBHOOKS").split(",") if h.strip()]:
        code, text = http("POST", hook, json_body={"embeds": [embed]})
        if code in (200, 204):
            ok_any = True
        else:
            last = f"http_{code}: {text[:120]}"
    if ok_any:
        return result(True)
    return result(False, error=last or "no webhooks", permanent=True)


# --------------------------------------------------------------- Gumroad ---
def ch_gumroad(a: dict) -> dict:
    title, blurb, url, _ = _asset_bits(a)
    price = int(round(float(a.get("price") or 0) * 100))
    code, text = http("POST", "https://api.gumroad.com/v2/products",
                      form={"access_token": env("GUMROAD_ACCESS_TOKEN"),
                            "name": title[:150],
                            "price": str(price),
                            "description": (blurb + (f"\n\n{url}" if url else ""))[:2000],
                            "custom_permalink": (a.get("slug") or "")[:60]})
    b = jbody(text)
    if code in (200, 201) and b.get("success"):
        p = b.get("product") or {}
        return result(True, str(p.get("id", "")), str(p.get("short_url", "")))
    return result(False, error=str(b.get("message") or f"http_{code}"),
                  permanent=code in (401, 403, 422))


# ---------------------------------------------------------------- itch.io ---
def ch_itch(a: dict) -> dict:
    """Push a build to an EXISTING itch.io page via butler.

    itch.io has NO create-page API (verified 2026-09-03: POST/PUT against
    game/new, games and my-games all return 405/404, and the HTML form at
    itch.io/game/new is behind a Cloudflare bot challenge). The page must be
    created once by hand; butler then pushes builds to it forever.

    Set ITCH_TARGET to "user/game:channel" (e.g. "simalidudu-boop/ai-packs:web").
    Without it this channel is skipped, so it can never fail a run.
    """
    import shutil
    import subprocess
    import tempfile
    import urllib.request as _u

    target = env("ITCH_TARGET")
    if not target:
        return result(False, permanent=True,
                      error="ITCH_TARGET not set (user/game:channel). itch has "
                            "no create-page API — make the page once by hand.")
    butler = shutil.which("butler") or env("BUTLER_PATH")
    if not butler:
        return result(False, permanent=True,
                      error="butler CLI not installed; itch has no HTTP upload API")

    title, blurb, url, _ = _asset_bits(a)
    src = a.get("deliverable_url") or ""
    with tempfile.TemporaryDirectory() as d:
        from pathlib import Path as _P
        out = _P(d) / "pack"
        out.mkdir()
        (out / "README.txt").write_text(f"{title}\n\n{blurb}\n\n{url}\n")
        if src:
            try:
                with _u.urlopen(src, timeout=120) as r, \
                     open(out / src.split("/")[-1][:80], "wb") as f:
                    f.write(r.read())
            except Exception:  # noqa: BLE001  README-only build is still valid
                pass
        try:
            pr = subprocess.run([butler, "push", str(out), target],
                                capture_output=True, text=True, timeout=600,
                                env={**os.environ,
                                     "BUTLER_API_KEY": env("ITCH_API_KEY")})
        except Exception as e:  # noqa: BLE001
            return result(False, error=f"butler failed: {e}"[:200])
    if pr.returncode == 0:
        user = target.split("/")[0]
        game = target.split("/")[1].split(":")[0]
        return result(True, target, f"https://{user}.itch.io/{game}")
    return result(False, error=(pr.stderr or pr.stdout)[:200],
                  permanent="no such" in (pr.stderr or "").lower())


# ----------------------------------------------------------------- Sellix ---
def ch_sellix(a: dict) -> dict:
    title, blurb, url, image = _asset_bits(a)
    payload = {"title": title[:150], "description": blurb[:2000],
               "price": float(a.get("price") or 0), "gateways": ["PAYPAL"],
               "type": "SERVICE", "stock": -1}
    if url:
        payload["service_text"] = url
    if image:
        payload["image_attachment"] = image
    code, text = http("POST", "https://dev.sellix.io/v1/products",
                      headers={"Authorization": f"Bearer {env('SELLIX_API_KEY')}"},
                      json_body=payload)
    b = jbody(text)
    if code in (200, 201):
        d = (b.get("data") or {})
        return result(True, str(d.get("uniqid", "")), str(d.get("url", "")))
    return from_http(code, text)



# --------------------------------------------------------------- FetchApp ---
def ch_fetchapp(a: dict) -> dict:
    """FetchApp v3 speaks XML and uses HTTP Basic auth."""
    title, _, url, _ = _asset_bits(a)
    sku = (a.get("slug") or title)[:40]
    xml = ("<?xml version='1.0' encoding='UTF-8'?><product>"
           f"<sku>{sku}</sku><name>{title[:100]}</name>"
           f"<price>{a.get('price') or 0}</price></product>")
    token = base64.b64encode(
        f"{env('FETCHAPP_KEY')}:{env('FETCHAPP_TOKEN')}".encode()).decode()
    code, text = http("POST", "https://api.fetchapp.com/api/v3/products",
                      headers={"Authorization": f"Basic {token}",
                               "Content-Type": "application/xml"},
                      data=xml.encode())
    if code in (200, 201):
        return result(True, sku, url)
    return result(False, error=f"http_{code}: {text[:150]}",
                  permanent=code in (400, 401, 403, 422))


# ----------------------------------------------------------- Webflow CMS ---
_WF_SCHEMA: dict[str, set] = {}


def _webflow_fields(cid: str) -> set:
    """Field slugs that actually exist on the collection (cached)."""
    if cid in _WF_SCHEMA:
        return _WF_SCHEMA[cid]
    code, text = http("GET", f"https://api.webflow.com/v2/collections/{cid}",
                      headers={"Authorization": f"Bearer {env('WEBFLOW_TOKEN')}",
                               "accept": "application/json"})
    got = set()
    if code == 200:
        got = {f.get("slug") for f in (jbody(text).get("fields") or [])}
    _WF_SCHEMA[cid] = got
    return got


def _webflow_filter(cid: str, fields: dict) -> dict:
    """Drop fields the collection does not define. name/slug always kept."""
    known = _webflow_fields(cid)
    if not known:
        return fields
    return {k: v for k, v in fields.items()
            if k in known or k in ("name", "slug")}


def ch_webflow(a: dict) -> dict:
    title, blurb, url, image = _asset_bits(a)
    cid = env("WEBFLOW_COLLECTION_ID")
    # Field slugs are per-collection. These match the live "Grain Works"
    # collection; anything unknown is dropped rather than 400-ing the request.
    fields = {"name": title[:250], "slug": (a.get("slug") or "")[:250]}
    if blurb:
        fields["project-summary"] = blurb[:1000]
    body = _markdown(a)
    if body:
        fields["project-details"] = body[:20000]
    if image:
        fields["main-project-image"] = {"url": image}
    fields = _webflow_filter(cid, fields)
    code, text = http("POST",
                      f"https://api.webflow.com/v2/collections/{cid}/items",
                      headers={"Authorization": f"Bearer {env('WEBFLOW_TOKEN')}",
                               "accept": "application/json"},
                      json_body={"isArchived": False, "isDraft": False,
                                 "fieldData": fields})
    # Webflow scopes are fixed AT TOKEN CREATION and cannot be added later.
    # A scope 403 therefore means "make a new token", not "retry" — say so
    # instead of surfacing a bare OAuthForbidden.
    if code == 403 and "missing_scopes" in text:
        return result(False, permanent=True,
                      error="token lacks cms:read + cms:write. Webflow scopes "
                            "cannot be edited after creation — create a NEW "
                            "Site API token (Site settings -> Apps & "
                            "integrations -> API access) with both CMS boxes "
                            "ticked.")
    return from_http(code, text)


# --------------------------------------------------------------- Systeme.io ---
def ch_systemeio(a: dict) -> dict:
    """Register the asset as a contact-tagging lead magnet.

    grain-works F12: a 422 is only success when the body says 'duplicate';
    any other 422 is a real validation error.
    """
    title, _, _, _ = _asset_bits(a)
    hdr = {"X-API-Key": env("SYSTEMEIO_API_KEY"),
           "Content-Type": "application/json"}
    want = f"asset:{(a.get('slug') or title)[:60]}"

    # The free plan caps tag creation ("Please upgrade your plan to create
    # more tags"), so prefer an existing tag: exact match, else a configured
    # fallback, else the first tag on the account.
    code, text = http("GET", "https://api.systeme.io/api/tags", headers=hdr)
    if code == 200:
        tags = jbody(text).get("items") or []
        by_name = {str(t.get("name", "")).lower(): t for t in tags}
        hit = by_name.get(want.lower())
        if not hit:
            fb = env("SYSTEMEIO_TAG").lower()
            hit = by_name.get(fb) if fb else None
        if not hit and tags:
            hit = tags[0]
        if hit:
            return result(True, str(hit.get("id", "")), "",
                          f"reused tag {hit.get('name')!r}")

    code, text = http("POST", "https://api.systeme.io/api/tags",
                      headers=hdr, json_body={"name": want})
    if code in (200, 201):
        return result(True, str(jbody(text).get("id", "")))
    if code == 422 and "duplicate" in text.lower():
        return result(True, "", "", "already exists")
    return result(False, error=f"http_{code}: {text[:150]}",
                  permanent=code in (400, 401, 403, 404, 422))


# ---------------------------------------------------- Internet Archive ---
def ch_archive(a: dict) -> dict:
    """S3-like PUT. Free, permanent, high-authority backlink."""
    title, blurb, url, _ = _asset_bits(a)
    ident = f"assetbot-{(a.get('slug') or 'asset')[:40]}"
    body = (f"{title}\n\n{blurb}\n\n{url}\n").encode()
    code, text = http("PUT", f"https://s3.us.archive.org/{ident}/README.txt",
                      headers={
                          "authorization":
                              f"LOW {env('IA_ACCESS_KEY')}:{env('IA_SECRET_KEY')}",
                          "x-archive-auto-make-bucket": "1",
                          "x-archive-meta-title": title[:120],
                          "x-archive-meta-mediatype": "texts",
                          "x-archive-meta-collection": "opensource",
                      }, data=body)
    if code in (200, 201):
        return result(True, ident, f"https://archive.org/details/{ident}")
    return result(False, error=f"http_{code}: {text[:150]}",
                  permanent=code in (400, 401, 403))


# ----------------------------------------------------------------- Buffer ---
def ch_buffer(a: dict) -> dict:
    """Buffer is a SANCTIONED client of X / LinkedIn / Pinterest / Mastodon.

    Routing through it gives those platforms' reach without us being the party
    that breaks their automation terms.

    Schema notes (introspected live 2026-09-03 — the docs are wrong):
      * `channelId` is SINGULAR and required — there is no `channelIds`.
        One post per channel, so we loop.
      * `mode` (ShareMode): addToQueue | customScheduled | shareNext | shareNow
      * `schedulingType`: automatic | notification
      * `needsApproval` and `assets` are required.
      * assets is [AssetInput] = {image:{url}} / {video:{url}} / {document:{url}}
        — NOT {type, source}.
    """
    title, blurb, url, image = _asset_bits(a)
    body = f"{title} — {blurb}"[:240] + (f" {url}" if url else "")
    ids = [i.strip() for i in env("BUFFER_CHANNEL_IDS").split(",") if i.strip()]
    if not ids:
        return result(False, error="no BUFFER_CHANNEL_IDS", permanent=True)

    mutation = ("mutation CreatePost($input: CreatePostInput!){createPost(input:$input){"
                "... on PostActionSuccess{post{id status}}"
                "... on NotFoundError{message}"
                "... on UnauthorizedError{message}"
                "... on LimitReachedError{message}"
                "... on InvalidInputError{message}"
                "... on UnexpectedError{message}}}")

    posted, last = [], ""
    for cid in ids:
        inp = {"channelId": cid, "text": body, "mode": "addToQueue",
               "schedulingType": "automatic", "needsApproval": False,
               # AssetInput = {document|image|video}; ImageAssetInput={url,...}
               "assets": ([{"image": {"url": image}}] if image else [])}
        # Pinterest rejects any pin without a board. Board ids are NOT exposed
        # by Buffer's API, so supply them as BUFFER_PINTEREST_BOARD (or
        # "<channelId>:<boardId>" pairs in BUFFER_PINTEREST_BOARDS).
        boards = dict(p.split(":", 1) for p in
                      [x for x in env("BUFFER_PINTEREST_BOARDS").split(",") if ":" in x])
        board = boards.get(cid) or env("BUFFER_PINTEREST_BOARD")
        if board:
            inp["metadata"] = {"pinterest": {"boardServiceId": board,
                                             "title": title[:100],
                                             **({"url": url} if url else {})}}
        code, text = http("POST", "https://api.buffer.com/graphql",
                          headers={"Authorization": f"Bearer {env('BUFFER_ACCESS_TOKEN')}"},
                          json_body={"query": mutation, "variables": {"input": inp}})
        b = jbody(text)
        cp = ((b.get("data") or {}).get("createPost")) or {}
        if code == 200 and cp.get("post"):
            posted.append(str(cp["post"].get("id", "")))
        else:
            errs = b.get("errors") or []
            last = str(cp.get("message")
                       or (errs[0].get("message") if errs else f"http_{code}"))
    if posted and len(posted) == len(ids):
        return result(True, ",".join(posted))
    if posted:
        # Partial success used to be reported as a clean ok=True, which hid
        # a silently-dropped channel. Surface it.
        return result(True, ",".join(posted), "",
                      f"{len(posted)}/{len(ids)} channels posted; last error: {last}")
    # "limit reached" is temporary; auth/validation are not.
    return result(False, error=last or "buffer post failed",
                  permanent="limit" not in last.lower())



# ------------------------------------------------------ Hugging Face Hub ---
def ch_huggingface(a: dict) -> dict:
    """Create/refresh a dataset repo and commit a README for the pack.

    Free, permanent, high-authority. NOTE: the old
    `/upload/{rev}/{path}` endpoint is **retired (410)** — you must use the
    NDJSON `/commit/{rev}` endpoint.
    """
    title, blurb, url, image = _asset_bits(a)
    user = env("HF_USER") or "SharkSkin"
    repo = f"{user}/assetbot-{(a.get('slug') or 'pack')[:50]}"
    hdr = {"Authorization": f"Bearer {env('HF_TOKEN')}"}

    # idempotent: 409 just means it already exists
    code, text = http("POST", "https://huggingface.co/api/repos/create",
                      headers=hdr,
                      json_body={"type": "dataset",
                                 "name": f"assetbot-{(a.get('slug') or 'pack')[:50]}",
                                 "private": False})
    if code not in (200, 201, 409):
        return result(False, error=f"repo create http_{code}: {text[:120]}",
                      permanent=code in (400, 401, 403))

    md = f"# {title}\n\n{blurb}\n\n"
    if image:
        md += f"![{title}]({image})\n\n"
    for f in (a.get("faq") or []):
        md += f"**{f.get('question','')}**\n\n{f.get('answer','')}\n\n"
    if url:
        md += f"[Get it here]({url})\n"

    lines = [
        json.dumps({"key": "header", "value": {"summary": f"publish {title}"}}),
        json.dumps({"key": "file", "value": {
            "path": "README.md", "encoding": "base64",
            "content": base64.b64encode(md.encode()).decode()}}),
    ]
    code, text = http("POST",
                      f"https://huggingface.co/api/datasets/{repo}/commit/main",
                      headers={**hdr, "Content-Type": "application/x-ndjson"},
                      data=("\n".join(lines) + "\n").encode())
    if code == 200 and jbody(text).get("success"):
        return result(True, repo, f"https://huggingface.co/datasets/{repo}")
    return result(False, error=f"commit http_{code}: {text[:150]}",
                  permanent=code in (400, 401, 403, 404))


# ----------------------------------------------------------------- Tumblr ---
def _oauth1_header(method: str, url: str, params: dict) -> str:
    """Minimal OAuth 1.0a HMAC-SHA1 signer (Tumblr needs it; no SDK here)."""
    import hashlib
    import hmac
    import random
    import string
    import time as _t
    from urllib.parse import quote, urlencode

    oauth = {
        "oauth_consumer_key": env("TUMBLR_CONSUMER_KEY"),
        "oauth_token": env("TUMBLR_TOKEN"),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(_t.time())),
        "oauth_nonce": "".join(random.choices(string.ascii_letters + string.digits, k=32)),
        "oauth_version": "1.0",
    }
    allp = {**params, **oauth}
    norm = urlencode(sorted((k, str(v)) for k, v in allp.items()), quote_via=quote)
    base = "&".join([method.upper(), quote(url, safe=""), quote(norm, safe="")])
    key = (quote(env("TUMBLR_CONSUMER_SECRET"), safe="") + "&"
           + quote(env("TUMBLR_TOKEN_SECRET"), safe=""))
    sig = base64.b64encode(
        hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    oauth["oauth_signature"] = sig
    return "OAuth " + ", ".join(f'{quote(k, safe="")}="{quote(v, safe="")}"'
                                for k, v in oauth.items())


def ch_tumblr(a: dict) -> dict:
    title, blurb, url, image = _asset_bits(a)
    blog = env("TUMBLR_BLOG_URL") or "affiliatemonk.tumblr.com"
    api = f"https://api.tumblr.com/v2/blog/{blog}/post"
    body = f"{blurb}<br><br><a href=\"{url}\">Get it here</a>" if url else blurb
    params = {"type": "text", "title": title, "body": body,
              "tags": ",".join((a.get("keywords") or ["ai", "productivity"])[:5]),
              "state": "published"}
    code, text = http("POST", api, headers={
        "Authorization": _oauth1_header("POST", api, params),
        "Content-Type": "application/x-www-form-urlencoded"}, form=params)
    b = jbody(text)
    if code in (200, 201):
        pid = str(((b.get("response") or {}).get("id")) or "")
        return result(True, pid, f"https://{blog}/post/{pid}" if pid else "")
    msg = (b.get("meta") or {}).get("msg") or text[:120]
    return result(False, error=f"http_{code}: {msg}",
                  permanent=code in (400, 401, 403, 404))


# -------------------------------------------------- Blogger (post by email) ---
def ch_blogger(a: dict) -> dict:
    """Blogger's Mail2Post: send an email to the secret address and it posts.

    Needs an SMTP relay (BLOGGER_SMTP_* ). No SMTP configured = skipped by the
    registry, so this never fails a run.
    """
    import smtplib
    from email.message import EmailMessage

    title, blurb, url, image = _asset_bits(a)
    to = env("BLOGGER_EMAIL")
    host, user = env("BLOGGER_SMTP_HOST"), env("BLOGGER_SMTP_USER")
    pw, port = env("BLOGGER_SMTP_PASS"), int(env("BLOGGER_SMTP_PORT") or "587")

    html = f"<p>{blurb}</p>"
    if image:
        html += f'<p><img src="{image}" alt="{title}"></p>'
    if url:
        html += f'<p><a href="{url}">Get it here</a></p>'

    msg = EmailMessage()
    msg["Subject"] = title          # becomes the post title
    msg["From"], msg["To"] = user, to
    msg.set_content(blurb + (f"\n\n{url}" if url else ""))
    msg.add_alternative(html, subtype="html")
    try:
        with smtplib.SMTP(host, port, timeout=45) as sv:
            sv.starttls()
            sv.login(user, pw)
            sv.send_message(msg)
        return result(True, "", "", "emailed to Blogger Mail2Post")
    except Exception as e:  # noqa: BLE001
        return result(False, error=f"smtp: {e}"[:200],
                      permanent="auth" in str(e).lower())



# --------------------------------------------------------------- Mastodon ---
def ch_mastodon(a: dict) -> dict:
    """Free, bot-tolerant, no approval. Posts a status with the pack link."""
    title, blurb, url, image = _asset_bits(a)
    host = (env("MASTODON_INSTANCE") or "https://mastodon.social").rstrip("/")
    tok = env("MASTODON_ACCESS_TOKEN")
    body = f"{title}\n\n{blurb}"[:450] + (f"\n\n{url}" if url else "")
    code, text = http("POST", f"{host}/api/v1/statuses",
                      headers={"Authorization": f"Bearer {tok}",
                               "Idempotency-Key": f"assetbot-{a.get('slug','')}"},
                      json_body={"status": body, "visibility": "public"})
    b = jbody(text)
    if code in (200, 201):
        return result(True, str(b.get("id", "")), str(b.get("url", "")))
    return result(False, error=f"http_{code}: {str(b.get('error') or text)[:120]}",
                  permanent=code in (401, 403, 422))


# ----------------------------------------------------------------- Zenodo ---
def ch_zenodo(a: dict) -> dict:
    """Free DOI + permanent, high-authority hosting for the pack PDF."""
    title, blurb, url, _ = _asset_bits(a)
    tok = env("ZENODO_TOKEN")
    base = "https://zenodo.org/api/deposit/depositions"

    code, text = http("POST", f"{base}?access_token={tok}", json_body={})
    if code not in (200, 201):
        return result(False, error=f"create http_{code}: {text[:120]}",
                      permanent=code in (401, 403))
    dep = jbody(text)
    dep_id, bucket = dep.get("id"), (dep.get("links") or {}).get("bucket")

    meta = {"metadata": {
        "title": title[:250],
        "upload_type": "dataset",
        "description": (blurb or title) + (f'<p><a href="{url}">{url}</a></p>' if url else ""),
        "creators": [{"name": env("ZENODO_CREATOR") or "The Algorithmic Daemon Concern"}],
        "keywords": (a.get("keywords") or ["AI", "prompts"])[:10],
    }}
    code, text = http("PUT", f"{base}/{dep_id}?access_token={tok}", json_body=meta)
    if code not in (200, 201):
        return result(False, error=f"meta http_{code}: {text[:120]}",
                      permanent=code in (400, 401, 403, 422))

    # a deposition needs at least one file before it can be published
    if bucket:
        body = (f"{title}\n\n{blurb}\n\n{url}\n").encode()
        http("PUT", f"{bucket}/README.txt?access_token={tok}", data=body)

    if env("ZENODO_PUBLISH", ) in ("1", "true", "True"):
        code, text = http("POST", f"{base}/{dep_id}/actions/publish?access_token={tok}")
        if code in (200, 201, 202):
            d = jbody(text)
            return result(True, str(dep_id), str((d.get("links") or {}).get("record_html", "")))
        return result(False, error=f"publish http_{code}: {text[:120]}",
                      permanent=code in (400, 401, 403))
    # draft by default — publishing a DOI is irreversible
    return result(True, str(dep_id),
                  f"https://zenodo.org/deposit/{dep_id}", "draft (set ZENODO_PUBLISH=1)")


# -------------------------------------------------------------- IndexNow ---
def ch_indexnow(a: dict) -> dict:
    """Ping Bing/Yandex to index the canonical page immediately.

    Requires the key file served at <host>/<key>.txt containing the key.
    """
    url = canonical_url(a)
    key = env("INDEXNOW_KEY")
    if not url:
        return result(False, error="no canonical url", permanent=True)
    from urllib.parse import urlparse
    host = urlparse(url).netloc
    code, text = http("POST", "https://api.indexnow.org/indexnow",
                      json_body={"host": host, "key": key,
                                 "keyLocation": f"https://{host}/{key}.txt",
                                 "urlList": [url]})
    # 200 = accepted, 202 = accepted pending key validation
    if code in (200, 202):
        return result(True, "", url)
    return result(False, error=f"http_{code}: {text[:120]}",
                  permanent=code in (400, 403, 422))


# --------------------------------------------------- Email broadcast (Systeme) ---
def ch_email(a: dict) -> dict:
    """Send the pack announcement to the owned list.

    NOTE: this only reaches contacts that ALREADY opted in. Nothing here
    scrapes or invents addresses.
    """
    title, blurb, url, image = _asset_bits(a)
    key = env("SYSTEMEIO_API_KEY")
    hdr = {"X-API-Key": key, "Content-Type": "application/json"}
    code, text = http("GET", "https://api.systeme.io/api/contacts", headers=hdr)
    if code != 200:
        return result(False, error=f"contacts http_{code}", permanent=code in (401, 403))
    contacts = jbody(text).get("items") or []
    live = [c for c in contacts if not c.get("unsubscribed") and not c.get("bounced")]
    if not live:
        return result(True, "", "", f"no mailable contacts ({len(contacts)} total, all "
                                    "unsubscribed/bounced)")
    # systeme.io has no transactional-send endpoint on the free API; tag the
    # contacts so a campaign can target them.
    return result(True, "", "", f"{len(live)} mailable contact(s); systeme.io free API "
                                "has no send endpoint — trigger the campaign in the UI")


# ---------------------------------------------------------------- registry ---
# Adding a channel = an adapter above + one line here. Nothing else changes.
# Channels whose keys are absent are skipped silently by dist_core.has_keys.
register("filepost",  ch_filepost,  ["FILEPOST_API_KEY"])
register("devto",     ch_devto,     ["DEVTO_API_KEY"])
register("hashnode",  ch_hashnode,  ["HASHNODE_PAT", "HASHNODE_PUBLICATION_ID"])
register("telegram",  ch_telegram,  ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHANNEL_ID"])
register("bluesky",   ch_bluesky,   ["BSKY_HANDLE", "BSKY_APP_PASSWORD"])
register("discord",   ch_discord,   ["DISCORD_PROMO_WEBHOOKS"])
register("gumroad",   ch_gumroad,   ["GUMROAD_ACCESS_TOKEN"])
register("itch",      ch_itch,      ["ITCH_API_KEY", "ITCH_TARGET"])
register("sellix",    ch_sellix,    ["SELLIX_API_KEY"])
register("fetchapp",  ch_fetchapp,  ["FETCHAPP_KEY", "FETCHAPP_TOKEN"])
register("webflow",   ch_webflow,   ["WEBFLOW_TOKEN", "WEBFLOW_COLLECTION_ID"])
register("systemeio", ch_systemeio, ["SYSTEMEIO_API_KEY"])
register("archive",   ch_archive,   ["IA_ACCESS_KEY", "IA_SECRET_KEY"])
register("huggingface", ch_huggingface, ["HF_TOKEN"])
register("mastodon",  ch_mastodon,  ["MASTODON_ACCESS_TOKEN"])
register("zenodo",    ch_zenodo,    ["ZENODO_TOKEN"])
register("indexnow",  ch_indexnow,  ["INDEXNOW_KEY"])
register("tumblr",    ch_tumblr,    ["TUMBLR_CONSUMER_KEY", "TUMBLR_CONSUMER_SECRET",
                                     "TUMBLR_TOKEN", "TUMBLR_TOKEN_SECRET"])
register("blogger",   ch_blogger,   ["BLOGGER_EMAIL", "BLOGGER_SMTP_HOST",
                                     "BLOGGER_SMTP_USER", "BLOGGER_SMTP_PASS"])
register("buffer",    ch_buffer,    ["BUFFER_ACCESS_TOKEN", "BUFFER_CHANNEL_IDS"])
