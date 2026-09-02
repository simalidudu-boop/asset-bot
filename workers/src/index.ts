/**
 * asset-bot-edge — Cloudflare Worker v5
 *
 * 1) GET  /                 -> serves the Command Center dashboard
 *                              (fetched from the repo, cached)
 * 2) POST /webhook/whop     -> Whop webhooks -> KV buffer -> GitHub dispatch
 * 3) POST /image            -> Flux Schnell via Workers AI (data-URI while
 *                              R2 is off; R2 optional upgrade)
 * 4) GET  /api/status       -> {ok, kill, dry}  (public)
 * 5) POST /api/set          -> kill_switch / dry_run toggles (X-Bot-Token)
 * 6) POST /api/dispatch     -> trigger GitHub workflows (X-Bot-Token)
 * 7) POST /api/comment      -> /approve or /reject review issues (X-Bot-Token)
 */

export interface Env {
  BOT_STATE: KVNamespace;
  PROMO_BUCKET: R2Bucket | undefined;
  GH_OWNER: string;
  GH_REPO: string;
  GH_TOKEN: string;
  BOT_TOKEN: string;
  AI: any;
}

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json" },
  });
}

// per-isolate cache for the GitHub read proxy (45s TTL applied at read time)
const ghCache = new Map<string, { t: number; body: string; status: number }>();

function authed(env: Env, request: Request): boolean {
  const t = request.headers.get("X-Bot-Token") ?? "";
  return !!env.BOT_TOKEN && t === env.BOT_TOKEN;
}

