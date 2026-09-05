# Factory 4 — THE UTILITY

Free browser tools served from the Cloudflare Worker at `/tools`.

## Two halves

**1. The announcer** (`announce_tools.py`) — cycles the existing tool set
through the distribution mesh, one tool + one angle per day. 5 tools x 3
angles = 15 distinct announcements before anything repeats.

**2. The producer** (`generate_tool_html.py`) — an LLM generates a NEW
self-contained tool, gated by a QC that **executes the generated JavaScript**
in Node and asserts the output actually changed.

Until the producer existed, F4 was a shopfront: the Worker served five
hand-written tools and nothing created a sixth. It is now a real factory.

## Why the execution gate matters

An LLM will happily emit HTML that looks like a tool and computes nothing.
That failure is invisible to any check that only looks at the markup.

Verified against four cases:

| Case | Result |
|---|---|
| working tool | **PASS 100/100** |
| `run()` that does nothing | **BLOCK** — `EMPTY_OUTPUT` |
| `run()` that throws | **BLOCK** — `THREW: … is not defined` |
| tool calling `fetch()` | **BLOCK** — forbidden construct |

The `fetch` ban is deliberate: a tool that calls out is a tool with a running
cost and a privacy story. Every tool here computes locally, so serving them is
free forever and nothing a visitor types leaves their browser.

## Files

| File | Role |
|---|---|
| `announce_tools.py` | daily rotation through existing tools |
| `generate_tool_html.py` | LLM producer + execution QC |
| `dist_*.py`, `resilience.py`, `textgen.py` | own copies of shared infra |

Tools themselves live in `workers/src/tools.ts` and are served by the Worker.

## Config

`F4_ENABLED=1` to run at all · `F4_DIST_POSTING_MODE=LIVE` to post ·
`F4_PAGE_BASE` for the tool URLs.

## Known gap

The announcer's IndexNow ping uses the dated job slug rather than the tool's
real URL, so it pings `/p/tool-x-DATE` instead of `/tools/x`. Harmless — the
real tool URLs are already in `sitemap.xml` — but worth fixing.
