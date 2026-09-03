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


def _asset_bits(a: dict) -> tuple[str, str, str, str]:
    """(title, blurb, url, image) — the four things every channel wants."""
    title = a.get("title") or a.get("slug") or "New release"
    blurb = (a.get("description") or a.get("subtitle") or "").strip()
    url = a.get("page_url") or a.get("cdn_url") or a.get("landing_url") or ""
    imgs = a.get("gallery_images") or []
    image = imgs[0] if imgs else (a.get("image_url") or "")
    return title, blurb, url, image


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
    """Flat form fields (NOT Rails-nested) — per grain-works F7."""
    title, blurb, url, _ = _asset_bits(a)
    code, text = http("POST", "https://itch.io/game/new",
                      headers={"Authorization": f"Bearer {env('ITCH_API_KEY')}"},
                      form={"title": title[:100],
                            "short_text": blurb[:200],
                            "classification": "assets",
                            "user_id": env("ITCH_USERNAME"),
                            "external_link": url})
    return from_http(code, text)


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


# ---------------------------------------------------------------- Sell.app ---
def ch_sellapp(a: dict) -> dict:
    title, blurb, url, _ = _asset_bits(a)
    code, text = http("POST", "https://sell.app/api/v2/products",
                      headers={"Authorization": f"Bearer {env('SELLAPP_API_KEY')}",
                               "Accept": "application/json"},
                      json_body={"title": title[:150],
                                 # min 5 chars, else 422
                                 "description": (blurb + (f"\n\n{url}" if url else "")
                                                 or "Digital download.")[:2000],
                                 "visibility": "PUBLIC",
                                 # NOT `type` — that is always "invalid".
                                 # serials | service | dynamic
                                 "deliverables_type": "service",
                                 "currency": "USD",
                                 "price": {"amount": str(a.get("price") or 0),
                                           "currency": "USD"}})
    b = jbody(text)
    if code in (200, 201):
        d = b.get("data") or b
        pid, slug = str(d.get("id", "")), d.get("slug") or ""
        store = env("SELLAPP_STORE") or ""
        # VERIFY: sell.app returns 201 for products that do not actually
        # persist (observed 2026-09-03 — GET /products/{id} then 404s and the
        # list stays empty). Never trust the create response alone.
        vcode, _ = http("GET", f"https://sell.app/api/v2/products/{pid}",
                        headers={"Authorization": f"Bearer {env('SELLAPP_API_KEY')}",
                                 "Accept": "application/json"})
        if vcode != 200:
            return result(False, permanent=True,
                          error=f"created id={pid} but GET returned {vcode} — "
                                "product did not persist (store likely needs "
                                "setup/verification in the sell.app dashboard)")
        return result(True, pid,
                      f"https://{store}/product/{slug}" if store and slug else "")
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
def ch_webflow(a: dict) -> dict:
    title, blurb, url, image = _asset_bits(a)
    cid = env("WEBFLOW_COLLECTION_ID")
    fields = {"name": title[:250], "slug": (a.get("slug") or "")[:250]}
    if blurb:
        fields["summary"] = blurb[:1000]
    if url:
        fields["link"] = url
    if image:
        fields["image"] = image
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
    code, text = http("POST", "https://api.systeme.io/api/tags",
                      headers={"X-API-Key": env("SYSTEMEIO_API_KEY"),
                               "Content-Type": "application/json"},
                      json_body={"name": f"asset:{(a.get('slug') or title)[:60]}"})
    if code in (200, 201):
        b = jbody(text)
        return result(True, str(b.get("id", "")))
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

    Routing through it gives those platforms' reach without us being the
    party that breaks their automation terms. See docs/DISTRIBUTION_V2.md.
    """
    title, blurb, url, image = _asset_bits(a)
    text_body = f"{title}\n\n{blurb}"[:260] + (f"\n\n{url}" if url else "")
    ids = [i.strip() for i in env("BUFFER_CHANNEL_IDS").split(",") if i.strip()]
    if not ids:
        return result(False, error="no BUFFER_CHANNEL_IDS", permanent=True)
    mutation = ("mutation CreatePost($input: CreatePostInput!){createPost(input:$input){"
                "... on PostActionSuccess{post{id}}"
                "... on NotFoundError{message}"
                "... on UnauthorizedError{message}"
                "... on LimitReachedError{message}"
                "... on InvalidInputError{message}"
                "... on UnexpectedError{message}}}")
    inp = {"channelIds": ids, "text": text_body}
    if image:
        inp["assets"] = [{"type": "image", "source": image}]
    code, text = http("POST", "https://api.buffer.com/graphql",
                      headers={"Authorization": f"Bearer {env('BUFFER_ACCESS_TOKEN')}"},
                      json_body={"query": mutation, "variables": {"input": inp}})
    b = jbody(text)
    if code == 200 and not b.get("errors"):
        cp = ((b.get("data") or {}).get("createPost")) or {}
        if cp.get("post"):
            return result(True, str((cp["post"] or {}).get("id", "")))
        msg = cp.get("message") or "unknown buffer error"
        # LimitReached is temporary; auth/validation are not.
        perm = "limit" not in str(msg).lower()
        return result(False, error=str(msg), permanent=perm)
    errs = b.get("errors") or []
    return result(False,
                  error=str(errs[0].get("message") if errs else f"http_{code}"),
                  permanent=code in (401, 403))


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
register("itch",      ch_itch,      ["ITCH_API_KEY", "ITCH_USERNAME"])
register("sellix",    ch_sellix,    ["SELLIX_API_KEY"])
register("sellapp",   ch_sellapp,   ["SELLAPP_API_KEY"])
register("fetchapp",  ch_fetchapp,  ["FETCHAPP_KEY", "FETCHAPP_TOKEN"])
register("webflow",   ch_webflow,   ["WEBFLOW_TOKEN", "WEBFLOW_COLLECTION_ID"])
register("systemeio", ch_systemeio, ["SYSTEMEIO_API_KEY"])
register("archive",   ch_archive,   ["IA_ACCESS_KEY", "IA_SECRET_KEY"])
register("buffer",    ch_buffer,    ["BUFFER_ACCESS_TOKEN", "BUFFER_CHANNEL_IDS"])
