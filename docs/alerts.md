# Alerts

When a trigger fires, ECRXN Dispatch can send alerts through **Telegram, Discord, Pushover, Email, Facebook, Make
and n8n**.

- [System and trigger alerts](#system-and-trigger-alerts) · [A trigger's Notifiers tab](#a-triggers-notifiers-tab)
  · [Trigger groups](#trigger-groups)
- [Sending the audio](#sending-the-audio-a-file-a-link-or-both) · [Facebook](#facebook) · [Placeholders](#placeholders)

---

## System and trigger alerts

| | Where | What it sends |
|---|---|---|
| **System alert** | **Radio Systems** → a system → its channel tabs | One alert per call, listing every trigger that fired |
| **Group alert** | **Triggers** → a group (e.g. Fire, EMS) → **Notifiers** | One alert per call for the group, listing its triggers that fired |
| **Trigger alert** | **Triggers** → a trigger → **Notifiers** | One alert for that trigger only, to its own channel, group, address or Page |

They can all be on at once. For example, every station goes to the county's Pushover group through the system alert,
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

## Trigger groups

Group a system's triggers, say **Fire** and **EMS**, and each group sends its own alerts, with its own
messages, channels and Facebook video background. For example, fire stations post to Facebook over a fire truck
picture and EMS stations over an ambulance picture, from the same Page.

**Set one up** (on the **Triggers** page):

1. Click **Add group**, give it a name and a colour.
2. Tick the triggers that belong in it (each trigger can be in one group). You can also pick a trigger's
   **Group** on its General tab. The trigger list then shows each group with its triggers under it.
3. Open the group's **Notifiers** tab and set up its alerts the same way as a trigger's: fill in where it goes,
   **Send test**, **Save**, then switch on **Send this group's … alert**. Facebook has its own **Video background**.

**How a group alert is sent:**

- Once per call, when any of the group's triggers fire. `{trigger_list}` names the group's triggers that fired
  (`Station 4 Fire, Station 12 Rescue`) and `{group_name}` the group (`Fire`). If fire and EMS triggers fire in
  the same call, the Fire group and the EMS group each send their own.
- A trigger that has **its own** alert on a channel sends that instead, and is left out of its group's alert on that
  channel. Its Notifiers tab shows **Fire: in** or **Fire: own instead** for each channel.
- Blank tokens and messages use the system's. In a trigger's own alert, blank ones use its group's first, then the
  system's (and a trigger without its own Facebook background uses the group's).
- The **system alert** is separate. If a trigger should only go out through its group, switch off its
  **Include in the system's … alert** on that channel (new triggers are only in the system's Pushover alert).

Deleting a group keeps its triggers, just without a group. A whole-system export includes the groups; triggers
imported into another system come in without a group.

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

### 2. Make a business portfolio and add your Page

Everything else happens in a free Meta **business portfolio**, so you only need one website and the token can be
set to never expire.

1. Go to **[business.facebook.com](https://business.facebook.com)** and log in with the Facebook account that
   manages the Page.
2. On the left, under the **Meta Business Suite** logo, is your Page's or portfolio's name. Hover over (or click)
   it: at the bottom of the list are your **business portfolios**. If you have none, choose
   **Create a business portfolio** and fill in your name and email.
3. Open the portfolio's **Settings** (the gear at the bottom left) → **Accounts → Pages → Add → Add a Page**, and
   type your Page's name. Because you manage the Page, it's added straight away.

### 3. Create the app

Still in the portfolio's Settings:

1. **Accounts → Apps**, then **Add** (top right) → **Create a new app ID**.
2. Give it a name such as "ECRXN Dispatch" and your email.
3. **Use case:** open the **All** list and choose **Manage everything on your Page**.
4. **Business:** pick the business portfolio you just made.
5. **Requirements:** click **Next**. **Overview:** click **Create app** (bottom right).

That use case already includes the permissions ECRXN Dispatch needs, for text and video posts alike. (Older guides
mention `publish_video`; Meta no longer uses it for Page videos, which is why you won't find it.)

### 4. Make a system user and give it the app and the Page

A **system user** is a non-person account in the portfolio. Its token can be set to never expire.

1. **Users → System users → Add.** Give it a name such as "ECRXN Dispatch" and set **System user role** to
   **Admin**.
2. **Accounts → Apps**, select your app, and under **People** click **Add people** (or **Assign people**). Pick the
   system user, give it **Full control** of everything, and confirm. The system user now shows under the app.
3. Back in **Users → System users**, select the system user, click **Assign assets**, pick your **Page** and turn
   on **Full control**.

### 5. Generate the token

1. In **Users → System users**, select the system user and click **Generate token**. It walks you through it.
2. **App:** pick your app.
3. **Expiration:** **Never** (recommended) or **60 days**.
4. **Permissions:** tick
   - `pages_show_list`
   - `pages_manage_posts`
   - `pages_read_engagement`
   - `business_management`

   If your app or the permissions don't appear, **refresh the page** and click **Generate token** again; Facebook
   sometimes doesn't show them until you refresh after step 4.2.
5. Finish, then copy the token right away: Meta shows it only once.

That's the token you paste into ECRXN Dispatch as the **Page access token**. It's a system-user token, not a Page
token, and that's fine: ECRXN Dispatch asks Facebook for the Page's own token with it each time it posts. A
**Never** token keeps working until you delete the system user or take away its access to the Page or the app; a
**60 days** token needs step 5 repeated when it runs out.

### 6. Switch the app to Live

While an app is in **Development** mode, its posts are only visible to people with a role on the app. Switch it
to **Live** so everyone sees them. Open the app at [developers.facebook.com](https://developers.facebook.com/)
(**My Apps**):

1. **App settings → Basic:** fill in a **Privacy Policy URL** (any page on your website, for example
   `https://ecrxn.com/privacy`), pick a **Category**, upload an **App icon**, and **Save changes**.
2. At the top of the app dashboard, switch **App Mode** from **Development** to **Live**.

You don't need App Review to post to a Page your own business manages.

### 7. Put it in ECRXN Dispatch

On **Radio Systems → Facebook** (or a trigger's **Notifiers → Facebook**), paste the **Page ID** and the **Page
access token**, save, and press **Send test**. If Facebook refuses, the message says why (for example *"Invalid
OAuth access token"* means the token was copied wrong or has expired: repeat step 5; *"(#200) Permissions
error"* means the system user can't create content on the Page: check step 4).

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

A **system background** is used by every alert without its own; a [group](#trigger-groups) background replaces it
for that group's alerts (say, an EMS picture for the EMS group), and a **trigger background** for that trigger's own
alert. A trigger without its own uses its group's, then the system's. With none, the video is black. Pictures are cropped to fill the
frame, so a 1080×1920 portrait picture looks best. **Preview video** shows the first 15 seconds of the latest call
over the background before anything is posted.

Post text is plain text (HTML is removed). If Facebook rejects a post, the test button and the log show
Facebook's own reason. If Meta retires the API version, set `FACEBOOK_GRAPH_VERSION` in `.env`.

### If posting still doesn't work

Paste your token into the [Access Token Debugger](https://developers.facebook.com/tools/debug/accesstoken/) and check:

- **Scopes** lists `pages_manage_posts`, `pages_read_engagement` and `pages_show_list`, and **Granular scopes**
  shows your Page's ID next to them. If your Page isn't there, the token was made without access to it: assign
  the Page to the system user (step 4.3) and generate a new token.
- **Valid: True** and **Expires: Never** (or a date, if you chose 60 days).
- The app is **Live** (step 6) and in the same business portfolio as the Page.

The **Send test** button shows Facebook's own error message; that message says what's missing.

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
| `{group_name}` | `Fire` | In a [group's alert](#trigger-groups), the group; in a trigger's own alert, its group (blank otherwise) |
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
