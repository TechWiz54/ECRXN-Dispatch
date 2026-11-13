# Setup

Install ECRXN Dispatch, get your first call in, keep it updated. About ten minutes from start to first tone hit.

- [Install](#install) · [First steps](#first-steps) · [Updating](#updating) · [Forgot the password?](#forgot-the-admin-password)
- [Where audio is saved](#where-audio-is-saved) · [HTTPS and the internet](#https-and-the-internet) · [Security](#security)
- [Settings (.env)](#settings-env) · [Troubleshooting](#troubleshooting) · [Uninstall](#uninstall)

---

## Install

Both installers set up everything ECRXN Dispatch needs and write your settings to a `.env` file for you.

### Windows 10 / 11

1. Download **`ECRXN-Dispatch-Setup-<version>.exe`** from the
   [latest release](https://github.com/TechWiz54/ECRXN-Dispatch/releases/latest).
2. Run it. Windows may say *"Windows protected your PC"* because the program isn't signed by a paid
   certificate: click **More info → Run anyway**.
3. Pick the port (default `9911`), admin username, password (a random one is filled in; write it down) and timezone.
   Leave **Let other devices on the network open the dashboard** ticked if you'll use it from other devices.
4. Finish. ECRXN Dispatch is now running in the background and starts with Windows. The last page shows the
   dashboard address and your login.

Everything it needs comes inside the setup program (its own Python and ffmpeg), so nothing else gets installed.
It goes to `C:\Program Files\ECRXN Dispatch`.

**The tray icon.** While you're logged in, the ECRXN Dispatch icon sits next to the clock (click the **^** arrow
if it's hidden; drag it onto the taskbar to keep it in view). Double-click it to open the dashboard; right-click
it for:

| Menu | |
|---|---|
| Open dashboard | Opens it in your browser |
| Running on port 9911 / Stopped | Whether it's running right now |
| Restart, Stop / Start | Shows *Starting…* / *Stopping…* until it has really happened, and a notice if it fails |
| Settings… | Port, the address used in alert links, timezone and log detail. **Save and restart** applies them (changing the port also moves the firewall rule, so Windows asks for admin rights then) |
| Open the logs folder, Help | |
| Hide this icon | Hides the icon only; ECRXN Dispatch keeps running. It's back at the next login, or from the Start menu |

ECRXN Dispatch itself runs at boot even when nobody is logged in; the icon is only the remote control. The
**Start menu → ECRXN Dispatch** folder has the dashboard, the settings window, the logs, *Reset the admin password*
and *Uninstall*.

> **Used the old `install_windows.bat` before?** Run the setup program, then copy `.env`, the `var` folder and
> `static\audio` from your old folder into `C:\Program Files\ECRXN Dispatch` (replace what's there) and use
> **Restart** (tray icon). The old "iCAD Dispatch" startup task and firewall rule are removed for you.

### Linux

```bash
git clone https://github.com/TechWiz54/ECRXN-Dispatch.git
cd ECRXN-Dispatch
sudo ./install_linux.sh
```

It installs Python, ffmpeg and build tools with your package manager, creates an `icad_dispatch` service account,
copies the app to `/opt/icad_dispatch`, writes `.env`, starts the `icad_dispatch` systemd service, and opens the
port in `ufw` / `firewalld` if one is active. Works on Debian 12+, Ubuntu 22.04+, Raspberry Pi OS Bookworm+,
Fedora 38+ (ffmpeg from [RPM Fusion](https://rpmfusion.org)), Arch and openSUSE.

```bash
systemctl status icad_dispatch          # running?
sudo systemctl restart icad_dispatch    # after editing /opt/icad_dispatch/.env
journalctl -u icad_dispatch -f          # live logs
```

Options: `--dir PATH`, `--port N`, `--user NAME`, `--no-service`, `--unattended`.

> The service user can't write to `/home` or system folders. To copy audio to another drive, use a folder under
> `/mnt`, `/media`, `/srv` or `/opt` and run `sudo chown icad_dispatch:icad_dispatch /mnt/usb/audio`.

### Without an installer (any OS)

For development, or a system without an installer. Install Python 3.10+ and ffmpeg, then:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt      # Windows: .venv\Scripts\pip
cp .env.example .env                           # then edit it
.venv/bin/python serve.py                      # Windows: .venv\Scripts\python serve.py
```

---

## First steps

**1. Log in.** Open `http://<server>:9911` and sign in with the admin login the installer printed. Then change
the password (**your name, top right → Change Password**). Until you do, a yellow banner reminds you. Lost the
login? It's in `.env`: see [Forgot the admin password?](#forgot-the-admin-password).

**2. Add a radio system.** **Radio Systems → Add System**:

| Field | What to enter |
|---|---|
| System ID | A number your uploader also sends, e.g. `6643` (RDIO Scanner users: its system ID) |
| System Name | e.g. `County Fire` |
| Stream URL | Optional live-listen link (Broadcastify, Icecast…), available as `{stream_url}` in alerts |

Open the system's **General** tab and copy its **API Key**.

**3. Turn on Tone Finder.** On the system's **Tones** tab set **Tone Finder** to **Enabled** and save. Calls are
kept when Tone Finder is on and tones were heard, or when a trigger fires. Leave the other tone settings at their
defaults to start.

**4. Point your uploader here.** Every uploader needs three things:

| Setting | Value |
|---|---|
| URL | `http://<server>:9911/api/call-upload` |
| System ID | from step 2 |
| API key | from step 2 |

RDIO Scanner: add a *Downstream* with those values. SDRTrunk, Trunk Recorder and others: use their
RDIO-compatible uploader. To test by hand, see [Uploads](uploads.md#examples).

**5. Watch calls arrive.** The **Dashboard** lists every call with tones (**Tone hits**) and refreshes every
15 seconds. Switch to **Tones without a trigger** to see each tone heard that no trigger covers yet: how often,
when and on which talkgroup, in pages you can sort and search. **Add trigger** turns one into a trigger (or adds
it to an existing one), and it drops off the list.

**6. Set up alerts.** See [Alerts](alerts.md). Each system has its own alert settings, and each trigger can also
send its own alert to a different channel, group or Page.

---

## Updating

- **Windows:** download the new `ECRXN-Dispatch-Setup-<version>.exe` from the
  [Releases page](https://github.com/TechWiz54/ECRXN-Dispatch/releases) and run it. It stops ECRXN Dispatch,
  replaces the program and starts it again, without asking anything.
- **Linux:** `git pull` in the folder you installed from, then `sudo ./install_linux.sh` again.

**Nothing of yours is replaced.** An update only replaces the program's own files. These are yours and are never
in the download, so they can't be overwritten:

| Yours | What it is |
|---|---|
| `.env` | Your settings and admin login (the installer sees it's there and keeps it) |
| `var/` | The database (systems, triggers, calls), Facebook backgrounds, login sessions |
| `static/audio/` | Saved call audio (only an empty placeholder file of that folder is in the download) |
| `log/` | Logs |

When the new version starts, it updates the database by itself (it records which updates it has applied, so
each runs once). For extra peace of mind, download each system first: open it on **Radio Systems → Export**.

---

## Forgot the admin password?

**What's the default login?** There isn't a shared one, so nobody can guess it. The username is `admin` unless
you typed another. The password is the one the installer filled in (or you typed) and showed on its last page.
It's saved in the settings file:

- **Windows:** open `C:\Program Files\ECRXN Dispatch\.env` in Notepad.
- **Linux:** `sudo cat /opt/icad_dispatch/.env`.

Look for the `ROOT_USERNAME=` and `ROOT_PASSWORD=` lines. (Running it yourself from `.env.example`, it's
`admin` / `changeme123` until you change it.) If you changed the password in the dashboard later, that file still
shows the first one; reset it instead:

You need access to the server itself, which is what keeps this safe:

- **Edit `.env`**: add `RESET_ADMIN_PASSWORD=your-new-password` and restart. The password is changed and the
  line is removed from `.env` again.
- **Or,** on Windows, right-click **Start menu → ECRXN Dispatch → Reset the admin password → Run as
  administrator**. On Linux: `sudo -u icad_dispatch /opt/icad_dispatch/.venv/bin/python /opt/icad_dispatch/serve.py --reset-password`.
  It asks for the new password twice; add a username at the end to reset someone else.

Either way, "Remember me" logins on other devices are signed out. `ROOT_USERNAME` / `ROOT_PASSWORD` in `.env`
only create the admin on the very first start; changing them later does nothing.

---

## Where audio is saved

Each system's **File Storage** tab decides where call audio goes:

- **Local** (default): MP3s in `static/audio/`, in date folders (`%Y/%m/%d` → `2026/11/12`). Alerts link to them.
  **Also save a copy to** copies every call to a second folder, such as an external drive (`E:\ScannerAudio`).
  If that folder is unavailable, the call is still saved normally.
- **SFTP** or **S3**: each file is uploaded to another server or object storage instead.

---

## HTTPS and the internet

Before opening ECRXN Dispatch to the internet, put it behind a reverse proxy such as Caddy or nginx that handles
HTTPS, then set in `.env`:

```env
BASE_URL=https://dispatch.example.com
SESSION_COOKIE_SECURE=True
SESSION_COOKIE_DOMAIN=dispatch.example.com
```

The app trusts the standard `X-Forwarded-*` headers from one proxy in front of it.

---

## Security

- **Passwords** are stored as bcrypt hashes; new ones need at least 8 characters.
- **Logins:** 8 wrong passwords from one address lock that address out for 15 minutes, and 32 on one account lock
  the account (`LOGIN_MAX_ATTEMPTS`, `LOGIN_LOCKOUT_MINUTES`). You get a fresh session on every login.
- **Forms** are protected against cross-site requests, and pages send headers that stop other sites framing them.
- **Upload API keys** are per system and checked in constant time. Regenerate one on **Radio Systems → General** if
  it leaks.
- **Exports** are a full copy, including tokens, passwords and webhook URLs. Keep the files private.
- Alert text, names and imported files are escaped before they're shown, so a trigger name can't run code.

Found a security problem? Please report it privately to the maintainers rather than in a public issue.

---

## Settings (.env)

The installer writes `.env`; [`.env.example`](../.env.example) lists everything. Restart after changes. On Windows,
the tray icon's **Settings…** changes the port, alert link address, timezone and log detail for you.

| Setting | What it does |
|---|---|
| `HOST` / `PORT` | Where it listens (default `0.0.0.0:9911`) |
| `BASE_URL` | The address used in alert links, e.g. `http://192.168.1.50:9911` |
| `TIMEZONE` | Times in alerts, e.g. `America/New_York` |
| `ROOT_USERNAME` / `ROOT_PASSWORD` | Admin account created on the first start only |
| `RESET_ADMIN_PASSWORD` | Set a new admin password on the next start (then removed) |
| `LOG_LEVEL` | 1 = debug … 5 = critical |
| `SESSION_COOKIE_SECURE` / `SESSION_COOKIE_DOMAIN` | For HTTPS, see above |
| `LOGIN_MAX_ATTEMPTS` / `LOGIN_LOCKOUT_MINUTES` | Login lockout (8 / 15) |
| `MAX_UPLOAD_MB` | Largest upload the web server accepts (default 2100, for 2 GB Facebook clips) |
| `FACEBOOK_MAX_IMAGE_MB` / `FACEBOOK_MAX_CLIP_MB` | Facebook background limits (250 / 2048) |
| `FACEBOOK_GRAPH_VERSION` | Facebook API version (default `v26.0`) |
| `OPENAI_API_KEY` | Shared key for transcription / AI features when a system has none |
| `WEB_THREADS`, `WEB_CONCURRENCY`, `WEB_TIMEOUT` | Web server tuning |

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Uploader gets `missing_token` (401) | It isn't sending the API key |
| `missing_system_id` (400) / `system_not_found` (404) | The System ID is missing or doesn't match a system |
| `invalid_token` (403) | The API key belongs to a different system |
| 200 but nothing on the Dashboard | Tone Finder is off, or there were no tones |
| Calls fail or no audio is saved | Check `log/icad_dispatch.log`. On Linux, ffmpeg may be missing: re-run the installer |
| Other devices can't open the dashboard | Run the setup again with the firewall option ticked (Linux: open the port) |
| Alert links point to `localhost` | Set `BASE_URL` in `.env` to an address others can reach |

---

## Uninstall

**Windows:** **Settings → Apps → ECRXN Dispatch → Uninstall** (or the Start menu shortcut). It stops ECRXN Dispatch
and removes its startup task and firewall rule. Your data (`.env`, `var`, `log`, `static\audio`) stays in
`C:\Program Files\ECRXN Dispatch`; delete that folder too if you don't want to keep it.

**Linux:**

```bash
sudo systemctl disable --now icad_dispatch
sudo rm /etc/systemd/system/icad_dispatch.service
sudo rm -rf /opt/icad_dispatch          # deletes the database and audio too
sudo userdel icad_dispatch
```
