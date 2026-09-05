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

import { TOOLS, toolBySlug, renderTool, renderIndex } from "./tools";

export interface Env {
  BOT_STATE: KVNamespace;
  PROMO_BUCKET: R2Bucket | undefined;
  GH_OWNER: string;
  GH_REPO: string;
  GH_TOKEN: string;
  BOT_TOKEN: string;
  AI: any;
  KOFI_VERIFICATION_TOKEN: string;
  INDEXNOW_KEY: string;
  LIGHTNING_ADDRESS: string;
  DISCORD_ALERT_WEBHOOK: string;
}

const CONFIG_DEFAULTS: Record<string, string | number | boolean> = {
  N_FREE: 1,          // free assets per daily cycle
  N_PAID: 2,          // paid assets per daily cycle
  N_POSTS: 1,         // content pieces per content run
  POST_LANGS: "en",   // comma-separated language codes
  N_IMAGES: 2,        // promo images per asset
  MAKE_VIDEO: true,   // build slideshow videos
  ENABLE_POST_MEDIA: true,  // attach an image to image/video posts
  PREFLIGHT_STRICT: true,   // fail runs on fatal misconfiguration
};

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
      // Cache keyed on the bare URL, ignoring ?v= busters, with a real TTL.
      // Previously the response was cache.put() with no Cache-Control, so the
      // edge held the old dashboard forever and "/" served a stale build while
      // "/?v=N" served the new one. Always give the entry an explicit max-age.
      const cache = caches.default;
      const cacheKey = new Request(new URL(url.pathname, url.origin).toString(),
                                   { method: "GET" });
      const bust = url.searchParams.has("v") || url.searchParams.has("nocache");
      if (!bust) {
        const cached = await cache.match(cacheKey);
        if (cached) {
          const body = await cached.text();
          return new Response(body, {
            headers: {
              "content-type": "text/html; charset=utf-8",
              "cache-control": "no-store, must-revalidate",
              "x-dashboard-ref": cached.headers.get("x-dashboard-ref") ?? "cache",
            },
          });
        }
      }
      try {
        // pin to the current commit so a push invalidates immediately
        let ref = "main";
        try {
          const head = await gh(env, "GET", `/repos/${env.GH_OWNER}/${env.GH_REPO}/commits/main`);
          if (head?.sha) ref = head.sha;
        } catch { /* fall back to main */ }
        const raw = `https://raw.githubusercontent.com/${env.GH_OWNER}/${env.GH_REPO}/${ref}/dashboard/index.html`;
        const r = await fetch(raw, { cf: { cacheTtl: 30 } });
        if (!r.ok) throw new Error(`raw ${r.status}`);
        // Stamp the served commit into the page so the build is visible
        // on screen — no need to open devtools to check for staleness.
        const html = (await r.text()).replace(/__BUILD__/g, ref.slice(0, 7));
        // Two different cache policies on purpose:
        //  - the EDGE copy may live 60s (cheap, shared)
        //  - the BROWSER must always revalidate, otherwise a user who loaded
        //    the pre-tabs build keeps it forever (the original response had no
        //    Cache-Control at all, so browsers cached it heuristically).
        const edgeResp = new Response(html, {
          headers: {
            "content-type": "text/html; charset=utf-8",
            "cache-control": "public, max-age=60",
            "x-dashboard-ref": ref.slice(0, 7),
          },
        });
        await cache.put(cacheKey, edgeResp.clone());
        return new Response(html, {
          headers: {
            "content-type": "text/html; charset=utf-8",
            "cache-control": "no-store, must-revalidate",
            "x-dashboard-ref": ref.slice(0, 7),
          },
        });
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
        // ignore ghost entries from pushes that failed YAML validation —
        // they are named ".github/workflows/x.yml" and no longer exist
        if ((r.name || "").startsWith(".github/")) continue;
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
      const notListed = assets.filter((a: any) =>
        a.product_id && a.marketplace_status &&
        a.marketplace_status !== "live_marketplace" &&
        a.marketplace_status !== "pending_review").length;
      if (notListed) alerts.push(
        `${notListed} live product(s) not submitted to the Whop marketplace ` +
        `— they are reachable by link but will not appear on Discover`);
      const noCover = assets.filter((a: any) =>
        a.product_id && a.cover_status === "pending_manual").length;
      if (noCover) alerts.push(
        `${noCover} live product(s) have no cover image — Whop attachment upload ` +
        `needs an App API key; attach manually in the Whop dashboard`);
      const noLink = assets.filter((a: any) => a.free === true && !a.page_url).length;
      if (noLink) alerts.push(`${noLink} free asset(s) have no page_url`);
      for (const k of Object.keys(byWf)) {
        if (byWf[k].lastConclusion === "failure") alerts.push(`${k}: last run FAILED`);
      }

      // append a daily rollup point (idempotent per UTC day) for the charts
      try {
        const hraw = await env.BOT_STATE.get("history");
        const hist: any[] = hraw ? JSON.parse(hraw) : [];
        const today = new Date().toISOString().slice(0, 10);
        const point = {
          d: today,
          posts: posts.length,
          postsToday,
          assets: assets.length,
          live: assets.filter((a: any) => a.status === "live").length,
          orphaned,
          lag: avgLag,
          runsOk: wr.filter((r: any) => r.conclusion === "success").length,
          runsFail: wr.filter((r: any) => r.conclusion === "failure").length,
        };
        const i = hist.findIndex((x) => x.d === today);
        // KV FREE TIER IS 1,000 WRITES/DAY. The dashboard polls /api/summary
        // every 60s, so writing unconditionally burned ~1,440 writes/day from
        // a single idle tab and hit 90% of the quota. Only write when the
        // rollup actually CHANGED (or the day is new) — that is a handful of
        // writes/day instead of one per poll.
        const changed = i < 0 || JSON.stringify(hist[i]) !== JSON.stringify(point);
        if (i >= 0) hist[i] = point; else hist.push(point);
        while (hist.length > 60) hist.shift();
        if (changed) await env.BOT_STATE.put("history", JSON.stringify(hist));
      } catch { /* charts are best-effort */ }

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

    // ---- maintenance: purge orphaned manifest entries ----
    if (p === "/api/purge-orphans" && request.method === "POST") {
      if (!authed(env, request)) return json({ error: "unauthorized" }, 401);
      try {
        const path = `/repos/${env.GH_OWNER}/${env.GH_REPO}/contents/state/manifest.json`;
        const cur = await gh(env, "GET", path);
        const manifest = JSON.parse(atob(String(cur.content).replace(/\s/g, "")));
        const before = (manifest.assets || []).length;
        const kept = (manifest.assets || []).filter((a: any) => a.status !== "orphaned");
        const removedSlugs = (manifest.assets || [])
          .filter((a: any) => a.status === "orphaned").map((a: any) => a.slug);
        if (!removedSlugs.length) return json({ ok: true, removed: 0, message: "no orphans" });
        const freedTopics = (manifest.assets || [])
          .filter((a: any) => a.status === "orphaned")
          .map((a: any) => a.topic).filter(Boolean);
        manifest.assets = kept;
        // keep posts, but drop ones pointing at removed assets
        manifest.posts = (manifest.posts || []).filter((x: any) => !removedSlugs.includes(x.asset));
        const body = btoa(unescape(encodeURIComponent(JSON.stringify(manifest, null, 2))));
        await gh(env, "PUT", path, {
          message: `chore: purge ${removedSlugs.length} orphaned asset(s) via Command Center`,
          content: body, sha: cur.sha,
        });

        // release the topics back to the pool — they were marked "used" but
        // produced nothing, so without this they'd never be retried.
        let released = 0;
        try {
          const tp = `/repos/${env.GH_OWNER}/${env.GH_REPO}/contents/state/topics_index.json`;
          const tcur = await gh(env, "GET", tp);
          const tidx = JSON.parse(atob(String(tcur.content).replace(/\s/g, "")));
          const beforeN = (tidx.used || []).length;
          tidx.used = (tidx.used || []).filter((t: string) => !freedTopics.includes(t));
          for (const t of freedTopics) delete (tidx.vectors || {})[t];
          released = beforeN - tidx.used.length;
          if (released > 0) {
            await gh(env, "PUT", tp, {
              message: `chore: release ${released} topic(s) from purged orphans`,
              content: btoa(unescape(encodeURIComponent(JSON.stringify(tidx, null, 2)))),
              sha: tcur.sha,
            });
          }
        } catch (e) { /* topic release is best-effort */ }

        return json({ ok: true, removed: removedSlugs.length, slugs: removedSlugs,
                      topicsReleased: released, assetsBefore: before, assetsAfter: kept.length });
      } catch (e) {
        return json({ ok: false, error: String(e) }, 500);
      }
    }

    // ---- settings / config (read + write env knobs stored in KV) ----
    if (p === "/api/config" && request.method === "GET") {
      const raw = await env.BOT_STATE.get("config");
      const cfg = raw ? JSON.parse(raw) : {};
      return json({ ok: true, config: { ...CONFIG_DEFAULTS, ...cfg }, defaults: CONFIG_DEFAULTS });
    }
    if (p === "/api/config" && request.method === "POST") {
      if (!authed(env, request)) return json({ error: "unauthorized" }, 401);
      const incoming = (await request.json()) as Record<string, unknown>;
      const clean: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(incoming)) {
        if (!(k in CONFIG_DEFAULTS)) continue;
        clean[k] = v;
      }
      const raw = await env.BOT_STATE.get("config");
      const merged = { ...(raw ? JSON.parse(raw) : {}), ...clean };
      await env.BOT_STATE.put("config", JSON.stringify(merged));
      return json({ ok: true, config: { ...CONFIG_DEFAULTS, ...merged } });
    }

    // ---- history: append-only daily rollup for charts ----
    if (p === "/api/history" && request.method === "GET") {
      const raw = await env.BOT_STATE.get("history");
      return json({ ok: true, history: raw ? JSON.parse(raw) : [] });
    }

    // ---- set flags ----
    if (p === "/api/set" && request.method === "POST") {
      if (!authed(env, request)) return json({ error: "unauthorized" }, 401);
      const { key, value } = (await request.json()) as { key: string; value: boolean };
      if (!["kill_switch", "dry_run"].includes(key)) return json({ error: "bad key" }, 400);
      await env.BOT_STATE.put(key, value ? "1" : "0");
      return json({ ok: true, key, value: !!value });
    }

    // ---- FAQ experience page (embedded by Whop in an iframe) ----
    // Whop renders our app at experience_path = /experiences/[experienceId].
    // It appends ?productId=... (and other params) when embedding, so we
    // resolve the product from the query first, then fall back to matching
    // the experience id recorded in the manifest, then to the sole product.
    // ---- /api/factories — one view across all factories ----
    // The dashboard previously only knew about Factory 1, so F3 and F4 could
    // fail silently for days. Each factory writes the same shape into its own
    // state dir, so one loop covers them all.
    if (p === "/api/factories" && request.method === "GET") {
      const owner = env.GH_OWNER, repo = env.GH_REPO;
      const readJson = async (fp: string) => {
        const d = await gh(env, "GET",
          `/repos/${owner}/${repo}/contents/${fp}`);
        return JSON.parse(atob(String(d.content).replace(/\s/g, "")));
      };
      const readLines = async (fp: string) => {
        const d = await gh(env, "GET",
          `/repos/${owner}/${repo}/contents/${fp}`);
        return atob(String(d.content).replace(/\s/g, ""))
          .split("\n").filter(Boolean)
          .map((l) => { try { return JSON.parse(l); } catch { return null; } })
          .filter(Boolean);
      };
      const quiet = async <T>(fn: () => Promise<T>, d: T): Promise<T> => {
        try { return await fn(); } catch { return d; }
      };

      const defs = [
        { key: "f1", name: "The Storefront", dir: "state",
          kind: "prompt packs", sells: "Whop", hb: "daily" },
        { key: "f2", name: "The Broker", dir: "factory2/state",
          kind: "affiliate articles", sells: "affiliate", hb: "factory2" },
        { key: "f3", name: "The Commons", dir: "factory3/state",
          kind: "datasets + tools", sells: "zaps", hb: "factory3" },
        { key: "f4", name: "The Utility", dir: "factory4/state",
          kind: "browser tools", sells: "zaps", hb: "factory4" },
      ];

      const out: any[] = [];
      for (const d of defs) {
        const man = await quiet(() => readJson(`${d.dir}/manifest.json`), {} as any);
        const hb = await quiet(() => readJson(`${d.dir}/heartbeat.json`), {} as any);
        const q = await quiet(() => readLines(`${d.dir}/dist_queue.jsonl`), [] as any[]);

        // manifests use different keys per factory
        const items = man.assets || man.articles || man.datasets || [];
        const beat = hb[d.hb] || hb.daily || {};
        const byStatus: Record<string, number> = {};
        for (const r of q) byStatus[r.status] = (byStatus[r.status] || 0) + 1;

        // stale = no heartbeat in 48h. That is the signal that a factory
        // died quietly, which is exactly what happened to F1 for a day.
        let stale: boolean | null = null;
        let ageH: number | null = null;
        if (beat.at) {
          ageH = (Date.now() - Date.parse(beat.at)) / 36e5;
          stale = ageH > 48;
        }

        out.push({
          key: d.key, name: d.name, kind: d.kind, sells: d.sells,
          items: items.length,
          live: items.filter((x: any) =>
            x.status === "live" || x.status === undefined).length,
          lastRun: beat.at || null,
          lastCount: beat.count ?? null,
          ageHours: ageH === null ? null : Math.round(ageH * 10) / 10,
          stale,
          queue: { total: q.length, ...byStatus },
          posted: byStatus["posted"] || 0,
          failed: byStatus["failed"] || 0,
        });
      }

      const alerts: string[] = [];
      for (const f of out) {
        if (f.stale) alerts.push(`${f.name} (${f.key}) has not run in ${f.ageHours}h`);
        if (f.failed > 0) alerts.push(`${f.name}: ${f.failed} failed distribution job(s)`);
        if (f.items === 0 && f.key !== "f4") alerts.push(`${f.name} has produced nothing`);
      }

      return json({
        ok: true,
        generated_at: new Date().toISOString(),
        factories: out,
        totals: {
          items: out.reduce((n, f) => n + f.items, 0),
          posted: out.reduce((n, f) => n + f.posted, 0),
          failed: out.reduce((n, f) => n + f.failed, 0),
        },
        alerts,
      });
    }

    // ---- /custom — lead capture for custom work ----
    // UPSELL_CUSTOM_URL points here. Whop's /leads API rejects every email we
    // send it ("Invalid value for parameter 'email'"), so capture is hosted
    // on the Worker and stored in KV instead.
    if (p === "/custom" && request.method === "GET") {
      const from = url.searchParams.get("from") || "";
      const esc = (t: any) => String(t ?? "").replace(/&/g, "&amp;")
        .replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
      return new Response(`<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Custom Prompt Pack — Built For Your Niche</title>
<meta name="description" content="Request a custom AI prompt pack built around your niche, brand voice and workflow. Tell us what you need and we will scope it.">
<link rel="canonical" href="${url.origin}/custom">
<meta property="og:title" content="Custom Prompt Pack">
<meta property="og:description" content="Built around your niche and brand voice.">
<style>
 :root{color-scheme:dark}
 *{box-sizing:border-box}
 body{margin:0;padding:34px 18px 70px;background:#0f1115;color:#e8eaed;
  font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}
 .w{max-width:620px;margin:0 auto} a{color:#7cc4ff}
 h1{font-size:28px;margin:0 0 8px} .mut{color:#9aa3b2}
 label{display:block;font-size:13px;color:#9aa3b2;margin:16px 0 6px}
 input,textarea{width:100%;background:#0b0d12;color:#e8eaed;border:1px solid #2a2e37;
  border-radius:8px;padding:11px;font:14px inherit}
 button{background:#7cc4ff;color:#06202f;border:0;border-radius:8px;padding:13px 26px;
  font-weight:700;font-size:15px;cursor:pointer;margin-top:18px}
 button:hover{filter:brightness(1.1)}
 .card{background:#161922;border:1px solid #2a2e37;border-radius:10px;padding:16px;margin:18px 0}
 .ok{border-color:#245c3a}
 ul{margin:8px 0 0 18px;padding:0} li{margin:4px 0}
</style></head><body><div class="w">
<h1>Custom prompt pack</h1>
<p class="mut">The free packs are built for everyone. This one gets built for you —
your niche, your brand voice, your actual workflow.</p>
<div class="card">
  <b>What you get</b>
  <ul>
    <li>A pack scoped to your exact use case, not a generic template</li>
    <li>Prompts tested against your real inputs</li>
    <li>Delivered as Markdown, PDF and DOCX</li>
    <li>One revision round included</li>
  </ul>
</div>
<form id="f" onsubmit="return send(event)">
  <label for="email">Email</label>
  <input id="email" type="email" required placeholder="you@company.com">
  <label for="niche">What is your niche or business?</label>
  <input id="niche" required placeholder="e.g. real estate agent in Dubai">
  <label for="need">What should the pack do for you?</label>
  <textarea id="need" rows="4" required placeholder="Describe the workflow you want automated…"></textarea>
  <input id="from" type="hidden" value="${esc(from)}">
  <button type="submit">Request a quote</button>
</form>
<div id="out"></div>
<p class="mut" style="margin-top:26px"><a href="${url.origin}/p">← browse the free packs</a></p>
<script>
async function send(e){
  e.preventDefault();
  const b={email:document.getElementById('email').value,
           niche:document.getElementById('niche').value,
           need:document.getElementById('need').value,
           from:document.getElementById('from').value};
  const out=document.getElementById('out');
  out.innerHTML='<p class="mut">Sending…</p>';
  try{
    const r=await fetch('/api/lead',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});
    if(r.ok){
      document.getElementById('f').style.display='none';
      out.innerHTML='<div class="card ok"><b>Got it.</b><br>'+
        '<span class="mut">You will get a reply with scope and price. '+
        'No spam, no list — this address is only used to answer you.</span></div>';
    } else { out.innerHTML='<p style="color:#e74c3c">Something went wrong. '+
             'Email us directly instead.</p>'; }
  }catch(err){ out.innerHTML='<p style="color:#e74c3c">Network error.</p>'; }
  return false;
}
</script>
</div></body></html>`, {
        headers: { "content-type": "text/html; charset=utf-8",
                   "cache-control": "public, max-age=300" } });
    }

    // Store a captured lead. Public by necessity (it is a public form), so it
    // is rate-limited by KV key and validated server-side.
    if (p === "/api/lead" && request.method === "POST") {
      let b: any = {};
      try { b = await request.json(); } catch { /* handled below */ }
      const email = String(b.email ?? "").trim().slice(0, 200);
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
        return new Response(JSON.stringify({ ok: false, error: "bad email" }),
          { status: 400, headers: { "content-type": "application/json" } });
      }
      const lead = {
        email,
        niche: String(b.niche ?? "").slice(0, 300),
        need: String(b.need ?? "").slice(0, 2000),
        from: String(b.from ?? "").slice(0, 120),
        at: new Date().toISOString(),
      };
      try {
        const raw = await env.BOT_STATE.get("leads");
        const leads: any[] = raw ? JSON.parse(raw) : [];
        if (!leads.some((l) => l.email === email && l.from === lead.from)) {
          leads.unshift(lead);
          while (leads.length > 500) leads.pop();
          await env.BOT_STATE.put("leads", JSON.stringify(leads));
          const hook = env.DISCORD_ALERT_WEBHOOK ?? "";
          if (hook) {
            await fetch(hook, { method: "POST",
              headers: { "content-type": "application/json" },
              body: JSON.stringify({ embeds: [{
                title: "🎯 New custom-work lead",
                description: `**${lead.email}**\n${lead.niche}\n\n${lead.need.slice(0, 400)}`
                  + (lead.from ? `\n\n_from: ${lead.from}_` : ""),
                color: 0x7cc4ff }] }) }).catch(() => {});
          }
        }
      } catch { /* never fail the form on storage problems */ }
      return json({ ok: true });
    }

    if (p === "/api/leads" && request.method === "GET") {
      if (!authed(env, request)) {
        return new Response("unauthorized", { status: 401 });
      }
      const raw = await env.BOT_STATE.get("leads");
      const leads: any[] = raw ? JSON.parse(raw) : [];
      return json({ ok: true, count: leads.length, leads: leads.slice(0, 50) });
    }

    // ---- Factory 4: free browser tools ----
    // Dataset-backed, bring-your-own-key, and carrying the canonical +
    // JSON-LD + og tags that comparable tool sites omit.
    if (p === "/tools" || p === "/tools/") {
      return new Response(renderIndex(url.origin, env.LIGHTNING_ADDRESS ?? ""), {
        headers: { "content-type": "text/html; charset=utf-8",
                   "cache-control": "public, max-age=600" } });
    }
    if (p.startsWith("/tools/")) {
      const t = toolBySlug(decodeURIComponent(p.slice(7).replace(/\/$/, "")));
      if (t) {
        return new Response(
          renderTool(t, url.origin, env.LIGHTNING_ADDRESS ?? ""), {
            headers: { "content-type": "text/html; charset=utf-8",
                       "cache-control": "public, max-age=600",
                       "x-tool": t.slug } });
      }
      return new Response("Tool not found", { status: 404 });
    }

    // ---- /p/:slug — thin canonical page per pack ----
    // NOT in the buy path: nobody is routed through here. Its whole job is to
    // be a self-canonicalising, indexable target that syndicated copies
    // (dev.to, Hashnode, Webflow) point back at, with the CTA going straight
    // to Whop checkout so no friction is added for buyers.
    //
    // Why this exists: Whop product pages declare canonical = the STORE ROOT,
    // not themselves, so they tell Google not to index the product page.
    if ((p.startsWith("/p/") || p === "/p" || p === "/sitemap.xml" || p === "/robots.txt"
         || p === "/rss.xml" || p === "/feed.xml"
         || (env.INDEXNOW_KEY && p === `/${env.INDEXNOW_KEY}.txt`))
        && request.method === "GET") {
      let assets: any[] = [];
      try {
        const d = await gh(env, "GET",
          `/repos/${env.GH_OWNER}/${env.GH_REPO}/contents/state/manifest.json`);
        assets = (JSON.parse(atob(String(d.content).replace(/\s/g, ""))).assets) || [];
      } catch { /* fall through to empty */ }
      const live = assets.filter((a: any) => a.product_id && a.status === "live");
      const origin = url.origin;

      // IndexNow key file — the protocol requires <host>/<key>.txt to echo
      // the key, proving we control the domain.
      if (p === `/${env.INDEXNOW_KEY ?? "__none__"}.txt`) {
        return new Response(env.INDEXNOW_KEY ?? "", {
          headers: { "content-type": "text/plain; charset=utf-8" } });
      }

      // RSS — a feed is a passive syndication multiplier: dev.to, Hashnode,
      // Medium and every reader can auto-import from it.
      if (p === "/rss.xml" || p === "/feed.xml") {
        const esc = (t: any) => String(t ?? "")
          .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        const items = live.map((a: any) => {
          const link = `${origin}/p/${a.slug}`;
          const img = (a.release_images || a.gallery_images || [])[0] || "";
          return `<item>
<title>${esc(a.title)}</title>
<link>${link}</link>
<guid isPermaLink="true">${link}</guid>
<description>${esc(a.subtitle || a.title)}</description>
${a.created ? `<pubDate>${new Date(a.created).toUTCString()}</pubDate>` : ""}
${img ? `<enclosure url="${esc(img)}" type="image/jpeg"/>` : ""}
</item>`;
        }).join("\n");
        return new Response(
          `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>Asset Bot — prompt packs</title>
<link>${origin}/p</link>
<description>New AI prompt packs, as they ship.</description>
<language>en</language>
${items}
</channel></rss>`,
          { headers: { "content-type": "application/rss+xml; charset=utf-8",
                       "cache-control": "public, max-age=300" } });
      }

      if (p === "/robots.txt") {
        return new Response(
          `User-agent: *\nAllow: /\nSitemap: ${origin}/sitemap.xml\n`,
          { headers: { "content-type": "text/plain; charset=utf-8" } });
      }

      if (p === "/sitemap.xml") {
        const urls = [`${origin}/p`, ...live.map((a: any) => `${origin}/p/${a.slug}`),
                      `${origin}/tools`,
                      ...TOOLS.map((t) => `${origin}/tools/${t.slug}`),
                      `${origin}/custom`];
        return new Response(
          `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n` +
          urls.map((u) => `<url><loc>${u}</loc></url>`).join("\n") +
          `\n</urlset>`,
          { headers: { "content-type": "application/xml; charset=utf-8" } });
      }

      const esc = (t: any) => String(t ?? "")
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
      const shell = (title: string, head: string, body: string) =>
        `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(title)}</title>${head}
<style>
  :root{color-scheme:dark light}
  *{box-sizing:border-box}
  body{margin:0;padding:32px 20px;background:#0f1115;color:#e8eaed;
       font:16px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}
  .w{max-width:720px;margin:0 auto}
  a{color:#7cc4ff}
  h1{font-size:30px;line-height:1.2;margin:0 0 8px}
  .sub{opacity:.75;font-size:18px;margin:0 0 24px}
  img.hero{width:100%;border-radius:12px;margin:0 0 24px}
  .cta{display:inline-block;background:#ff6b35;color:#fff;font-weight:700;
       padding:14px 28px;border-radius:10px;text-decoration:none;margin:8px 0 28px}
  details{border:1px solid #2a2e37;border-radius:10px;padding:14px 16px;margin-bottom:10px;background:#161922}
  summary{cursor:pointer;font-weight:600}
  .card{display:block;border:1px solid #2a2e37;border-radius:12px;padding:16px;
        margin-bottom:12px;text-decoration:none;color:inherit;background:#161922}
  footer{margin-top:40px;opacity:.5;font-size:13px}
</style></head><body><div class="w">${body}
<footer>Published by The Algorithmic Daemon Concern.</footer></div></body></html>`;

      // index
      if (p === "/p" || p === "/p/") {
        const body = `<h1>Prompt packs</h1><p class="sub">Every pack we've shipped.</p>` +
          (live.length ? live.map((a: any) =>
            `<a class="card" href="${origin}/p/${esc(a.slug)}"><b>${esc(a.title)}</b><br>
             <span style="opacity:.7">${esc(a.subtitle || "")}</span></a>`).join("")
            : "<p>Nothing published yet.</p>");
        return new Response(shell("Prompt packs", `<link rel="canonical" href="${origin}/p">`, body),
          { headers: { "content-type": "text/html; charset=utf-8",
                       "cache-control": "public, max-age=300" } });
      }

      const slug = decodeURIComponent(p.slice(3));
      const a = live.find((x: any) => x.slug === slug);
      if (!a) {
        return new Response(shell("Not found", "", "<h1>Not found</h1>"),
          { status: 404, headers: { "content-type": "text/html; charset=utf-8" } });
      }

      const self = `${origin}/p/${a.slug}`;
      const buy = a.page_url || "";
      const img = (a.gallery_images || [])[0] || "";
      const faq = a.faq || [];
      const price = Number(a.price || 0);

      // Product + FAQPage JSON-LD. offers.url points at Whop checkout.
      const ld: any = {
        "@context": "https://schema.org", "@type": "Product",
        name: a.title, description: a.subtitle || a.title,
        ...(img ? { image: [img] } : {}),
        brand: { "@type": "Brand", name: "The Algorithmic Daemon Concern" },
        offers: { "@type": "Offer", price: price.toFixed(2), priceCurrency: "USD",
                  availability: "https://schema.org/InStock",
                  ...(buy ? { url: buy } : {}) },
      };
      const ldFaq = faq.length ? {
        "@context": "https://schema.org", "@type": "FAQPage",
        mainEntity: faq.map((f: any) => ({
          "@type": "Question", name: f.question,
          acceptedAnswer: { "@type": "Answer", text: f.answer } })),
      } : null;

      const head =
        `<link rel="canonical" href="${self}">` +
        `<meta name="description" content="${esc(a.subtitle || a.title)}">` +
        `<meta property="og:type" content="product">` +
        `<meta property="og:title" content="${esc(a.title)}">` +
        `<meta property="og:description" content="${esc(a.subtitle || "")}">` +
        `<meta property="og:url" content="${self}">` +
        (img ? `<meta property="og:image" content="${esc(img)}">` : "") +
        `<meta name="twitter:card" content="summary_large_image">` +
        `<script type="application/ld+json">${JSON.stringify(ld)}</script>` +
        (ldFaq ? `<script type="application/ld+json">${JSON.stringify(ldFaq)}</script>` : "");

      const body =
        `<h1>${esc(a.title)}</h1>` +
        `<p class="sub">${esc(a.subtitle || "")}</p>` +
        (img ? `<img class="hero" src="${esc(img)}" alt="${esc(a.title)}">` : "") +
        (buy ? `<a class="cta" href="${esc(buy)}" rel="nofollow">
                 ${price > 0 ? `Get it — $${price.toFixed(2)}` : "Get it free"}</a>` : "") +
        // Lightning zap CTA — the only payment rail that works under
        // sanctions. Shown whenever LIGHTNING_ADDRESS is configured.
        (env.LIGHTNING_ADDRESS && env.LIGHTNING_ADDRESS.includes("@") ? `<p style="margin:4px 0 24px">
           <span style="opacity:.7">Found this useful? Zap it:</span>
           <code style="background:#161922;border:1px solid #2a2e37;border-radius:6px;
                        padding:4px 8px;margin-left:6px">${esc(env.LIGHTNING_ADDRESS)}</code>
         </p>` : "") +
        (faq.length ? `<h2>FAQ</h2>` + faq.map((f: any) =>
          `<details><summary>${esc(f.question)}</summary>
           <div style="margin-top:10px;opacity:.85">${esc(f.answer)}</div></details>`).join("") : "");

      return new Response(shell(`${a.title} — prompt pack`, head, body), {
        headers: { "content-type": "text/html; charset=utf-8",
                   "cache-control": "public, max-age=300",
                   "x-pack": a.slug },
      });
    }

    if (p.startsWith("/experiences/") && request.method === "GET") {
      const expId = decodeURIComponent(p.slice("/experiences/".length));
      const qs = url.searchParams;
      const wanted = qs.get("productId") || qs.get("product_id") ||
                     qs.get("accessPassId") || qs.get("slug") || "";

      let assets: any[] = [];
      try {
        const d = await gh(env, "GET",
          `/repos/${env.GH_OWNER}/${env.GH_REPO}/contents/state/manifest.json`);
        assets = (JSON.parse(atob(String(d.content).replace(/\s/g, ""))).assets) || [];
      } catch { /* render the empty state below */ }

      const live = assets.filter((a: any) => a.product_id && (a.faq || []).length);
      let asset =
        live.find((a: any) => a.product_id === wanted || a.slug === wanted) ||
        live.find((a: any) => a.faq_experience_id === expId) ||
        (live.length === 1 ? live[0] : null);

      const esc = (t: string) => String(t ?? "")
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

      let inner: string;
      if (asset) {
        inner = `<h1>${esc(asset.title)}</h1>
    <p class="sub">Frequently asked questions</p>
    ${(asset.faq || []).map((f: any, i: number) => `
    <details${i === 0 ? " open" : ""}>
      <summary>${esc(f.question)}</summary>
      <div class="a">${esc(f.answer)}</div>
    </details>`).join("")}`;
      } else if (live.length > 1) {
        // Embedded without a product hint and several products qualify —
        // show them all rather than guessing wrong.
        inner = `<h1>Frequently asked questions</h1>` + live.map((a: any) => `
    <h2>${esc(a.title)}</h2>
    ${(a.faq || []).map((f: any) => `
    <details><summary>${esc(f.question)}</summary>
      <div class="a">${esc(f.answer)}</div></details>`).join("")}`).join("");
      } else {
        inner = `<h1>Frequently asked questions</h1>
    <p class="sub">No FAQ has been published for this product yet.</p>`;
      }

      const html = `<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FAQ</title><style>
  :root{color-scheme:light dark}
  *{box-sizing:border-box}
  body{margin:0;padding:24px;font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif;
       background:transparent;color:#e8eaed}
  @media (prefers-color-scheme: light){body{color:#1a1a1a}}
  .wrap{max-width:720px;margin:0 auto}
  h1{font-size:22px;margin:0 0 4px}
  h2{font-size:16px;margin:28px 0 8px;opacity:.85}
  .sub{margin:0 0 20px;opacity:.6;font-size:14px}
  details{border:1px solid rgba(128,128,128,.28);border-radius:10px;
          padding:14px 16px;margin-bottom:10px;background:rgba(128,128,128,.06)}
  details[open]{background:rgba(128,128,128,.10)}
  summary{cursor:pointer;font-weight:600;list-style:none;display:flex;
          justify-content:space-between;align-items:center;gap:12px}
  summary::-webkit-details-marker{display:none}
  summary::after{content:"+";font-size:18px;opacity:.5;flex:0 0 auto}
  details[open] summary::after{content:"\u2212"}
  .a{margin-top:10px;opacity:.85}
</style></head><body><div class="wrap">
    ${inner}
</div></body></html>`;

      return new Response(html, {
        headers: {
          "content-type": "text/html; charset=utf-8",
          // Must be embeddable by Whop. Explicitly allow framing (no
          // X-Frame-Options) and keep it fresh-ish at the edge.
          "content-security-policy": "frame-ancestors https://whop.com https://*.whop.com",
          "cache-control": "public, max-age=120",
          "x-faq-product": asset?.product_id ?? "none",
        },
      });
    }

    // ---- cron claim: GitHub's fallback schedule checks in here first ----
    // Returns {claimed:false} when the Worker already dispatched this slot,
    // so the dead-man's-switch run exits instead of duplicating the work.
    // ---- Ko-fi webhook (INBOUND: payment notifications, not distribution) ----
    // Ko-fi has no publishing API — its API is webhooks only. This is our
    // first real revenue signal: until now nothing in the pipeline could tell
    // us a stranger had actually paid.
    //
    // Contract (per Ko-fi docs): application/x-www-form-urlencoded, with a
    // `data` field holding a JSON STRING. Must return 200 or Ko-fi retries the
    // same message_id. Verification token is plain text — compare in constant
    // time and never log it.
    if (p === "/api/kofi" && request.method === "POST") {
      let payload: any = {};
      try {
        const form = new URLSearchParams(await request.text());
        payload = JSON.parse(form.get("data") ?? "{}");
      } catch {
        // Always 200 — a parse failure must not make Ko-fi retry forever.
        return json({ ok: false, error: "bad payload" });
      }

      const expected = env.KOFI_VERIFICATION_TOKEN ?? "";
      const got = String(payload.verification_token ?? "");
      // constant-time-ish compare
      let same = expected.length === got.length && expected.length > 0;
      for (let i = 0; i < Math.min(expected.length, got.length); i++) {
        if (expected[i] !== got[i]) same = false;
      }
      if (!same) {
        return new Response(JSON.stringify({ ok: false, error: "bad token" }),
          { status: 401, headers: { "content-type": "application/json" } });
      }

      const id = String(payload.message_id ?? "");
      const sale = {
        id,
        at: String(payload.timestamp ?? new Date().toISOString()),
        type: String(payload.type ?? "Tip"),          // Tip|Subscription|Commission|Shop Order
        amount: Number(payload.amount ?? 0),
        currency: String(payload.currency ?? "USD"),
        from: String(payload.from_name ?? "Someone"),
        email: String(payload.email ?? ""),
        // Ko-fi: hide the message publicly when is_public is false
        message: payload.is_public ? String(payload.message ?? "") : "",
        isPublic: !!payload.is_public,
        isSub: !!payload.is_subscription_payment,
        isFirstSub: !!payload.is_first_subscription_payment,
        tier: String(payload.tier_name ?? ""),
        items: (payload.shop_items ?? []).map((i: any) =>
          String(i.direct_link_code ?? "")),
      };

      try {
        const raw = await env.BOT_STATE.get("sales");
        const sales: any[] = raw ? JSON.parse(raw) : [];
        // idempotent: Ko-fi retries the same message_id until it sees a 200
        if (!sales.some((x) => x.id === id && id)) {
          sales.unshift(sale);
          while (sales.length > 200) sales.pop();
          await env.BOT_STATE.put("sales", JSON.stringify(sales));

          // Announce it — the first paid sale is the signal that matters most.
          const hook = env.DISCORD_ALERT_WEBHOOK ?? "";
          if (hook) {
            const money = `${sale.currency} ${sale.amount.toFixed(2)}`;
            await fetch(hook, {
              method: "POST",
              headers: { "content-type": "application/json" },
              body: JSON.stringify({
                embeds: [{
                  title: `💰 ${sale.type} — ${money}`,
                  description: `from **${sale.from}**` +
                    (sale.tier ? `\nTier: ${sale.tier}` : "") +
                    (sale.message ? `\n> ${sale.message}` : ""),
                  color: 0x2ecc71,
                }],
              }),
            }).catch(() => {});
          }
        }
      } catch { /* never fail the webhook on storage problems */ }

      return json({ ok: true });
    }

    if (p === "/api/sales" && request.method === "GET") {
      const raw = await env.BOT_STATE.get("sales");
      const sales: any[] = raw ? JSON.parse(raw) : [];
      const total = sales.reduce((n, s) => n + (s.amount || 0), 0);
      const today = new Date().toISOString().slice(0, 10);
      return json({
        ok: true,
        count: sales.length,
        total: Number(total.toFixed(2)),
        today: Number(sales.filter((s) => String(s.at).slice(0, 10) === today)
          .reduce((n, s) => n + (s.amount || 0), 0).toFixed(2)),
        sales: sales.slice(0, 25),
      });
    }

    if (p === "/api/cronclaim" && request.method === "POST") {
      const { workflow } = (await request.json()) as { workflow: string };
      if (!workflow) return json({ error: "workflow required" }, 400);
      const now = new Date();
      // Fallbacks run 1h+ after the Worker slot; check this hour and the last two.
      for (let back = 0; back <= 2; back++) {
        const d = new Date(now.getTime() - back * 3600_000);
        const hit = await env.BOT_STATE.get(
          `cronlock:${workflow}:${d.toISOString().slice(0, 13)}`);
        if (hit) return json({ ok: true, claimed: false, reason: "worker-cron-ran" });
      }
      const slot = `${workflow}:${now.toISOString().slice(0, 13)}`;
      await env.BOT_STATE.put(`cronlock:${slot}`, String(Date.now()),
                              { expirationTtl: 10800 });
      return json({ ok: true, claimed: true, reason: "worker-cron-missed" });
    }

    // ---- cron delivery log (Worker cron -> GitHub dispatch) ----
    if (p === "/api/cronlog" && request.method === "GET") {
      const log = JSON.parse((await env.BOT_STATE.get("cronlog")) ?? "[]");
      return json({ ok: true, source: "cloudflare-cron", count: log.length, log });
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

  /**
   * Cloudflare Cron Triggers -> GitHub workflow_dispatch.
   *
   * GitHub's `schedule:` events are best-effort and were running an average of
   * 87 minutes late (samples: 69/89/138/51), sometimes being dropped outright.
   * Cloudflare cron fires on time, so timing now lives here and GitHub only
   * ever receives an explicit, immediate dispatch.
   *
   * The `schedule:` blocks stay in the workflows as a dead-man's switch: if the
   * Worker stops firing, GitHub still eventually runs the job. To keep that
   * from double-running, each dispatch takes a KV lock keyed to the run slot.
   */
  async scheduled(event: ScheduledController, env: Env, ctx: ExecutionContext) {
    const cron = event.cron;
    const workflow = cron.startsWith("20 6") ? "daily-cycle" : "content-posting";
    const file = workflow === "daily-cycle" ? "daily-cycle.yml" : "content-posting.yml";

    // Lock slot = workflow + UTC hour, so the GitHub schedule fallback (which
    // fires later in the same hour) sees the lock and skips.
    const now = new Date();
    const slot = `${workflow}:${now.toISOString().slice(0, 13)}`;
    const already = await env.BOT_STATE.get(`cronlock:${slot}`);
    if (already) return;
    await env.BOT_STATE.put(`cronlock:${slot}`, String(Date.now()), {
      expirationTtl: 10800,
    });

    // Respect the kill switch, same as a manual dispatch would.
    if ((await env.BOT_STATE.get("kill")) === "1") return;

    ctx.waitUntil((async () => {
      try {
        await gh(env, "POST",
                 `/repos/${env.GH_OWNER}/${env.GH_REPO}/actions/workflows/${file}/dispatches`,
                 { ref: "main", inputs: {} });
        const log = JSON.parse((await env.BOT_STATE.get("cronlog")) ?? "[]");
        log.unshift({ at: new Date().toISOString(), cron, workflow, ok: true });
        await env.BOT_STATE.put("cronlog", JSON.stringify(log.slice(0, 50)));
      } catch (e) {
        const log = JSON.parse((await env.BOT_STATE.get("cronlog")) ?? "[]");
        log.unshift({ at: new Date().toISOString(), cron, workflow,
                      ok: false, error: String(e) });
        await env.BOT_STATE.put("cronlog", JSON.stringify(log.slice(0, 50)));
      }
    })());
  },
};
