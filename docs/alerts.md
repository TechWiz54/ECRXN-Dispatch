# Alerts

When a trigger fires, ECRXN Dispatch can send alerts through **Telegram, Discord, Pushover, Email, Facebook, Make
and n8n**.

- [System and trigger alerts](#system-and-trigger-alerts) · [A trigger's Notifiers tab](#a-triggers-notifiers-tab)
- [Sending the audio](#sending-the-audio-a-file-a-link-or-both) · [Facebook](#facebook) · [Placeholders](#placeholders)

---

## System and trigger alerts

| | Where | What it sends |
|---|---|---|
| **System alert** | **Radio Systems** → a system → its channel tabs | One alert per call, listing every trigger that fired |
| **Trigger alert** | **Triggers** → a trigger → **Notifiers** | One alert for that trigger only, to its own channel, group, address or Page |

Both can be on at once. For example, every station goes to the county's Pushover group through the system alert,
while "Station 4 Fire" also goes to Station 4's own Discord channel.

Every message box starts filled in with a working message, both on a system and on each trigger, so alerts make
sense straight away. Change any of them; the [placeholders](#placeholders) below fill in the details.

---

## A trigger's Notifiers tab

Each channel has two switches. Both save as soon as you flip them.

- **Include in the system's … alert.** Whether this trigger is part of the system's alert on that channel.
  New triggers are only in the system's **Pushover** alert; switch others on as you need them. (Triggers made
  before version 1.2 keep being in every system alert, as they were.)
- **Send this trigger's own … alert.** A separate alert for this trigger only, using the settings in the card.
  If something needed (marked <span style="color:red">*</span>) is missing, it switches back off and says what.

The header shows **System: in / left out** (when the system's alert for that channel is on) and **Own: on / off /
not set up**. The number on the tab counts the trigger's own alerts that are on.

To set one up: fill in where it goes (channel ID, webhook URL, email addresses, Page ID or Pushover keys), press
**Send test** (it uses the form as it is, so you can test before saving, with the audio from the system's latest
call), press **Save**, then switch on **Send this trigger's own … alert**.

**Shared settings.** Leave a bot token, page token, API key or passphrase blank to use the system's. Email uses the
system's mail server unless you switch on **Use a different mail server for this trigger** and fill in its
own server, login and "from" address.

**Your own content per trigger:**

- **Telegram, Pushover, Email, Facebook**: their own message, title, subject or post text.
- **Discord**: a **Message** above the embed (e.g. `@here {trigger_list} dispatched`), the embed title, colour,
  footer and **Embed fields** (label, value, inline).
- **Make**: your own **keys and values**, e.g. `message` = `{trigger_list} at {timestamp_24}`.
- **n8n** sends every placeholder. Its JWT settings come from the system.

In a trigger's own alert, `{trigger_list}` is just that trigger's name, and `{stream_url}` is the trigger's own
stream URL if it has one.

---

## Sending the audio: a file, a link, or both

Put `{audio_url}` anywhere in a message to include a link to the call audio. Most channels can also send the
**audio file itself**. Each is a switch on the system and on each trigger, and **all start off**:

| Channel | Switch | On | Off |
|---|---|---|---|
| Telegram | **Send the audio file as a voice message** | A voice message with your message as its caption | A text message |
| Discord | **Attach the audio file** | The MP3 is attached and plays in Discord (up to 10 MB) | Embed only |
| Make | **Also send the audio file** | Form data: your keys plus the file in the field `audio` | JSON |
| n8n | **Also send the audio file** | Form data: every field plus the binary field `audio` | JSON |
| Email | **Attach the audio file** | The MP3 is attached (up to 25 MB) | Message only |
| Facebook | **Post as a video with the call audio** | A video of the audio over your background ([below](#facebook)) | A text post with a link |
| Pushover | none | Pushover can't carry audio files, so its alerts link to the audio | |

Want both? Switch the file on and keep `{audio_url}` in the text.

> **Make / n8n:** with the file on, the webhook receives `multipart/form-data` instead of JSON. Make hands you the
> file for an *Upload* or *HTTP* module; n8n's Webhook node puts it under **Binary → audio**.

---

## Facebook

Alerts can post to a **Facebook Page** (Facebook doesn't let apps post to personal profiles). Set it up on a
system (**Radio Systems → Facebook**), on a trigger (**Notifiers → Facebook**), or both. You need two things:
the **Page ID** and a **Page access token**. Setting it up takes about 15 minutes the first time.

> Meta moves its menus around now and then. If a button below has a slightly different name, look for the
> closest match.

### 1. Find the Page ID

1. On Facebook, switch to your Page (your profile picture, top right → pick the Page) and open the Page.
2. Click the **Page name** in the Page's intro (or **About**). A box opens.
3. At the bottom of the box is **Page transparency**: the Page's name, its category, and under them the
   **Page ID**, a long number like `104123456789012`. Copy it.

### 2. Create a Meta app (once)

1. Go to [developers.facebook.com](https://developers.facebook.com/) and log in with the Facebook account that
   manages the Page. The first time, click **Get started** and verify your account.
2. **My Apps → Create app.** Give it a name such as "ECRXN Dispatch" and your email.
3. When asked what the app should do (the **use case**), choose **Manage everything on your Page**. If you're asked
   for an app type instead, pick **Business**. If it offers to connect a **business portfolio**, pick yours (or
   skip it and connect it later, in step 3a).
4. Open the use case's **Customize** (or **Permissions**) page and add `pages_manage_posts`,
   `pages_read_engagement` and `pages_show_list`. That's all it needs, for text posts and video posts alike.
   (Older guides mention `publish_video`; Meta no longer uses it for Page videos, which is why you won't find it.)
5. Your Facebook account needs full control of the Page (or at least the **Create content** task), or Facebook
   refuses posts even with the right permissions.

### 3. Get a token that never expires (recommended)

Tools that run on their own, like n8n or Make, either ask you to click **Connect Facebook** again when the token
runs out, or use a **system user**: a non-person account in a Meta *business portfolio* whose token can be set to
never expire. ECRXN Dispatch works with a system user, so you only do this once.

**a. Put your Page in a business portfolio.** Most people don't have one yet; it's free:

1. Go to **[business.facebook.com](https://business.facebook.com)**.
2. On the left, under the **Meta Business Suite** logo, is your Page's or portfolio's name. Hover over (or click)
   it: at the bottom of the list are your **business portfolios** and other assets. If you have none, choose
   **Create a business portfolio** and fill in your name and email.
3. Open the portfolio's **Settings** (the gear at the bottom left) → **Accounts → Pages → Add → Add a Page**, and
   type your Page's name. Because you manage the Page, it's added straight away.
4. Still in Settings: **Accounts → Apps → Add → Connect an app ID**, and enter your app's ID (shown at the top of
   your app on developers.facebook.com).

**b. Make the system user and its token:**

1. In the portfolio's Settings: **Users → System users → Add.** Name it "ECRXN Dispatch" and give it the **Admin**
   role.
2. With the system user selected, click **Assign assets**: pick your **Page** and turn on **Full control** (or at
   least *Create content*). Click **Assign assets** again and add your **app**.
3. Click **Generate token**. Pick your app, set **Token expiration** to **Never**, tick `pages_manage_posts`,
   `pages_read_engagement` and `pages_show_list`, and click **Generate token**. Copy it right away: Meta shows it
   only once.

Paste that token into ECRXN Dispatch as the **Page access token**. It's a system-user token, not a Page token, and
that's fine: ECRXN Dispatch asks Facebook for the Page's own token with it each time it posts. It keeps working
until you delete the system user or take away its access to the Page.

**Without a business portfolio (Graph API Explorer).** This works, but the token does **not** last forever:
Meta asks you to renew it every couple of months, so you'll be back here to repeat it. Use it to try things out,
and the system user for everyday use.

1. In the **[Graph API Explorer](https://developers.facebook.com/tools/explorer/)**, pick **your app** under
   *Meta App*, choose **Get User Access Token**, tick the three permissions and click **Generate Access Token**.
   Allow them and choose your Page. (Picking your Page in the **User or Page** menu gives a Page token straight
   away, but that one lasts only about an hour.)
2. Click the **ⓘ** next to the token → **Open in Access Token Tool** → **Extend Access Token**. Copy the long token.
3. Back in the Explorer, paste it into **Access Token**, run `me/accounts` and copy your Page's **`access_token`**.
   Paste that one into ECRXN Dispatch (not the extended token itself, which runs out after about 60 days).

### If posting still doesn't work

Paste your token into the [Access Token Debugger](https://developers.facebook.com/tools/debug/accesstoken/) and check:

- **Scopes** lists `pages_manage_posts`, `pages_read_engagement` and `pages_show_list`, and **Granular scopes**
  shows your Page's ID next to them. If your Page isn't there, the token was made without access to it: for a
  system user, assign the Page (step b.2) and generate a new token; in the Explorer, choose the Page when Facebook
  asks which Pages to allow.
- **Valid: True** and, for a system user, **Expires: Never**.
- The app is **Live** (step 4) and connected to the same business portfolio as the Page (step a.4).

The **Send test** button shows Facebook's own error message; that message says what's missing.

### 4. Switch the app to Live

While an app is in **Development** mode, its posts are only visible to people with a role on the app. Switch it
to **Live** so everyone sees them:

1. **App settings → Basic:** fill in a **Privacy Policy URL** (any page on your website, for example
   `https://ecrxn.com/privacy`), pick a **Category**, upload an **App icon**, and **Save changes**.
2. At the top of the app dashboard, switch **App Mode** from **Development** to **Live**.

You don't need App Review to post to a Page your own business manages.

### 5. Put it in ECRXN Dispatch

On **Radio Systems → Facebook** (or a trigger's **Notifiers → Facebook**), paste the **Page ID** and the **Page
access token**, save, and press **Send test**. If Facebook refuses, the message says why (for example *"Invalid
OAuth access token"* means the token was copied wrong or has expired: repeat step 3; *"(#200) Permissions
error"* means your account or the system user can't create content on the Page: check step 2.5 / 3.3).

**Post as a video with the call audio** (off by default):

- **Off**: a text post with the audio link attached.
- **On**: the audio goes over a background picture or clip and is uploaded as a video people can play in their
  feed. Calls up to **90 seconds** become vertical 9:16 videos, which Facebook shows as **Reels**; longer calls
  become widescreen 16:9 videos (Reels can't be longer than 90 seconds).

### Video backgrounds

With the video switch on, a **Video background** box appears. Upload a **picture** (JPG, PNG, WebP, HEIC, TIFF,
BMP, AVIF and more; up to **250 MB**) or a **clip** (MP4, MOV, WebM, MKV, AVI, WMV, GIF and most others; up to
**2 GB**). Big files are fine; they're shrunk when saved:

- pictures become a JPG up to 2160 px on the long side
- clips become a silent 1080p MP4 of their first 60 seconds, which loops for the length of the call

A **system background** is used by every trigger without its own; a **trigger background** replaces it for that
trigger (say, an EMS picture for EMS stations). With neither, the video is black. Pictures are cropped to fill the
frame, so a 1080×1920 portrait picture looks best. **Preview video** shows the first 15 seconds of the latest call
over the background before anything is posted.

Post text is plain text (HTML is removed). If Facebook rejects a post, the test button and the log show
Facebook's own reason. If Meta retires the API version, set `FACEBOOK_GRAPH_VERSION` in `.env`.

---

## Placeholders

Write a placeholder in braces, like `{trigger_list}`, anywhere in a message, subject, title, embed field, Make
value or post text. `{{trigger_list}}` works too. Anything that isn't a placeholder is left as you typed it.

**Calls and triggers**

| Placeholder | Example | Notes |
|---|---|---|
| `{trigger_list}` | `Station 4 Fire, County EMS` | Triggers that fired, comma separated |
| `{trigger_list_lines}` | `Station 4 Fire`<br>`County EMS` | One per line |
| `{trigger_count}` | `2` | |
| `{trigger_names}` | `["Station 4 Fire", "County EMS"]` | A list, for JSON (n8n) |
| `{system_name}` | `Demo County` | |
| `{system_id}` | `1001` | The System ID your uploader sends |
| `{talkgroup_id}` | `100` | |
| `{talkgroup_name}` | `Fire Dispatch` | When the uploader sends one |
| `{audio_url}` | `https://…/static/audio/2026/11/12/….mp3` | Link to the call audio |
| `{stream_url}` | `https://www.broadcastify.com/…` | The system's (or trigger's) stream URL |
| `{duration_s}` | `12.3` | Call length in seconds |
| `{duration_hms}` | `00:00:12` | |

**Time** (in the `TIMEZONE` from `.env`)

| Placeholder | Example |
|---|---|
| `{timestamp_readable}` (also `{timestamp_local}`) | `21:01 Nov 12 2026` |
| `{timestamp_24}` | `21:01:17` |
| `{timestamp_12}` | `9:01:17 PM` |
| `{timestamp_iso_local}` | `2026-11-12T21:01:17-05:00` |
| `{timestamp_iso_utc}` (also `{timestamp_utc}`) | `2026-11-13T02:01:17+00:00` |
| `{timestamp}` (also `{start_epoch_s}`) | `1794535277` (seconds since 1970, for machines) |

**Transcript** (with [transcription](ai-features.md#transcription) on)

| Placeholder | Example |
|---|---|
| `{transcript}` (also `{transcript_text}`) | `Engine 4, structure fire, 125 Sunset Street…` |
| `{transcript_json}` | The timed segments as JSON |

**Address** (with [address extraction](ai-features.md#address-extraction) on; blank otherwise)

| Placeholder | Example |
|---|---|
| `{address}` (also `{address_line}`, `{address_raw}`) | `125 Sunset Street, Sayre, PA 18840` |
| `{address_city}` / `{address_county}` / `{address_state}` / `{address_postal}` / `{address_country}` | `Sayre` / `Bradford` / `PA` / `18840` / `US` |
| `{address_lat}` / `{address_lng}` | `41.97` / `-76.52` |
| `{address_maps_url}` | A Google Maps link |
| `{address_source}` | `GEOCODED`, `EXTRACTED` or `NONE` |
| `{address_json}` | Everything above as JSON |

**Incident type** (with [incident classification](ai-features.md#incident-classification) on; `-` otherwise)

| Placeholder | Example |
|---|---|
| `{incident_category}` | `Fire` |
| `{incident_type}` | `Structure Fire` |
| `{incident_confidence}` | `0.92` |
| `{incident_json}` | All three as JSON |

**Example**

```text
🚨 {trigger_list}
{incident_type} at {address}
{timestamp_readable} · TG {talkgroup_id}
Listen: {audio_url}
```

Telegram and Facebook messages are plain text; `\n` in a message also makes a new line. Email bodies can use HTML
(`<br>`, `<a href="{audio_url}">`). Pushover allows simple HTML (`<b>`, `<font color>`, `<a>`).
