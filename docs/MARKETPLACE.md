# Getting products discoverable on the Whop marketplace

## Visible != discoverable

Two independent switches control who can see a product:

| Field | Values | Meaning |
|---|---|---|
| `visibility` | `visible` / `hidden` / `archived` | reachable by direct link + shown on **your own** store page |
| `marketplace_status` | `not_available` -> `pending_review` -> `live_marketplace` | shown on **whop.com/discover** |

Our factory previously only ever set `visibility: "visible"`. Every product we
shipped was therefore reachable by link but **invisible on Discover** — no
marketplace traffic, ever. This was a silent, total loss of the ~2.5M weekly
marketplace visitors.

## Whop's listing requirements

1. **Title**
2. **Headline**
3. **Description**
4. **Logo** — company-level, shared by all products
5. **Gallery images** — at least one (video preferred)
6. **At least one available pricing option** — a visible plan

Then submit: `POST /api/v1/products/{id}/publish` -> `marketplace_status: pending_review`.
Whop reviews it and moves it to `live_marketplace`. You get a Team Whop message
either way.

## How the factory does it now

`engine/marketplace.py`:

- `check_requirements(product_id, company_id)` — validates all six requirements
  and returns exactly what is missing.
- `publish(product_id, company_id, known_status=...)` — validates, then submits.
  Never raises; a listing failure cannot fail a publish run.

Wired into two places:

- **`publish.py::publish_asset()`** — free products go visible immediately, so
  they are submitted right after the cover image is attached.
- **`publish.py::approve()`** — paid products are hidden until `/approve`. They
  get their plan + visibility there, which is the moment they first qualify, so
  they are submitted there too.

`run_daily.py` records `marketplace_status` in `state/manifest.json`, and the
Command Center raises an alert for any live product that was never submitted.

## Verified live (2026-09-02)

Both existing products were audited, found compliant, and submitted:

| Product | Result |
|---|---|
| `prod_3rUWWBYz3FsuL` Zero-Click Content Machine | `pending_review` |
| `prod_F080AA8beZEie` The Content Research Engine | `pending_review` |

The validator was also proven negative: `prod_XzidDlN33ult6` correctly reported
`missing: ['headline', 'description']` instead of being blindly submitted.

## API caveats found the hard way

- **`GET /products/{id}` does not return `marketplace_status`.** Only the
  publish response does. Track it in the manifest; do not try to read it back.
  Re-publishing is idempotent (200, stays `pending_review`), so a duplicate
  submit is harmless.
- `GET /plans` requires `account_id` — `/plans?product_id=` silently returns
  nothing, which looks identical to "product has no plans".
- Plan `initial_price` is sometimes a float and sometimes an object with
  `amount`; handle both.

## Still manual / your call

- **Product `type` and `category`** improve Discover placement. They are set in
  the product editor UI and are not exposed on the v1 create/update payloads we
  have access to — worth setting once per product by hand.
- **Reviews**: some third-party guides claim Discover also wants at least one
  paid product and a genuine customer review. Whop's own changelog says
  approval is instant. We cannot control reviews programmatically either way.

## FAQs — generated, but not writable via API

Whop product store pages have a dedicated **FAQs** section. It is a real
conversion lever and both our products shipped with it empty.

**It cannot be set through the API.** Verified three ways:

- `PATCH /api/v1/products/{id}` with `faq` -> `400 Invalid value for parameter 'faq'`.
  A deliberately bogus parameter (`unknown_zzz`) returns the *identical* error,
  so `faq` is simply unrecognised — not merely mis-shaped. Tried list-of-objects,
  object map, `title`/`content` keys and an empty list: all identical.
- `UpdateAccessPassInput` has **no** `faq` field (`Field is not defined`).
- The schema has a `FaqObject` type and `AccessPass.faq` is **readable**, but
  there is no FAQ mutation anywhere in the schema.

So the factory does the half it can:

- `generate_pack.py` now asks the model for a `faq` array, and `ensure_faq()`
  guarantees at least 4 sensible Q&As even when the model omits them or returns
  a malformed shape (it keeps whatever the model produced and tops up).
- FAQs are rendered into the deliverable itself (a `## FAQ` section), so buyers
  get the answers even while the store page section is empty.
- `marketplace.faq_report()` prints the generated Q&A in paste-ready form on
  every publish, and reports whether the live product already has any.

**Manual step:** Product editor -> FAQs -> Add question. Copy for the two
existing products is in `docs/FAQ_TO_PASTE.md`.