async function gh(env: Env, method: string, path: string, payload?: unknown) {
  const res = await fetch(`https://api.github.com${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${env.GH_TOKEN}`,
      "User-Agent": "asset-bot-edge",
      Accept: "application/vnd.github+json",
      "Content-Type": "application/json",
    },
    body: payload !== undefined ? JSON.stringify(payload) : undefined,
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`gh ${method} ${path} -> ${res.status}: ${text.slice(0, 200)}`);
  return text ? JSON.parse(text) : {};
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const p = url.pathname;

    // ---- dashboard (root) ----
    if (p === "/" && request.method === "GET") {
      const cache = caches.default;
      const cached = await cache.match(request);
      if (cached) return cached;
      try {
        const raw = `https://raw.githubusercontent.com/${env.GH_OWNER}/${env.GH_REPO}/main/dashboard/index.html`;
        const r = await fetch(raw, { cf: { cacheTtl: 300 } });
        if (!r.ok) throw new Error(`raw ${r.status}`);
        const html = await r.text();
        const resp = new Response(html, {
          headers: { "content-type": "text/html; charset=utf-8" },
        });
        // only cache success to avoid caching 404s
        await cache.put(request, resp.clone());
        return resp;
      } catch (e) {
        return json({ ok: true, service: "asset-bot-edge",
                      dashboard: "fetch failed — dashboard may not be pushed yet",
                      error: String(e) });
      }
    }

    // ---- webhook relay ----
    if (p === "/webhook/whop" && request.method === "POST") {
      try {
        const body = await request.text();
        let payload: unknown;
        try { payload = JSON.parse(body); } catch { payload = { raw: body }; }
        const key = `whop:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`;
        await env.BOT_STATE.put(key, body, { expirationTtl: 86400 });
        const type = (payload as { type?: string })?.type ?? "unknown";
        const eventType = `whop_${String(type).replace(/\./g, "_")}`;
        await gh(env, "POST", `/repos/${env.GH_OWNER}/${env.GH_REPO}/dispatches`,
                 { event_type: eventType, client_payload: { whop_key: key, type } });
        return json({ ok: true, queued: eventType });
      } catch (e) {
        return json({ ok: false, error: String(e) }, 502);
      }
    }

    // ---- image (Workers AI; R2 optional) ----
    if (p === "/image" && request.method === "POST") {
      try {
        const { prompt, name } = (await request.json()) as { prompt: string; name?: string };
        if (!prompt) return json({ error: "prompt required" }, 400);
        const ai = (await env.AI.run("@cf/black-forest-labs/flux-1-schnell", { prompt })) as { image?: string };
        if (!ai.image) return json({ error: "no image in AI response" }, 502);
        if (!env.PROMO_BUCKET) {
          return json({ ok: true, storage: "data-uri",
                        data_url: `data:image/jpeg;base64,${ai.image}` });
        }
        const bytes = Uint8Array.from(atob(ai.image), (c) => c.charCodeAt(0));
        const keyName = `${name ?? Date.now()}-${crypto.randomUUID().slice(0, 8)}.jpg`;
        await env.PROMO_BUCKET.put(keyName, bytes, { httpMetadata: { contentType: "image/jpeg" } });
        return json({ ok: true, url: `/promo/${keyName}` });
      } catch (e) {
        return json({ ok: false, error: String(e) }, 500);
      }
    }

    // ---- status ----
    if (p === "/api/status") {
      const kill = (await env.BOT_STATE.get("kill_switch")) === "1";
      const dry = (await env.BOT_STATE.get("dry_run")) === "1";
      return json({ ok: true, kill, dry, service: "asset-bot-edge" });
    }

    // ---- GitHub read proxy (dashboard uses this instead of hitting the
    //      unauthenticated API from the browser — no more 403 rate limits) ----
    if (p === "/api/github" && request.method === "GET") {
      const path = url.searchParams.get("path") ?? "";
      if (!/^\/(repos\/|search\/issues)/.test(path)) {
        return json({ error: "path not allowed" }, 400);
      }
      const cached = ghCache.get(path);
      if (cached && Date.now() - cached.t < 45000) {
        return new Response(cached.body, { headers: { "content-type": "application/json" } });
      }
      try {
        const res = await fetch(`https://api.github.com${path}`, {
          headers: {
            Authorization: `Bearer ${env.GH_TOKEN}`,
            "User-Agent": "asset-bot-edge",
            Accept: "application/vnd.github+json",
          },
        });
        const text = await res.text();
        if (!res.ok) {
          return json({ error: `github ${res.status}`, detail: text.slice(0, 400) }, res.status);
        }
        ghCache.set(path, { t: Date.now(), body: text, status: res.status });
        return new Response(text, { headers: { "content-type": "application/json" } });
      } catch (e) {
        return json({ error: String(e) }, 502);
      }
    }

    // ---- aggregated analytics (one call, server-side joined) ----
    if (p === "/api/summary" && request.method === "GET") {
      const owner = env.GH_OWNER, repo = env.GH_REPO;
      const ghJson = async (path: string) => {
        const r = await fetch(`https://api.github.com${path}`, {
          headers: {
            Authorization: `Bearer ${env.GH_TOKEN}`,
            "User-Agent": "asset-bot-edge",
            Accept: "application/vnd.github+json",
          },
        });
        if (!r.ok) throw new Error(`gh ${path} ${r.status}`);
        return r.json() as any;
      };
      const ghFile = async (fp: string) => {
        const d = await ghJson(`/repos/${owner}/${repo}/contents/${fp}`);
        return JSON.parse(atob(String(d.content).replace(/\s/g, "")));
      };
      const safe = async <T>(fn: () => Promise<T>, dflt: T): Promise<T> => {
        try { return await fn(); } catch { return dflt; }
      };

      const [runs, manifest, heartbeat, issues, kill, dry] = await Promise.all([
        safe(() => ghJson(`/repos/${owner}/${repo}/actions/runs?per_page=30`), { workflow_runs: [] } as any),
        safe(() => ghFile("state/manifest.json"), { assets: [], posts: [] } as any),
        safe(() => ghFile("state/heartbeat.json"), {} as any),
        safe(() => ghJson(`/search/issues?q=${encodeURIComponent(`repo:${owner}/${repo} label:asset-review state:open`)}`), { items: [] } as any),
        env.BOT_STATE.get("kill_switch"),
        env.BOT_STATE.get("dry_run"),
      ]);

      const wr = runs.workflow_runs || [];
      const now = Date.now();
      const since = (iso?: string) => iso ? Math.round((now - Date.parse(iso)) / 60000) : null;

      // per-workflow health
      const byWf: Record<string, any> = {};
      for (const r of wr) {
        const k = r.name || r.path;
        byWf[k] ??= { total: 0, success: 0, failure: 0, last: null, lastConclusion: null };
        byWf[k].total++;
        if (r.conclusion === "success") byWf[k].success++;
        if (r.conclusion === "failure") byWf[k].failure++;
        if (!byWf[k].last || r.created_at > byWf[k].last) {
          byWf[k].last = r.created_at; byWf[k].lastConclusion = r.conclusion;
        }
      }
      for (const k of Object.keys(byWf)) {
        byWf[k].successRate = byWf[k].total ? Math.round(100 * byWf[k].success / byWf[k].total) : null;
        byWf[k].ageMin = since(byWf[k].last);
      }

      // cron punctuality: compare scheduled runs to their slot
      const contentSlots = [1, 4, 7, 10, 13, 16, 19, 22];
      const lags: number[] = [];
      for (const r of wr) {
        if (r.event !== "schedule" || !/content/i.test(r.name || "")) continue;
        const t = new Date(r.created_at);
        let best: Date | null = null;
        for (const h of contentSlots) {
          const slot = new Date(Date.UTC(t.getUTCFullYear(), t.getUTCMonth(), t.getUTCDate(), h, 17, 0));
          if (slot <= t && (!best || slot > best)) best = slot;
        }
        if (best) lags.push(Math.round((t.getTime() - best.getTime()) / 60000));
      }
      const avgLag = lags.length ? Math.round(lags.reduce((a, b) => a + b, 0) / lags.length) : null;

      const assets = manifest.assets || [];
      const posts = manifest.posts || [];
      const fmtCount: Record<string, number> = {};
      for (const x of posts) fmtCount[x.fmt || "?"] = (fmtCount[x.fmt || "?"] || 0) + 1;
      const day = new Date().toISOString().slice(0, 10);
      const postsToday = posts.filter((x: any) => (x.at || "").slice(0, 10) === day).length;

      // staleness: expected a content run every 3h, daily every 24h
      const hbContent = since(heartbeat?.content?.at);
      const hbDaily = since(heartbeat?.daily?.at);
      const alerts: string[] = [];
      if (kill === "1") alerts.push("KILL SWITCH ON — all scheduled runs abort");
      if (dry === "1") alerts.push("DRY RUN ON — nothing is published");
      if (hbContent !== null && hbContent > 260) alerts.push(`No content run in ${Math.round(hbContent / 60)}h (expected every 3h)`);
      if (hbDaily !== null && hbDaily > 1560) alerts.push(`No daily cycle in ${Math.round(hbDaily / 60)}h (expected every 24h)`);
      if (hbContent === null) alerts.push("No content heartbeat recorded yet");
      const orphaned = assets.filter((a: any) => a.status === "orphaned").length;
      if (orphaned) alerts.push(`${orphaned} orphaned asset(s) in manifest`);
      const noLink = assets.filter((a: any) => a.free === true && !a.page_url).length;
      if (noLink) alerts.push(`${noLink} free asset(s) have no page_url`);
      for (const k of Object.keys(byWf)) {
        if (byWf[k].lastConclusion === "failure") alerts.push(`${k}: last run FAILED`);
      }

      return json({
        ok: true,
        generated_at: new Date().toISOString(),
        flags: { kill: kill === "1", dry: dry === "1" },
        alerts,
        workflows: byWf,
        cron: { avgLagMin: avgLag, samples: lags.length, lags },
        assets: {
          total: assets.length,
          free: assets.filter((a: any) => a.free === true).length,
          paid: assets.filter((a: any) => a.free === false && a.status !== "orphaned").length,
          live: assets.filter((a: any) => a.status === "live").length,
          orphaned,
          list: assets.slice(-12).reverse(),
        },
        posts: {
          total: posts.length,
          today: postsToday,
          formats: fmtCount,
          list: posts.slice(-15).reverse(),
        },
        heartbeat: { content: heartbeat?.content ?? null, daily: heartbeat?.daily ?? null,
                     contentAgeMin: hbContent, dailyAgeMin: hbDaily },
        review: { open: (issues.items || []).length,
                  items: (issues.items || []).map((i: any) => ({ number: i.number, title: i.title, url: i.html_url })) },
      });
    }

    // ---- set flags ----
    if (p === "/api/set" && request.method === "POST") {
      if (!authed(env, request)) return json({ error: "unauthorized" }, 401);
      const { key, value } = (await request.json()) as { key: string; value: boolean };
      if (!["kill_switch", "dry_run"].includes(key)) return json({ error: "bad key" }, 400);
      await env.BOT_STATE.put(key, value ? "1" : "0");
      return json({ ok: true, key, value: !!value });
    }

    // ---- dispatch workflows ----
    if (p === "/api/dispatch" && request.method === "POST") {
      if (!authed(env, request)) return json({ error: "unauthorized" }, 401);
      const { workflow, mock } = (await request.json()) as { workflow: string; mock?: boolean };
      const files: Record<string, string> = {
        "daily-cycle": "daily-cycle.yml",
        "content-posting": "content-posting.yml",
      };
      const file = files[workflow];
      if (!file) return json({ error: "unknown workflow" }, 400);
      await gh(env, "POST",
               `/repos/${env.GH_OWNER}/${env.GH_REPO}/actions/workflows/${file}/dispatches`,
               { ref: "main", inputs: mock ? { mock: "true" } : {} });
      return json({ ok: true, dispatched: workflow, mock: !!mock });
    }

    // ---- comment on review issues ----
    if (p === "/api/comment" && request.method === "POST") {
      if (!authed(env, request)) return json({ error: "unauthorized" }, 401);
      const { issue, command } = (await request.json()) as { issue: number; command: string };
      if (!issue || !["/approve", "/reject"].some(c => command.startsWith(c))) {
        return json({ error: "bad command" }, 400);
      }
      await gh(env, "POST", `/repos/${env.GH_OWNER}/${env.GH_REPO}/issues/${issue}/comments`,
               { body: command });
      return json({ ok: true, issue, command });
    }

    // ---- R2 passthroughs (dormant until R2 enabled) ----
    if (p.startsWith("/upload/") && request.method === "PUT") {
      if (!env.PROMO_BUCKET) return json({ error: "R2 not enabled" }, 503);
      if (!authed(env, request)) return json({ error: "unauthorized" }, 401);
      const name = p.slice("/upload/".length);
      if (!name || name.includes("..")) return json({ error: "bad name" }, 400);
      await env.PROMO_BUCKET.put(name, request.body, {
        httpMetadata: { contentType: request.headers.get("Content-Type") ?? "application/octet-stream" },
      });
      return json({ ok: true, url: `/promo/${name}` });
    }
    if (p.startsWith("/promo/")) {
      if (!env.PROMO_BUCKET) return json({ error: "R2 not enabled" }, 503);
      const obj = await env.PROMO_BUCKET.get(p.slice("/promo/".length));
      if (!obj) return json({ error: "not found" }, 404);
      return new Response(obj.body, {
        headers: {
          "content-type": obj.httpMetadata?.contentType ?? "image/jpeg",
          "cache-control": "public, max-age=31536000, immutable",
        },
      });
    }

    return json({ ok: true, service: "asset-bot-edge", v: 5 });
  },
};
