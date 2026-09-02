# Whop product cover images — VERIFIED WORKING SEQUENCE

Status as of 2026-09-02: the App API key `app_aJFKUT7MnR5730` **works**.
Image upload succeeds. One permission is still missing for the final attach.

## The sequence (all verified live)

1. **`mediaDirectUpload`** GraphQL mutation at `https://api.whop.com/public-graphql`
   with `contentType`, `byteSizeV2`, `checksum` (base64 MD5), `filename`, and
   `record: "access_pass"`. A Whop *product* is an **access_pass** internally —
   passing `"product"` is rejected by the enum.
   Returns `{ id, uploadUrl, headers }`.
2. **`PUT`** the raw bytes to `uploadUrl` with exactly the returned headers. -> **200**
3. **`updateAccessPass`** with `galleryImages: [{ id: <blob id> }]`.
   `AttachmentInput` accepts **only** `id` (not `directUploadId`, not `url`).

Auth: `Authorization: Bearer <app key>` + `x-whop-app-id: app_aJFKUT7MnR5730`.
The plain company key gets 401 on step 1 — the App key is required.

Implemented in `engine/whop_media.py`, called from `engine/publish.py`.

## THE ONE REMAINING STEP

Steps 1 and 2 succeed. Step 3 returns:

```
403 forbidden — Required permission: access_pass:update
```

Grant that scope to the app:

1. <https://whop.com/dashboard> -> your company -> **Developer** -> app `asset-bot`
   (`app_aJFKUT7MnR5730`).
2. Open **Permissions** (or *Scopes* / *API access*).
3. Enable **`access_pass:update`** — it may be listed as *Manage products* or
   *Update access passes*. Also keep whatever grants attachment upload (already working).
4. Save. No key regeneration needed — the same key picks up the new scope.

Then re-run the daily cycle, or backfill the two existing products with:

```bash
cd engine && WHOP_APP_API_KEY=... WHOP_APP_ID=app_aJFKUT7MnR5730 python3 -c "
import whop_media
for pid, img in [('prod_3rUWWBYz3FsuL', 'IMAGE_URL_1'),
                 ('prod_F080AA8beZEie', 'IMAGE_URL_2')]:
    print(pid, whop_media.set_product_gallery(pid, [img]))"
```

## GitHub secrets to add

| Secret | Value |
|---|---|
| `WHOP_APP_API_KEY` | the App API key (`apik_K7kGZ...`) |
| `WHOP_APP_ID` | `app_aJFKUT7MnR5730` |

`daily-cycle.yml` already exports both.

## Prompt for Whop AI (only if the scope toggle isn't in your dashboard)

> My app `app_aJFKUT7MnR5730` (company `biz_A79oVYva4QTT8Z`) uploads media
> successfully via `mediaDirectUpload` with `record: access_pass`, and the S3
> PUT returns 200. But calling `updateAccessPass` with
> `galleryImages: [{id: <blobId>}]` returns
> `403 forbidden — Required permission: access_pass:update`.
> Where exactly do I grant `access_pass:update` to my app, and does it require
> app review/approval? I am calling the API headless from a server with the App
> API key, not from an iframe with a user token.
