# Resilience, fallbacks and alerting

Built 2026-09-04 after the factory produced **0/3 assets while reporting
success** — the engine had no alerting at all, so a full-day outage was
invisible.

## `engine/resilience.py`

Four primitives. None of them may ever raise into the caller: a broken
alerting system must not break the factory.

| Primitive | Purpose |
|---|---|
| `alert(title, detail, level, dedupe)` | Critical errors → Discord. Deduplicated per run, links back to the GitHub run log. |
| `retry(fn, attempts, label)` | Exponential backoff **+ jitter**, transient faults only. |
| `first_ok([(name, fn)…])` | Provider cascade; returns the first success. Alerts only when **all** fail. |
| `safe(fn, label, default)` | Optional steps that must never fail a run. |

### Transient vs permanent — the important distinction

Retrying a `403` five times just burns the run's time budget. Only
`408/425/429/500/502/503/504`, timeouts and connection errors retry; every
other 4xx fails immediately.

Verified: a flaky call recovered on attempt 3; a `403` stopped after **1**.

### Circuit breaker

3 consecutive failures opens a provider for 300s, and `first_ok` skips it.
Success closes it immediately.

**Bug found while testing:** `breaker_open()` cleared the record whenever
`time() >= until`, but `until` starts at `0`, so the failure count reset on
every call and the breaker could never trip. Now it only clears once a
cooldown has actually started.

## Where fallbacks exist

| Stage | Primary | Fallback | Status |
|---|---|---|---|
| LLM text | Mistral | Groq → Gemini → … | already cascaded |
| Images | Cloudflare Flux | Pollinations | already cascaded |
| **Video** | **JSON2Video** | **ffmpeg (local)** | cascade + alert on each step |
| JSON parsing | direct parse | truncation repair → regenerate | added 2026-09-04 |
| Whop cover | GraphQL upload | `pending_manual` (never fails run) | existing |
| Distribution | 21 channels | queue + backoff; dead channel skipped | existing |
| Marketplace | submit | idempotent re-poll each cycle | existing |

## What now alerts to Discord

| Event | Level |
|---|---|
| Preflight failure (run aborted) | 🚨 error |
| Asset generation exception | 🚨 error |
| **Factory idle — 0 assets produced** | 🚨 error |
| All providers of a capability exhausted | 🚨 error |
| Distribution wholly failing (≥3 jobs, 0 posted) | 🚨 error |
| QC blocked an asset | ⚠️ warn |
| Channel dead (permanent / max retries) | ⚠️ warn |
| Provider circuit opened | ⚠️ warn |
| Video fell back to ffmpeg | ⚠️ warn |

Config: `DISCORD_ALERT_WEBHOOK` (falls back to `DISCORD_PROMO_WEBHOOKS`).
Every alert carries a direct link to the failing GitHub run.

**Verified live** — test alerts delivered to the Spidey Bot channel, and a
real mock run produced:

```
[alert:error] Asset generation failed: … ModuleNotFoundError: No module named 'weasyprint'
[alert:error] FACTORY IDLE — 0 assets produced
```

That is exactly the outage that previously passed silently.

## Deliberate non-goals

- **No alert on every transient retry.** Noise trains you to ignore alerts;
  only exhaustion is reported.
- **No LLM judging failures.** Deterministic rules only.
- **Alerts are deduplicated.** One bad loop cannot post 50 Discord messages.
