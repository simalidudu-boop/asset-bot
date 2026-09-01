"""
textgen.py — $0 multi-provider LLM router.

Normalizes free-tier providers behind one chat() call, tracks per-provider
daily budgets in state/ (persisted across GitHub Actions runs via the
workflow cache), and cascades on auth/rate-limit/server failures.

All providers are OpenAI-compatible except where noted. Every API key is
OPTIONAL: the cascade simply skips providers whose key is missing.

Provider priority (quality-critical): mistral > gemini > groq > cerebras
                                  > gh-models > cloudflare > xai
Provider priority (bulk/cheap):   groq > cerebras > gh-models > gemini > cloudflare
"""
import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path

STATE_DIR = Path(__file__).resolve().parent.parent / "state"
STATE_DIR.mkdir(exist_ok=True)

PROVIDERS = {
    "mistral": {
        "url": "https://api.mistral.ai/v1/chat/completions",
        "env_key": "MISTRAL_API_KEY",
        "model": "mistral-small-latest",
        "quality": "mistral-large-latest",
        "daily_budget": 40,          # experiment tier 2 RPM -> keep low & steady
        "extra_headers": {},
    },
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "env_key": "GROQ_API_KEY",
        "model": "qwen/qwen3.8-27b",
        "quality": "qwen/qwen3.8-27b",
        "daily_budget": 400,
        "extra_headers": {},
    },
    # NOTE: Cerebras removed in 2026 — free tier now requires payment.
    # GitHub Models retired by GitHub in 2026 (scheduled retirement brownout).
    "gemini": {
        # Gemini native (not OpenAI-compatible) -> handled in _call_provider
        "url": None,
        "env_key": "GEMINI_API_KEY",
        "model": "gemini-2.5-flash",
        "quality": "gemini-2.5-flash",
        "daily_budget": 100,
        "extra_headers": {},
    },
    "cloudflare": {
        "url": None,  # built per-call from CF_ACCOUNT_ID
        "env_key": "CF_API_TOKEN",
        "model": "@cf/meta/llama-3.1-8b-instruct",
        "quality": "@cf/meta/llama-3.1-8b-instruct",
        "daily_budget": 100,
        "extra_headers": {},
    },
    "xai": {
        "url": "https://api.x.ai/v1/chat/completions",
        "env_key": "XAI_API_KEY",
        "model": "grok-4.1-fast",
        "quality": "grok-4.1-fast",
        "daily_budget": 10,           # signup credits only -> reserve for premium passes
        "extra_headers": {},
    },
}

QUALITY_ORDER = ["mistral", "gemini", "xai", "groq", "cloudflare"]
BULK_ORDER = ["groq", "gemini", "cloudflare", "mistral"]


def _budget_path(name: str) -> Path:
    return STATE_DIR / f"llm_{name}.json"


def _budget_used(name: str) -> int:
    p = _budget_path(name)
    if not p.exists():
        return 0
    try:
        b = json.loads(p.read_text())
    except Exception:
        return 0
    if b.get("date") != time.strftime("%Y-%m-%d"):
        return 0
    return b.get("calls", 0)


def _budget_bump(name: str):
    p = _budget_path(name)
    used = _budget_used(name)
    p.write_text(json.dumps({"date": time.strftime("%Y-%m-%d"), "calls": used + 1}))


def _post_json(url: str, payload: dict, headers: dict, timeout: int = 120):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0 (asset-bot)", **headers},
        method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _call_openai_compatible(name: str, messages: list, model: str, max_tokens: int,
                            temperature: float, json_mode: bool):
    prov = PROVIDERS[name]
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {os.environ[prov['env_key']]}"}
    data = _post_json(prov["url"], payload, headers)
    return data["choices"][0]["message"]["content"]


def _call_gemini(messages: list, max_tokens: int, temperature: float, json_mode: bool):
    # map OpenAI roles -> Gemini contents
    contents, system = [], None
    for m in messages:
        if m["role"] == "system":
            system = m["content"]
        else:
            contents.append({"role": "model" if m["role"] == "assistant" else "user",
                             "parts": [{"text": m["content"]}]})
    body = {
        "contents": contents,
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": temperature,
            "responseMimeType": "application/json" if json_mode else "text/plain",
        },
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           f"{PROVIDERS['gemini']['model']}:generateContent?key={os.environ['GEMINI_API_KEY']}")
    data = _post_json(url, body, {})
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _call_cloudflare(messages: list, max_tokens: int, temperature: float, json_mode: bool):
    account = os.environ["CF_ACCOUNT_ID"]
    url = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/@cf/meta/llama-3.1-8b-instruct"
    payload = {
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {os.environ['CF_API_TOKEN']}"}
    data = _post_json(url, payload, headers)
    if not data.get("success"):
        raise RuntimeError(f"cloudflare: {data.get('errors')}")
    return data["result"]["response"]


def _call_provider(name: str, messages: list, max_tokens: int, temperature: float,
                   json_mode: bool, quality: bool):
    prov = PROVIDERS[name]
    if not os.environ.get(prov["env_key"]):
        raise RuntimeError(f"{name}: no key")
    if name == "cloudflare" and not os.environ.get("CF_ACCOUNT_ID"):
        raise RuntimeError("cloudflare: no CF_ACCOUNT_ID")
    if _budget_used(name) >= prov["daily_budget"]:
        raise RuntimeError(f"{name}: daily budget exhausted")
    model = prov["quality"] if quality else prov["model"]
    if name == "gemini":
        out = _call_gemini(messages, max_tokens, temperature, json_mode)
    elif name == "cloudflare":
        out = _call_cloudflare(messages, max_tokens, temperature, json_mode)
    else:
        out = _call_openai_compatible(name, messages, model, max_tokens, temperature, json_mode)
    _budget_bump(name)
    return out


def chat(messages: list, max_tokens: int = 2000, temperature: float = 0.7,
         json_mode: bool = False, quality: bool = False,
         order: list | None = None, min_successes: int = 1) -> list[str]:
    """Try providers in order; return up to `min_successes` completions.

    The first success is the primary result; extra successes (when
    min_successes > 1) are variant candidates for A/B selection.
    """
    results, errors = [], []
    order = order or (QUALITY_ORDER if quality else BULK_ORDER)
    for name in order:
        if len(results) >= min_successes:
            break
        try:
            results.append(_call_provider(name, messages, max_tokens, temperature, json_mode, quality))
            if len(results) >= min_successes:
                break
        except urllib.error.HTTPError as e:
            errors.append(f"{name}: HTTP {e.code}")
            time.sleep(2)
        except Exception as e:
            errors.append(f"{name}: {e}")
            time.sleep(1)
    if not results:
        raise RuntimeError("all providers failed: " + " | ".join(errors))
    return results


def get_json(messages: list, max_tokens: int = 3000, quality: bool = True):
    """chat() with JSON mode + a repair pass on parse failure."""
    for attempt in range(2):
        try:
            text = chat(messages, max_tokens=max_tokens, json_mode=True, quality=quality)[0]
            return json.loads(_strip_json_fence(text))
        except (json.JSONDecodeError, RuntimeError) as e:
            if attempt == 0 and isinstance(e, json.JSONDecodeError):
                messages.append({"role": "user",
                                 "content": "Your last response was not valid JSON. Return ONLY valid JSON."})
                continue
            raise
    raise RuntimeError("json extraction failed")


def _strip_json_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    return text
