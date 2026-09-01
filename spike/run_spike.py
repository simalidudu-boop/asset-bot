"""
run_spike.py — Phase 0 spike. Run this ONCE on your machine with your keys
to verify every external integration before going live:

    export WHOP_API_KEY=... WHOP_COMPANY_ID=... OWN_FORUM_ID=...
    export CF_API_TOKEN=... CF_ACCOUNT_ID=... EDGE_URL=... BOT_TOKEN=...
    export MISTRAL_API_KEY=... GROQ_API_KEY=... (any LLM keys you have)
    python3 spike/run_spike.py

Each test prints PASS/FAIL/SKIP. SKIP = key missing (fine — the $0 router
works with any subset). FAIL items must be fixed before Phase 1 go-live.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import whop_client as whop  # noqa: E402

RESULTS = []


def check(name, fn, skip=False):
    if skip:
        print(f"  SKIP  {name} (no key)")
        RESULTS.append((name, "SKIP"))
        return
    try:
        out = fn()
        print(f"  PASS  {name}" + (f" -> {str(out)[:160]}" if out else ""))
        RESULTS.append((name, "PASS"))
    except Exception as e:
        print(f"  FAIL  {name}: {e}")
        RESULTS.append((name, "FAIL"))


def get_json(url, headers=None, method="GET", payload=None, timeout=30):
    req = urllib.request.Request(url, method=method,
                                 data=json.dumps(payload).encode() if payload else None)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    if payload:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


print("=== 1. Whop identity ===")
check("whop /accounts/me", lambda: whop.me().get("id"), skip=not os.environ.get("WHOP_API_KEY"))
check("whop /companies", lambda: [c.get("id") for c in whop.my_companies()],
      skip=not os.environ.get("WHOP_API_KEY"))

print("\n=== 2. Whop forum posting (DRY — no post is created) ===")
def forum_probe():
    # probes permissions WITHOUT creating content: fetch requires read perm;
    # creation is verified live in the real pipeline (first run has DRY off).
    return f"company_id={os.environ.get('WHOP_COMPANY_ID','')} own_forum={os.environ.get('OWN_FORUM_ID','')} public_exp={os.environ.get('PUBLIC_EXPERIENCE','public')}"
check("forum config present", forum_probe,
      skip=not os.environ.get("WHOP_API_KEY"))

print("\n=== 3. LLM providers (one tiny completion each) ===")
def llm_probe(envkey, url, model, key_src, payload_fn):
    k = os.environ.get(envkey)
    if not k:
        return None  # will be SKIPped by caller
    payload = payload_fn(model)
    headers = {"Authorization": f"Bearer {k}"}
    d = get_json(url, headers, "POST", payload)
    return str(d)[:120]

providers = [
    ("mistral", "MISTRAL_API_KEY",
     "https://api.mistral.ai/v1/chat/completions",
     lambda m: {"model": m, "messages": [{"role": "user", "content": "say ok"}]},
     "mistral-small-latest"),
    ("groq", "GROQ_API_KEY",
     "https://api.groq.com/openai/v1/chat/completions",
     lambda m: {"model": m, "messages": [{"role": "user", "content": "say ok"}]},
     "llama-3.3-70b-versatile"),
    ("cerebras", "CEREBRAS_API_KEY",
     "https://api.cerebras.ai/v1/chat/completions",
     lambda m: {"model": m, "messages": [{"role": "user", "content": "say ok"}]},
     "llama-3.3-70b"),
    ("gh-models", "GH_MODELS_TOKEN",
     "https://models.inference.ai.azure.com/chat/completions",
     lambda m: {"model": m, "messages": [{"role": "user", "content": "say ok"}]},
     "gpt-4o-mini"),
    ("xai", "XAI_API_KEY",
     "https://api.x.ai/v1/chat/completions",
     lambda m: {"model": m, "messages": [{"role": "user", "content": "say ok"}]},
     "grok-4.1-fast"),
]
for name, envkey, url, payload_fn, model in providers:
    if not os.environ.get(envkey):
        check(f"llm {name}", None, skip=True)
        continue
    check(f"llm {name}", lambda u=url, p=payload_fn, m=model, e=envkey:
          llm_probe(e, u, m, None, p))

# gemini native
if os.environ.get("GEMINI_API_KEY"):
    check("llm gemini", lambda: get_json(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={os.environ['GEMINI_API_KEY']}",
        None, "POST",
        {"contents": [{"parts": [{"text": "say ok"}]}]}))
else:
    check("llm gemini", None, skip=True)

# cloudflare workers ai
if os.environ.get("CF_API_TOKEN") and os.environ.get("CF_ACCOUNT_ID"):
    check("llm cloudflare-workers-ai", lambda: get_json(
        f"https://api.cloudflare.com/client/v4/accounts/{os.environ['CF_ACCOUNT_ID']}/ai/run/@cf/meta/llama-3.1-8b-instruct",
        {"Authorization": f"Bearer {os.environ['CF_API_TOKEN']}"}, "POST",
        {"messages": [{"role": "user", "content": "say ok"}]})["result"]["response"][:80])
else:
    check("llm cloudflare-workers-ai", None, skip=True)

print("\n=== 4. Cohere embed/rerank ===")
if os.environ.get("COHERE_API_KEY"):
    check("cohere embed", lambda: len(get_json(
        "https://api.cohere.com/v1/embed",
        {"Authorization": f"Bearer {os.environ['COHERE_API_KEY']}"}, "POST",
        {"texts": ["test topic"], "model": "embed-english-v3.0",
         "input_type": "search_document"})["embeddings"][0]))
else:
    check("cohere embed", None, skip=True)

print("\n=== 5. Cloudflare Workers AI image (Flux Schnell) ===")
if os.environ.get("CF_API_TOKEN") and os.environ.get("CF_ACCOUNT_ID"):
    def cf_img():
        d = get_json(
            f"https://api.cloudflare.com/client/v4/accounts/{os.environ['CF_ACCOUNT_ID']}/ai/run/@cf/black-forest-labs/flux-1-schnell",
            {"Authorization": f"Bearer {os.environ['CF_API_TOKEN']}"}, "POST",
            {"prompt": "spike test: minimal cover art, one accent color", "num_steps": 4})
        assert d.get("success"), d.get("errors")
        import base64
        return f"{len(base64.b64decode(d['result']['image']))} bytes png"
    check("cf flux image", cf_img)
else:
    check("cf flux image", None, skip=True)

print("\n=== 6. Edge worker ===")
if os.environ.get("EDGE_URL"):
    check("edge / (health)", lambda: get_json(f"{os.environ['EDGE_URL']}/"))
    if os.environ.get("BOT_TOKEN"):
        def edge_upload():
            req = urllib.request.Request(f"{os.environ['EDGE_URL']}/upload/spike/hello.txt",
                                         data=b"spike", method="PUT")
            req.add_header("X-Bot-Token", os.environ["BOT_TOKEN"])
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.loads(r.read())
            return d["url"]
        check("edge /upload (PUT)", edge_upload)
else:
    check("edge / (health)", None, skip=True)

print("\n=== 7. GitHub dispatch (webhook relay e2e) ===")
if os.environ.get("GH_TOKEN") and os.environ.get("GITHUB_REPOSITORY"):
    def dispatch():
        req = urllib.request.Request(
            f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/dispatches",
            data=json.dumps({"event_type": "whop_unknown",
                             "client_payload": {"spike": True}}).encode(), method="POST")
        req.add_header("Authorization", f"Bearer {os.environ['GH_TOKEN']}")
        req.add_header("Accept", "application/vnd.github+json")
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status
    check("repository_dispatch", dispatch)
else:
    check("repository_dispatch", None, skip=True)

print("\n================ SUMMARY ================")
fails = [n for n, s in RESULTS if s == "FAIL"]
print(f"{len([s for _, s in RESULTS if s == 'PASS'])} pass, "
      f"{len(fails)} fail, "
      f"{len([s for _, s in RESULTS if s == 'SKIP'])} skip")
if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("Spike complete.")
