# How ECRXN Dispatch works

This explains what ECRXN Dispatch does, why it's built the way it is, and what happens inside when a call comes
in. It's for anyone who runs it, wants to help with it, or is just curious. Setup steps are in the
[Setup guide](docs/setup.md).

---

## Why it exists

Fire and EMS departments are paged over the radio with **tones**: short beeps at exact pitches, a different pair
for each department, sent just before the dispatcher speaks. Pagers in the field wake up when they hear their own
tones.

Plenty of people can't carry a pager but need or want to know when a department is dispatched: members off duty,
officers, neighbouring departments, local news pages, scanner listeners. Scanner software already records every
radio call. ECRXN Dispatch listens to those recordings, recognises each department's tones, and passes the call on
to wherever people are (a Telegram group, a Discord channel, a Facebook Page, a phone notification, email, or any
automation) with the audio, the time and, optionally, the words that were said and where.

It's maintained by the [East Coast Receiver Network](https://ecrxn.com) and based on
[iCAD Dispatch](https://github.com/TheGreatCodeholio/icad_dispatch) by TheGreatCodeholio, whose
`icad-tone-detection` library does the actual listening.

---

## The big picture

```
 scanner software                     ECRXN Dispatch                                  people
 (RDIO Scanner,      upload    ┌──────────────────────────────────────────┐   alerts
  SDRTrunk, Trunk  ──────────▶ │ 1 check key  2 find tones  3 match       │ ───────▶ Telegram, Discord,
  Recorder…)        one call   │ 4 save  5 transcribe  6 address/type     │          Pushover, email,
                    per upload │ 7 send alerts                            │          Facebook, Make, n8n
                               └──────────────────────────────────────────┘
                                         ▲            │
                                 you, in a browser    ▼
                                 (the dashboard)   database + audio files
```

There are three moving parts:

- **The upload address** (`/api/call-upload`), where scanner software sends each call as soon as it's recorded.
- **The dashboard**, the website you use to set things up and review calls.
- **The senders**, one per alert channel, which turn a call into a Telegram message, a Discord post, a Facebook
  video and so on.

Everything runs in one program on one computer, with one database file. There's nothing else to install or keep
running.

---

## What happens to a call

Each upload is handled from start to finish while the uploader waits for the answer, usually in a second or two
(longer with transcription).

**1. Check who's sending it.** The upload carries a **System ID** and an **API key**. Each radio system has its own
key, so a leaked key only affects one system, and it can be replaced on the system's General tab. Wrong or missing
values get a clear error back (401, 403, 404) so you can fix the uploader.

**2. Find the tones.** The audio is converted with ffmpeg and handed to the `icad-tone-detection` library with
the system's **Tones** settings (how long each tone must last, how close a pitch must be, and so on). It returns
every tone it heard: two-tone pages, long tones, hi-low (alternating) tones, pulsed tones, MDC IDs and DTMF digits,
each with its pitches, lengths and position in the call.

**3. Join split pages.** Some systems record the tones and the voice as two separate calls. With **Split Dispatch**
on, a clip that is only tones is held for a few seconds (the uploader gets a 202), and when the voice clip
arrives on the same talkgroup the two are joined into one call. See [Uploads](docs/uploads.md#split-uploads-tones-first-voice-after).

**4. Match triggers.** A **trigger** is "this department": a name, the tones it's paged with, and optionally the
one talkgroup it's paged on. Each heard tone is compared with each trigger's tones, allowing a small tolerance
(2 % by default) because real radios are never exact. A trigger with several tone rules can fire when **any** rule
matches (OR) or only when **all** do (AND). After a trigger fires it ignores repeats for a while (its *ignore
time*), so a page repeated three times sends one alert, not three.

**5. Decide whether to keep the call.** A call is saved if a trigger fired, or if **Tone Finder** is on and any
tones were heard. Calls without tones aren't kept, which keeps the database small and the dashboard useful.

**6. Transcribe (optional).** The tones are cut out (they confuse speech recognition) and the voice is sent to
OpenAI or your own speech-to-text server. The text comes back with timings, which are mapped back onto the
original audio so the dashboard can highlight each word as it plays.

**7. Store the audio.** The MP3 is saved where the system's **File Storage** says: in `static/audio/` on this
computer (optionally copied to a second folder or drive), on S3-compatible storage, or on another server over
SFTP. The file's web address becomes `{audio_url}` in alerts.

**8. Find the address and incident type (optional).** An AI model reads the transcript, picks out the address
(then Google Maps places it) and labels the call, for example *Fire / Structure Fire*.

**9. Send the alerts.** Two kinds go out:

- The **system alert** on each of the system's switched-on channels, naming every trigger that fired and is
  included in that channel. New triggers are included only in the system's Pushover alert; you choose the rest on
  each trigger's Notifiers tab.
- Each fired trigger's **own alerts**, to its own channel, group, address or Page.

Each message is built from a template with **placeholders** like `{trigger_list}`, `{timestamp_readable}` and
`{address}` filled in for this call ([full list](docs/alerts.md#placeholders)). Then the sender for that channel
delivers it: with the audio as a link, as an attached file, as a Telegram voice message, or, for Facebook, as a
video of the audio over a background picture (vertical Reel for calls up to 90 seconds). If a channel fails (a
wrong token, say), the error goes to the log and the other channels still go out.

**10. Answer the uploader** with what happened: saved, joined, and which triggers fired.

---

## The dashboard

- **Dashboard**: **Tone hits** lists every saved call with its tones, a player and the transcript. **Tones
  without a trigger** lists the tones heard that no trigger covers yet, grouped (the same page heard five times
  shows once), with the talkgroup and a button to make a trigger from it. This is how you build your trigger list:
  let it run, then add the departments as they're paged.
- **Radio Systems**: one per radio system you receive. Each has tabs for uploads, storage, tone settings,
  **Export** (the whole system as one file), every alert channel and the AI add-ons. **Import** next to **Add
  System** creates a system from an export file.
- **Triggers**: the departments. Each has its tone rules and a **Notifiers** tab for its own alerts. **Export /
  import** gives you the tones as a spreadsheet, or adds many triggers from one.

The pages are plain HTML, CSS and JavaScript with Bootstrap. Everything (fonts, icons, scripts) is served by
ECRXN Dispatch itself, so the dashboard works on a network with no internet. It adapts to phones.

---

## Where things are kept

| What | Where | Notes |
|---|---|---|
| Settings | `.env` | Port, address, timezone, first admin login. Written by the installer |
| Everything you set up, and call history | `var/icad_dispatch.db` | One SQLite database file |
| Call audio | `static/audio/` (or S3 / SFTP) | In date folders |
| Facebook backgrounds | `var/facebook_media/` | Already shrunk when uploaded |
| Logins in progress | `var/sessions/` | |
| Logs | `log/` | A new file each day |

None of these are in the download, which is why updating can't overwrite them.

**Database updates.** The `migrations/` folder holds numbered SQL files. On start the program applies any it
hasn't applied yet, in order, and records each one, so an updated version brings its database changes with it
and nobody has to run anything by hand. Changes are written so existing setups keep working the way they did.

---

## Why it's built this way

- **One program, one database file, no Docker.** Most people running this have one PC or a Raspberry Pi next to a
  scanner. SQLite needs no database server, backups are a file copy, and the installers set everything up in
  minutes on Windows or Linux.
- **One setup program on Windows.** Most people run this on a Windows PC, so the release includes a normal
  `Setup.exe` that carries its own Python and ffmpeg: nothing else to install, and updating is running the newer
  one. On Linux and a Pi the same code runs from its folder as a system service.
- **Detection is a separate library.** `icad-tone-detection` is well tested on real radio audio; this project
  uses it as is and builds the matching, alerting and dashboard around it.
- **Tolerances everywhere.** Radio audio drifts, fades and clips, so pitches and lengths are compared with
  margins, and split pages are joined.
- **Two levels of alerts.** A county-wide feed and a station's own channel need different messages and different
  audiences. The system alert covers the first, trigger alerts the second, with shared settings (bot tokens, mail
  server) reused so each trigger only needs what's different.
- **Every message box starts filled in.** A blank template is easy to forget; a working default means alerts are
  useful from the first page.
- **Settings travel as one file.** Exports include everything so a whole system can be rebuilt on a new computer
  in one step.

---

## Security, briefly

- Passwords are stored as bcrypt hashes. Repeated wrong passwords lock out the address (and, past a higher limit,
  the account) for 15 minutes. A forgotten password can only be reset by someone with access to the server itself.
- Every change made in the dashboard needs a per-session token, so another website can't make changes through
  your browser. Pages can't be framed by other sites.
- Uploads need the system's API key, compared in a way that doesn't leak timing.
- Names, messages and imported files are escaped before display.
- For use over the internet, put it behind HTTPS; see [Setup → HTTPS](docs/setup.md#https-and-the-internet).

---

## The demo

The browser demo (hosted on [ecrxn.com](https://ecrxn.com)) is the real dashboard saved as static pages, with a small script (`demo-api.js`)
that answers the dashboard's requests from made-up data instead of a server. Changes stay in that browser tab
and reset after an hour. The pages' Content-Security-Policy only allows the demo's own files, so nothing typed
into it can be sent anywhere. `public/build_demo.py` rebuilds it from the current dashboard after changes, so it
always looks like the real thing.

---

## Releases

Pushing a version tag (for example `v1.2.0`) to GitHub runs `.github/workflows/release.yml`. It checks the code
installs and compiles, builds the Windows setup program on a GitHub Windows machine (`.github/windows-installer/build.ps1`:
the app, the embeddable Python with its packages, and ffmpeg, packed by Inno Setup), and publishes the release
with `ECRXN-Dispatch-Setup-<version>.exe` attached and notes listing the changes. Nobody builds anything by hand.

On Windows the setup installs to `C:\Program Files\ECRXN Dispatch` and runs the app at startup as a background
task, so it works before anyone logs in. A tray icon (`tray.py`) starts, stops and restarts it and edits the main
settings. A newer setup replaces only the program files, so `.env`, `var\`, `log\` and `static\audio\` carry over.

---

## Words used

| Word | Meaning |
|---|---|
| **Two-tone / Quick Call** | Two tones, one after the other (e.g. 433.8 Hz then 1641.7 Hz): the usual fire/EMS page |
| **Long tone** | One steady tone, often an "all call" |
| **Hi-low** | Two tones alternating, like a siren |
| **Pulsed** | One tone switched on and off in a rhythm |
| **DTMF** | Phone-keypad digits |
| **Talkgroup** | A channel on a trunked radio system |
| **Trigger** | A department's tones; when they're heard, the trigger fires and alerts go out |
| **System** | One radio system you receive, with its own API key and settings |
| **Tolerance** | How far off a heard pitch may be and still match |
| **Ignore time** | How long a trigger stays quiet after firing, so repeated pages send one alert |
