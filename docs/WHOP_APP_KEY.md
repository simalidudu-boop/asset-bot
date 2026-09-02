# Getting a Whop App API key (unlocks product cover images)

## Why this is needed

The bot's current key is a **company REST key**. It can create products, read
data and PATCH v1 plans, but it is **denied** on the media upload routes:

| Route | Result with current key |
|---|---|
| `POST /api/v2/attachments` | `401 — API Key does not have permission` |
| `mediaDirectUpload` (GraphQL) | `"You must provide a valid App API Key"` |

Whop refuses external image URLs on products: `gallery_images[].url` must be a
`media.whop.com` URL, which only exists after an upload through the attachment
API. So cover images are impossible until an **App API key** exists.

## Do it yourself (2 minutes)

1. Go to <https://whop.com/dashboard> and select the company
   **The Algorithmic Daemon Concern** (`biz_A79oVYva4QTT8Z`).
2. In the left sidebar open **Developer** (some accounts show it as
   *Developer settings* / *Apps*).
3. Click **Create App**. Name it `asset-bot`. You do **not** need to give it a
   path, iframe URL, or any views — an app created purely for API access is fine.
4. Open the new app and find the **API key** section (labelled *App API key* or
   *Server API key*). Copy the value — it starts with `app_` or is shown as the
   app's secret key.
5. Under the app's **Permissions / Scopes**, make sure these are enabled:
   - `attachment:create` (or *Upload media / attachments*)
   - `product:update` (or *Manage products*)
   Save.
6. Add it to the repo: **GitHub → Settings → Secrets and variables → Actions →
   New repository secret**
   - Name: `WHOP_APP_API_KEY`
   - Value: the key from step 4

That's it. The publish code already attempts the upload → attach flow and will
start populating covers on the next daily run.

## Prompt for Whop AI support

Copy-paste this if you'd rather have them walk you through it:

> I have a company API key for my company `biz_A79oVYva4QTT8Z` that I use for
> server-side automation. It works for creating products and for `PATCH
> /api/v1/plans/{id}`, but I get `401 "The API Key supplied does not have
> permission to access this route"` on `POST /api/v2/attachments`, and the
> `mediaDirectUpload` GraphQL mutation replies `"You must provide a valid App
> API Key"`.
>
> My goal: programmatically set the gallery/cover image on products I create
> via the API. I've confirmed that passing an external image URL is rejected —
> `gallery_images[{url}]`, `gallery_images[url]`, `image_url` and `logo` all
> return `400 parameter_invalid` — so I understand the image must first be
> uploaded to `media.whop.com`.
>
> Please tell me exactly:
> 1. The steps to create an App and obtain an App API key for this company.
> 2. Which scopes/permissions that key needs to upload an attachment and to
>    attach it to a product.
> 3. The exact request sequence to upload an image from a public URL (or from
>    raw bytes) and then set it as a product's gallery/cover image, using plain
>    HTTP — I am not using the Node SDK or running inside an iframe, this is a
>    headless server-side script.
> 4. Whether an App API key can act on products owned by my company without a
>    user token / installed-app context.

## What changes once you have it

Nothing in the code — it's already written. `engine/publish.py` tries
`POST /attachments` then `PATCH /products/{id}` with the returned attachment id.
Until the key exists it records `cover_status: "pending_manual"` and keeps the
hosted image URLs on the asset, and the Command Center raises an alert listing
how many live products are missing covers.

If Whop tells you the App key uses a different header or base URL than the
company key, set `WHOP_APP_API_BASE` too and the client's `api=` switch will
route to it.
