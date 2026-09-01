/**
 * asset-bot-edge — Cloudflare Worker
 *
 * 1) POST /webhook/whop   — receive Whop webhooks, buffer to KV, fire
 *    GitHub repository_dispatch so Actions runs the matching workflow.
 *    Returns 200 immediately (Whop requires a fast 2xx).
 * 2) POST /image          — Flux Schnell image via Workers AI, stored in R2,
 *    returns public CDN URL. Used by the media pipeline.
 * 3) GET /state           — small JSON view of KV counters (health/debug).
 *
 * Secrets (wrangler secret put): GH_TOKEN, CF account id via env/CLOUDFLARE_ACCOUNT_ID
 */

export interface Env {
  BOT_STATE: KVNamespace;
  PROMO_BUCKET: R2Bucket;
  GH_OWNER: string;
  GH_REPO: string;
  GH_TOKEN: string;
  BOT_TOKEN: string; // shared secret for uploads from GitHub Actions
  AI: any; // Workers AI binding (native auth, no token needed)
}

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/** Forward event to GitHub Actions via repository_dispatch. */
async function dispatchGh(env: Env, eventType: string, payload: unknown) {
  const url = `https://api.github.com/repos/${env.GH_OWNER}/${env.GH_REPO}/dispatches`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GH_TOKEN}`,
      "User-Agent": "asset-bot-edge",
      Accept: "application/vnd.github+json",
    },
    body: JSON.stringify({
      event_type: eventType,
      client_payload: payload,
    }),
  });
  if (!res.ok) {
    throw new Error(`dispatch failed: ${res.status} ${await res.text()}`);
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/webhook/whop" && request.method === "POST") {
      try {
        const body = await request.text();
        let payload: unknown;
        try { payload = JSON.parse(body); } catch { payload = { raw: body }; }
        const ts = Date.now();
        const key = `whop:${ts}:${Math.random().toString(36).slice(2, 8)}`;
        await env.BOT_STATE.put(key, body, { expirationTtl: 86400 });

        // Map Whop event type -> GitHub dispatch event
        const type = (payload as { type?: string })?.type ?? "unknown";
        const eventType = `whop_${String(type).replace(/\./g, "_")}`;
        await dispatchGh(env, eventType, { whop_key: key, type });
        return json({ ok: true, queued: eventType });
      } catch (e) {
        return json({ ok: false, error: String(e) }, 502);
      }
    }

    if (url.pathname === "/image" && request.method === "POST") {
      try {
        const { prompt, name } = (await request.json()) as { prompt: string; name?: string };
        if (!prompt) return json({ error: "prompt required" }, 400);

        // Workers AI binding — platform auth, billed in free neurons
        const ai = (await env.AI.run("@cf/black-forest-labs/flux-1-schnell", {
          prompt,
        })) as { image?: string };
        if (!ai.image) return json({ error: "no image in AI response" }, 502);

        const bytes = Uint8Array.from(atob(ai.image), (c) => c.charCodeAt(0));
        // R2 not enabled yet? Return a data URI instead (spike/fallback mode).
        if (!env.PROMO_BUCKET) {
          return json({ ok: true, storage: "data-uri",
                        data_url: `data:image/jpeg;base64,${ai.image}` });
        }
        const keyName = `${name ?? Date.now()}-${crypto.randomUUID().slice(0, 8)}.jpg`;
        await env.PROMO_BUCKET.put(keyName, bytes, { httpMetadata: { contentType: "image/jpeg" } });
        return json({ ok: true, url: `/promo/${keyName}` });
      } catch (e) {
        return json({ ok: false, error: String(e) }, 500);
      }
    }

    if (url.pathname.startsWith("/upload/") && request.method === "PUT") {
      if (!env.PROMO_BUCKET) {
        return json({ error: "R2 storage not enabled on this account yet" }, 503);
      }
      const auth = request.headers.get("X-Bot-Token");
      if (!env.BOT_TOKEN || auth !== env.BOT_TOKEN) {
        return json({ error: "unauthorized" }, 401);
      }
      const name = url.pathname.slice("/upload/".length);
      if (!name || name.includes("..")) return json({ error: "bad name" }, 400);
      const contentType = request.headers.get("Content-Type") ?? "application/octet-stream";
      await env.PROMO_BUCKET.put(name, request.body, {
        httpMetadata: { contentType },
      });
      return json({ ok: true, url: `/promo/${name}`, name });
    }

    if (url.pathname.startsWith("/promo/")) {
      if (!env.PROMO_BUCKET) {
        return json({ error: "R2 storage not enabled on this account yet" }, 503);
      }
      const obj = await env.PROMO_BUCKET.get(url.pathname.slice("/promo/".length));
      if (!obj) return json({ error: "not found" }, 404);
      return new Response(obj.body, {
        headers: {
          "content-type": obj.httpMetadata?.contentType ?? "image/jpeg",
          "cache-control": "public, max-age=31536000, immutable",
        },
      });
    }

    if (url.pathname === "/state") {
      const list = await env.BOT_STATE.list({ limit: 25 });
      return json({ keys: list.keys.map((k) => k.name) });
    }

    return json({ ok: true, service: "asset-bot-edge", v: 4 });
  },
};
