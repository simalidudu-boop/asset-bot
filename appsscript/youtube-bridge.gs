/**
 * ============================================================================
 *  YOUTUBE UPLOAD BRIDGE — Google Apps Script
 * ============================================================================
 *  Why this exists
 *  ---------------
 *  Uploading to YouTube normally needs a Google Cloud Console project, an
 *  OAuth consent screen, an OAuth client and a refresh token. Apps Script
 *  skips ALL of that: the "YouTube Data API v3" Advanced Service runs under
 *  the script owner's own Google account, so there is no Cloud project to
 *  create, no OAuth client, and no credit card.
 *
 *  This file turns that capability into a tiny HTTP endpoint that asset-bot's
 *  Python worker can call (engine/dist_channels.py -> ch_youtube).
 *
 *  SETUP (5 minutes, once)
 *  -----------------------
 *   1. script.google.com -> New project. Paste this file in.
 *   2. Left sidebar -> Services (+) -> add "YouTube Data API v3".
 *      The identifier must be `YouTube`.
 *   3. Project Settings -> Script Properties -> add:
 *          SHARED_SECRET = <a long random string you invent>
 *   4. Deploy -> New deployment -> type "Web app"
 *          Execute as:        Me
 *          Who has access:    Anyone
 *      Copy the /exec URL.
 *   5. Run `authorizeOnce` from the editor once and accept the Google consent
 *      screen (this is what grants YouTube upload rights).
 *   6. In asset-bot set:
 *          YOUTUBE_BRIDGE_URL    = the /exec URL
 *          YOUTUBE_BRIDGE_SECRET = the same SHARED_SECRET
 *
 *  SECURITY: the endpoint is public (Apps Script requires "Anyone" for
 *  machine callers), so every request must carry the shared secret. Requests
 *  without it are rejected and nothing is uploaded.
 */

/** Run this once from the editor to trigger the OAuth consent prompt. */
function authorizeOnce() {
  // Touching the service is what makes Apps Script ask for permission.
  var list = YouTube.Channels.list('snippet', { mine: true });
  Logger.log('Authorized for channel: ' +
    (list.items && list.items.length ? list.items[0].snippet.title : 'none'));
}

function _secret() {
  return PropertiesService.getScriptProperties().getProperty('SHARED_SECRET') || '';
}

function _json(obj, code) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

/** Health check: GET /exec?secret=... */
function doGet(e) {
  var p = (e && e.parameter) || {};
  if (!_secret() || p.secret !== _secret()) {
    return _json({ ok: false, error: 'unauthorized' });
  }
  if (typeof YouTube === 'undefined') {
    return _json({ ok: false, error: 'advanced_service_not_enabled' });
  }
  try {
    var ch = YouTube.Channels.list('snippet,statistics', { mine: true });
    var it = (ch.items || [])[0] || {};
    return _json({
      ok: true,
      channel: (it.snippet || {}).title || '',
      channelId: it.id || '',
      videos: ((it.statistics || {}).videoCount) || '0'
    });
  } catch (err) {
    return _json({ ok: false, error: String(err) });
  }
}

/**
 * POST /exec  with JSON body:
 *   { secret, videoUrl, title, description, tags[], privacy }
 * Returns { ok, videoId, url } or { ok:false, error }.
 */
function doPost(e) {
  var body = {};
  try {
    body = JSON.parse((e && e.postData && e.postData.contents) || '{}');
  } catch (err) {
    return _json({ ok: false, error: 'bad_json' });
  }

  if (!_secret() || body.secret !== _secret()) {
    return _json({ ok: false, error: 'unauthorized' });
  }
  // action router — default stays YouTube for backwards compatibility
  if (body.action === 'blogger') {
    return _json(_bloggerPost(body));
  }
  if (body.action === 'quota') {
    return _json({ ok: true, gmailRemaining: _gmailQuota() });
  }

  if (typeof YouTube === 'undefined') {
    return _json({ ok: false, error: 'advanced_service_not_enabled' });
  }
  if (!body.videoUrl) {
    return _json({ ok: false, error: 'videoUrl required' });
  }

  try {
    var resp = UrlFetchApp.fetch(body.videoUrl, { muteHttpExceptions: true });
    if (resp.getResponseCode() !== 200) {
      return _json({ ok: false, error: 'fetch_video_' + resp.getResponseCode() });
    }
    var blob = resp.getBlob();
    blob.setName((body.title || 'video').replace(/[^a-z0-9]+/gi, '-')
      .toLowerCase().slice(0, 60) + '.mp4');

    var resource = {
      snippet: {
        title: String(body.title || 'Untitled').substring(0, 100),
        description: String(body.description || '').substring(0, 4900),
        tags: (body.tags || []).slice(0, 10),
        categoryId: '28'               // Science & Technology
      },
      status: {
        privacyStatus: body.privacy || 'public',
        selfDeclaredMadeForKids: false
      }
    };

    var yt = YouTube.Videos.insert(resource, 'snippet,status', blob);
    return _json({
      ok: true,
      videoId: yt.id,
      url: 'https://www.youtube.com/watch?v=' + yt.id
    });
  } catch (err) {
    return _json({ ok: false, error: String(err) });
  }
}

/**
 * ============================================================================
 *  BLOGGER MAIL2POST BRIDGE
 * ============================================================================
 *  Blogger can publish a post from an email sent to a secret address. Apps
 *  Script has GmailApp built in, so no SMTP server, no app password and no
 *  relay credentials are needed — it sends as the script owner.
 *
 *  POST /exec with { secret, action: "blogger", title, html, blogEmail }
 *
 *  Set BLOGGER_EMAIL in Script Properties (or pass blogEmail per request):
 *      BLOGGER_EMAIL = simalidudu.goatranger@blogger.com
 *
 *  Gmail quota on a free account is ~100 recipients/day — far more than the
 *  1-2 posts/day this pipeline produces.
 */
function _bloggerPost(body) {
  var to = body.blogEmail ||
    PropertiesService.getScriptProperties().getProperty('BLOGGER_EMAIL') || '';
  if (!to) return { ok: false, error: 'no BLOGGER_EMAIL configured' };
  if (!body.title) return { ok: false, error: 'title required' };

  try {
    // Blogger uses the SUBJECT as the post title and the BODY as the content.
    GmailApp.sendEmail(to, String(body.title).substring(0, 200), body.text || '', {
      htmlBody: body.html || body.text || '',
      name: body.fromName || 'Asset Bot'
    });
    return { ok: true, to: to, title: body.title };
  } catch (err) {
    return { ok: false, error: String(err) };
  }
}

/** Remaining Gmail sends today — useful for the dashboard. */
function _gmailQuota() {
  try { return MailApp.getRemainingDailyQuota(); } catch (e) { return -1; }
}
