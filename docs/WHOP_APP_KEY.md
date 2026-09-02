# Whop product cover images — SOLVED

Status: **working end to end** as of 2026-09-02. Both live products have covers.
Implemented in `engine/whop_media.py`, called automatically from `engine/publish.py`.

## Required setup (done)

| Item | Value |
|---|---|
| App | `asset-bot` / `app_aJFKUT7MnR5730` |
| App API key | env `WHOP_APP_API_KEY` |
| App id header | `x-whop-app-id` (env `WHOP_APP_ID`) |
| Install | app installed on the company, granting *Update products* |

The plain **company** key cannot do this — it gets 401 on the upload routes.
The **App** key alone is also not enough: before the app was installed on the
company, `updateAccessPass` returned
`403 Required permission: access_pass:update`. Installing the app fixed it.

## The verified 5-step sequence

All against `https://api.whop.com/public-graphql`:

1. **`mediaDirectUpload`** with `contentType`, `byteSizeV2`, `checksum`
   (base64 MD5), `filename`, `record: "access_pass"`.
   A Whop *product* is an **access_pass** internally — `"product"` is rejected.
   Returns `{ id (signed blob id), uploadUrl, headers }`.
2. **`PUT`** the bytes to `uploadUrl` with exactly the returned headers -> 200.
3. **`mediaAnalyzeAttachment`** with `{ directUploadId, mediaType: "image" }`.
   The enum is **lowercase** (`image|video|audio|other`). Returns a Boolean.
4. **`attachment(id: <signed blob id>)`** query -> returns the persistent
   **`file_...` id**. This is the key step: `AttachmentInput.id` means "the ID
   of an existing file object", and the signed blob id is NOT accepted —
   passing it gives `404 This Attachment was not found`.
   Registration is async, so retry this lookup for a few seconds
   (`Invalid ID` means it has not landed yet).
5. **`updateAccessPass`** with `galleryImages: [{ id: "file_..." }]`.

## Gotchas that cost time

- `record: "product"` -> enum error. Use `access_pass`.
- `mediaType: "IMAGE"` -> enum error. Use `image`.
- `galleryImages: [{directUploadId}]` -> not a field on AttachmentInput.
- `galleryImages: [{url}]` / `image_url` / `logo` -> `400 parameter_invalid`.
  External URLs are never accepted; bytes must be mirrored into Whop.
- Passing the signed blob id (or its decoded numeric id) to galleryImages ->
  `404 This Attachment was not found`. Only `file_...` works.

## GitHub secrets

| Secret | Value |
|---|---|
| `WHOP_APP_API_KEY` | the App API key |
| `WHOP_APP_ID` | `app_aJFKUT7MnR5730` |

`daily-cycle.yml` already exports both. New products get covers automatically.

## Backfill an existing product

```bash
cd engine && WHOP_APP_API_KEY=... WHOP_APP_ID=app_aJFKUT7MnR5730 python3 -c "
import whop_media
print(whop_media.set_product_gallery('prod_XXXX', ['https://.../image.jpg']))"
```
