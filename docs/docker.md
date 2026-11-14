# Docker and Portainer

ECRXN Dispatch is on Docker Hub as **[`pbradford15/ecrxn-dispatch`](https://hub.docker.com/r/pbradford15/ecrxn-dispatch)**,
for normal PCs and servers (amd64) and the Raspberry Pi 4 / 5 (arm64, 64-bit OS). It has ffmpeg and everything
else built in. A new image is published with every release.

- [Portainer](#portainer) · [Docker Compose](#docker-compose) · [docker run](#docker-run) · [The admin login](#the-admin-login)
- [Settings](#settings) · [Your data](#your-data) · [Updating](#updating) · [Forgot the password?](#forgot-the-password)

---

## Portainer

1. In Portainer, open your environment → **Stacks → Add stack**. Name it `ecrxn-dispatch`.
2. Choose **Web editor** and paste this:

   ```yaml
   services:
     ecrxn-dispatch:
       image: pbradford15/ecrxn-dispatch:latest
       container_name: ecrxn-dispatch
       restart: unless-stopped
       ports:
         - "9911:9911"
       environment:
         BASE_URL: "http://192.168.1.50:9911"
         TIMEZONE: "America/New_York"
         ROOT_USERNAME: "admin"
       volumes:
         - ecrxn-data:/app/var
         - ecrxn-logs:/app/log
         - ecrxn-audio:/app/static/audio

   volumes:
     ecrxn-data:
     ecrxn-logs:
     ecrxn-audio:
   ```

3. Change **`BASE_URL`** to the address people will use to reach it: your server's IP (or name) and the port,
   with `http://`. Alert links to the call audio are built from it, so it must work from outside the server.
   Change **`TIMEZONE`** if you're not on US Eastern ([list of names](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)).
4. Click **Deploy the stack**.
5. Open **Containers → ecrxn-dispatch → Logs**. On the first start the admin username and password are printed
   in a box. Write them down (see [The admin login](#the-admin-login)).
6. Open `BASE_URL` in your browser, log in, and carry on with **[Setup → First steps](setup.md#first-steps)**.

To change a setting later: **Stacks → ecrxn-dispatch → Editor**, edit, and **Update the stack**.

---

## Docker Compose

The repository has a ready [`docker-compose.yml`](../docker-compose.yml). Download it, edit `BASE_URL` (and
`TIMEZONE`), then:

```bash
docker compose up -d
docker compose logs ecrxn-dispatch        # shows the admin login on the first start
```

---

## docker run

```bash
docker run -d --name ecrxn-dispatch --restart unless-stopped -p 9911:9911 \
  -e BASE_URL=http://192.168.1.50:9911 -e TIMEZONE=America/New_York \
  -v ecrxn-data:/app/var -v ecrxn-logs:/app/log -v ecrxn-audio:/app/static/audio \
  pbradford15/ecrxn-dispatch:latest

docker logs ecrxn-dispatch                # shows the admin login on the first start
```

---

## The admin login

The username is `ROOT_USERNAME` (`admin` unless you change it). For the password, either:

- **Leave `ROOT_PASSWORD` out** (recommended). A random password is made on the first start and printed in the
  container's log, once. Every install gets a different one.
- **Or set `ROOT_PASSWORD`** before the first start to choose it yourself (8+ characters). Remove it from the
  stack afterwards if you like; it isn't needed again.

Both are only used the very first time, when the database is created. After that, change the password in the
dashboard (**your name, top right → Change Password**). Changing `ROOT_PASSWORD` later does nothing.

---

## Settings

Settings are environment variables with the same names as in [`.env.example`](../.env.example) and
[Setup → Settings](setup.md#settings-env). The ones you're most likely to need:

| Variable | Default | What it does |
|---|---|---|
| `BASE_URL` | none | The address people use to reach it, e.g. `http://192.168.1.50:9911`. **Set this.** |
| `TIMEZONE` | `America/New_York` | Time zone for the dashboard and alert times |
| `ROOT_USERNAME` / `ROOT_PASSWORD` | `admin` / random | The first admin login ([above](#the-admin-login)) |
| `PORT` | `9911` | Port inside the container. To use another port outside, change only the left side of `ports` (`"8080:9911"`) and `BASE_URL` |
| `SESSION_COOKIE_SECURE` | `False` | Set `True` when it's behind HTTPS |
| `SESSION_COOKIE_DOMAIN` | from `BASE_URL` | Only if logins don't stick behind a reverse proxy |
| `LOG_LEVEL` | `2` | 1 debug, 2 info, 3 warnings, 4 errors only |
| `OPENAI_API_KEY` | none | Shared OpenAI key for the [AI features](ai-features.md) |
| `WEB_THREADS` / `WEB_TIMEOUT` | `8` / `60` | Web server threads and request timeout (seconds) |

Secrets can also be read from files, Docker-secrets style: `ROOT_PASSWORD_FILE=/run/secrets/ecrxn_admin`.

**HTTPS / reverse proxy.** Put it behind Nginx Proxy Manager, Traefik, Caddy or similar, set `BASE_URL` to the
`https://` address and `SESSION_COOKIE_SECURE` to `True`. Allow large uploads on the proxy (Facebook background
clips can be up to 2 GB). More in [Setup → HTTPS and the internet](setup.md#https-and-the-internet).

---

## Your data

Everything you set up and record lives in three volumes, so the container itself can be deleted and replaced
at any time:

| In the container | Volume | What it is |
|---|---|---|
| `/app/var` | `ecrxn-data` | The database (systems, triggers, calls), Facebook backgrounds, logins |
| `/app/static/audio` | `ecrxn-audio` | Saved call audio |
| `/app/log` | `ecrxn-logs` | Logs, one file a day (the container log has the same) |

You can use folders on the host instead of named volumes, for example `- /srv/ecrxn/var:/app/var`. The container
fixes their permissions itself (it runs as user and group `9911`). To keep audio on another drive, point the
audio volume there, or use the system's **File Storage** tab (S3, SFTP).

**Backup:** stop the container and copy the `ecrxn-data` volume (or folder), or download each system from
**Radio Systems → Export**.

---

## Updating

- **Portainer:** **Stacks → ecrxn-dispatch → Update the stack**, with **Re-pull image and redeploy** turned on.
- **Compose:** `docker compose pull && docker compose up -d`.
- **docker run:** `docker pull pbradford15/ecrxn-dispatch:latest`, then remove the container and run the same
  `docker run` command again. The volumes keep your data.

The database updates itself on the next start. `latest` is always the newest release. To stay on one version,
use its number instead, for example `pbradford15/ecrxn-dispatch:1.3` (newest 1.3.x) or `:1.3.0` (exactly that).

---

## Forgot the password?

Open a shell in the container as its own user and reset it:

```bash
docker exec -it -u icad_dispatch ecrxn-dispatch python serve.py --reset-password
```

In Portainer: **Containers → ecrxn-dispatch → Console**, set **User** to `icad_dispatch`, command `/bin/sh`,
**Connect**, then run `python serve.py --reset-password`. It asks for the new password twice. Restart the
container afterwards.

Don't use `RESET_ADMIN_PASSWORD` with Docker: it stays in the container's settings and would set the password
again on every restart.
