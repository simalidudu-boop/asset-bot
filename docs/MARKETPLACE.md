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

### FAQs are an *experience*, not a product field

There is genuinely no FAQ field: `faq` appears **0 times** in the entire 3 MB
`api-v1-native.json` OpenAPI spec, and the GraphQL schema has no faq input
anywhere. FAQs are delivered as an **experience** — an app attached to a
product. Whop's first-party FAQs app is `app_PsBytos2S7vFcG`.

`marketplace.ensure_faq_experience()` creates that experience once and attaches
it to each product. **Attach is verified working** (200, and the experience
shows up under `publicAccessPass.experiences`). Creation needs one permission:

| Key | Missing permission |
|---|---|
| App key (`app_aJFKUT7MnR5730`) | `experience:create` |
| Company key | `app_authorization:create` |

**Whop freezes an app's grants at INSTALL time.** Adding a permission to the
app afterwards updates `requested_permissions` but does **not** apply to an
existing install — the API keeps returning 403. Proof: `experience:attach`
(present at the original install) returns 200, while `experience:create`
(added later) still 403s with the identical key.

Fix: **re-install the app** at
<https://whop.com/apps/app_aJFKUT7MnR5730/install/> and accept the new
permission list. **Confirmed: re-installing fixed it** — `experience:create`
went from 403 to 200 with the same key. Verify the grant took with:

```bash
curl -s -X POST -H "Authorization: Bearer $WHOP_APP_API_KEY" \
  -H 'Content-Type: application/json' -H 'x-whop-app-id: app_aJFKUT7MnR5730' \
  -d '{"app_id":"app_PsBytos2S7vFcG","company_id":"biz_A79oVYva4QTT8Z","name":"FAQ"}' \
  https://api.whop.com/api/v1/experiences
```

Even with the app attached, the FAQs app has **no public write API** — the
questions are typed in the app UI. So the factory generates the copy, ships it
in the deliverable, prints it paste-ready, and creates the sidebar slot.

**Manual step:** paste the copy in `docs/FAQ_TO_PASTE.md`.

### labels / banner_image — do NOT trust the beta spec here

The beta spec lists `labels` and `banner_image` on `PATCH /products/{id}`.
Neither works with our keys:

- `labels` -> **400** `Invalid value for parameter 'labels'` on both the company
  and App key, with and without `Whop-Version` / `whop-api-version` /
  `Accept-Version` headers. (Also note: `labels` are *collections*, not
  marketplace categories — it was never the Discover-category lever.)
- `banner_image` -> **200 OK, but silently does nothing.** Read back via REST
  and GraphQL: `bannerImage` is still `null`. A false success — always verify
  a write by reading it back.


### FAQ experience — current state (verified 2026-09-02)

After the re-install:

| Action | Result |
|---|---|
| Create experience for **our own app** (`app_aJFKUT7MnR5730`) | **200** — `exp_1tNTRzWvwTusVz` |
| Attach it to both products | **200**, persisted (`publicAccessPass.experiences` shows it) |
| Create experience for the **third-party FAQs app** (`app_PsBytos2S7vFcG`) | **400** `app_authorization:create` |
| `PATCH /experiences/{id}` | **403** `experience:update` |

So `ensure_faq_experience()` now defaults to **our own app**, which is fully
automatable, and is idempotent (matches on app id + name, reuses rather than
duplicating).

**Important limitation:** our app has `hosted_url: null` and
`status: hidden`, so its experience tab currently renders **nothing**. The tab
exists on the product but is an empty shell until either:

1. the app gets a `hosted_url` serving a FAQ page (we already have a Cloudflare
   Worker that could serve it), or
2. the **FAQs app is added from the dashboard** (product -> Add app -> FAQs) and
   the questions typed in its UI.

Option 2 is the fast path today. Option 1 makes FAQs fully hands-off and is the
only route that avoids `app_authorization:create` entirely.

## Worker-hosted FAQ page (built 2026-09-02)

The FAQ content now lives in `state/manifest.json` (`asset.faq`) and the Worker
renders it at:

```
GET /experiences/:experienceId?productId=prod_xxx
```

Whop's `experience_path` is `/experiences/[experienceId]` and it appends the
product id when embedding, so the route resolves in this order:

1. `?productId=` / `?product_id=` / `?accessPassId=` / `?slug=` from the query
2. `asset.faq_experience_id === :experienceId` from the manifest
3. the sole product, if only one has FAQs
4. otherwise render **every** product's FAQ rather than guessing wrong

Verified live:

| Request | Result |
|---|---|
| `?productId=prod_3rUWWBYz3FsuL` | Zero-Click Content Machine, 6 questions |
| `?productId=prod_F080AA8beZEie` | The Content Research Engine, 6 questions |
| no query hint | both products, 2 sections / 12 questions |

The page is a self-contained accordion (`<details>`), no external assets, dark
and light aware, transparent background so it blends into Whop's chrome. It
sends `content-security-policy: frame-ancestors https://whop.com
https://*.whop.com` and **no** `X-Frame-Options`, so Whop can embed it.

### BLOCKER: `base_url` cannot be set via the API

`PATCH /apps/{id}` with `base_url` returns **200 and silently does nothing** —
re-reading shows `base_url: null`. This is *not* an unknown-field error: a
deliberately bogus field returns 400, and `name` patches persist fine, so PATCH
works and `base_url` is accepted-then-ignored. Same false-success class as
`banner_image`.

**Manual step (one time, ~1 minute):** Whop dashboard -> Developer -> app
`asset-bot` -> set the hosted/base URL to

```
https://asset-bot-edge.simalidudu.workers.dev
```

and confirm **Experience path** is `/experiences/[experienceId]`.

Once that URL is set, the FAQ tab already attached to every product renders the
generated FAQ automatically, for all future products, with no further Whop
permissions and no per-product work.
