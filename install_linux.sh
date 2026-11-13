#!/usr/bin/env bash
# ECRXN Dispatch - native Linux installer (no Docker).
#
#   sudo ./install_linux.sh                 # interactive install to /opt/icad_dispatch
#   sudo ./install_linux.sh --unattended    # accept all defaults
#
# Options:
#   --dir PATH        install location            (default /opt/icad_dispatch)
#   --port N          port to listen on           (default 9911)
#   --user NAME       service account             (default icad_dispatch, uid/gid 9911 like the Docker image)
#   --no-service      don't install/start the systemd service
#   --unattended      don't ask questions
#
# Supports apt (Debian/Ubuntu/Raspberry Pi OS/Mint), dnf (Fedora/RHEL/Rocky/Alma),
# pacman (Arch/Manjaro) and zypper (openSUSE).
#
# Safe to re-run for upgrades: .env, var/ (database), log/ and static/audio/ are kept.

set -euo pipefail

INSTALL_DIR=/opt/icad_dispatch
PORT=9911
SVC_USER=icad_dispatch
SVC_UID=9911
WITH_SERVICE=1
UNATTENDED=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir) INSTALL_DIR="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --user) SVC_USER="$2"; shift 2 ;;
    --no-service) WITH_SERVICE=0; shift ;;
    --unattended|-y) UNATTENDED=1; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$(realpath -m "$INSTALL_DIR")"

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '    \033[32m%s\033[0m\n' "$*"; }
warn() { printf '    \033[33m%s\033[0m\n' "$*"; }
die()  { printf '\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

ask() {  # ask "prompt" "default" -> echoes answer
  local prompt="$1" def="$2" ans
  if [[ $UNATTENDED -eq 1 || ! -t 0 ]]; then echo "$def"; return; fi
  read -r -p "$prompt [$def]: " ans </dev/tty || true
  echo "${ans:-$def}"
}

[[ $EUID -eq 0 ]] || die "Run this with sudo:  sudo $0 $*"

echo "ECRXN Dispatch - Linux installer"
echo "Source:  $SRC_DIR"
echo "Install: $INSTALL_DIR"

# ───────────────────────── System packages ─────────────────────────
step "Installing system packages"
if command -v apt-get >/dev/null; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -q
  apt-get install -y -q python3 python3-venv python3-pip python3-dev ffmpeg \
      build-essential pkg-config rsync ca-certificates tzdata curl
  apt-get install -y -q libopenblas0 2>/dev/null || apt-get install -y -q libopenblas-base 2>/dev/null || true
elif command -v dnf >/dev/null; then
  dnf install -y python3 python3-pip python3-devel gcc gcc-c++ make pkgconf rsync tzdata openblas curl
  dnf install -y ffmpeg 2>/dev/null || dnf install -y ffmpeg-free 2>/dev/null \
    || warn "ffmpeg not available - enable RPM Fusion (https://rpmfusion.org) then: dnf install ffmpeg"
elif command -v pacman >/dev/null; then
  pacman -Sy --noconfirm --needed python python-pip ffmpeg base-devel rsync tzdata openblas curl
elif command -v zypper >/dev/null; then
  zypper --non-interactive install python3 python3-pip python3-devel gcc gcc-c++ make rsync timezone ffmpeg openblas curl \
    || zypper --non-interactive install python3 python3-pip python3-devel gcc gcc-c++ make rsync timezone ffmpeg-7 curl
else
  warn "Unknown package manager - make sure python3 (3.10+), python3-venv, ffmpeg and a C compiler are installed."
fi
command -v ffmpeg >/dev/null && ok "ffmpeg: $(command -v ffmpeg)" || warn "ffmpeg NOT found - audio processing will fail until it is installed"

# ───────────────────────── Python 3.10+ ─────────────────────────
step "Finding Python 3.10+"
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
    PY="$(command -v "$c")"; break
  fi
done
[[ -n "$PY" ]] || die "Python 3.10 or newer is required (found: $(python3 --version 2>&1 || echo none)).
  Debian 11 / Ubuntu 20.04 are too old - upgrade the OS, or install a newer Python (e.g. 'apt install python3.11 python3.11-venv' from the deadsnakes PPA) and re-run."
ok "Using $("$PY" --version) ($PY)"

# ───────────────────────── Service user ─────────────────────────
step "Creating service account '$SVC_USER'"
if ! getent group "$SVC_USER" >/dev/null; then
  if getent group "$SVC_UID" >/dev/null; then groupadd --system "$SVC_USER"; else groupadd --system -g "$SVC_UID" "$SVC_USER"; fi
fi
if ! id "$SVC_USER" >/dev/null 2>&1; then
  NOLOGIN="$(command -v nologin || echo /usr/sbin/nologin)"
  if getent passwd "$SVC_UID" >/dev/null; then
    useradd --system -M -d "$INSTALL_DIR" -s "$NOLOGIN" -g "$SVC_USER" "$SVC_USER"
  else
    useradd --system -M -d "$INSTALL_DIR" -s "$NOLOGIN" -u "$SVC_UID" -g "$SVC_USER" "$SVC_USER"
  fi
fi
if [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != "root" ]]; then
  usermod -aG "$SVC_USER" "$SUDO_USER" && ok "Added $SUDO_USER to group $SVC_USER (log out/in to take effect)"
fi
ok "$(id "$SVC_USER")"

# ───────────────────────── Copy files ─────────────────────────
step "Copying application files"
mkdir -p "$INSTALL_DIR"
if [[ "$SRC_DIR" != "$INSTALL_DIR" ]]; then
  rsync -a --delete \
    --exclude '.git/' --exclude '.venv/' --exclude 'var/' --exclude 'log/' --exclude '/static/audio/' \
    --exclude '.env' --exclude 'bin/' --exclude '__pycache__/' --exclude '*.bat' --exclude '*.ps1' \
    "$SRC_DIR"/ "$INSTALL_DIR"/
  ok "Copied to $INSTALL_DIR"
else
  ok "Installing in place"
fi
mkdir -p "$INSTALL_DIR"/{log,var,static/audio}

# ───────────────────────── Virtual env ─────────────────────────
step "Creating virtual environment and installing Python packages (can take a few minutes)"
if [[ -x "$INSTALL_DIR/.venv/bin/python" ]] && ! "$INSTALL_DIR/.venv/bin/python" -c 'import sys' 2>/dev/null; then
  rm -rf "$INSTALL_DIR/.venv"   # broken venv (e.g. Python was upgraded)
fi
[[ -x "$INSTALL_DIR/.venv/bin/python" ]] || "$PY" -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/python" -m pip install --upgrade pip --disable-pip-version-check -q
"$INSTALL_DIR/.venv/bin/python" -m pip install -r "$INSTALL_DIR/requirements.txt" --disable-pip-version-check -q
ok "Packages installed"

# ───────────────────────── .env ─────────────────────────
ENV_FILE="$INSTALL_DIR/.env"
CREATED_ENV=0
if [[ -f "$ENV_FILE" ]]; then
  step "Keeping existing .env"
  PORT="$(grep -E '^PORT=' "$ENV_FILE" | head -1 | cut -d= -f2 || true)"; PORT="${PORT:-9911}"
else
  step "Creating .env"
  LAN_IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')"
  [[ -n "$LAN_IP" ]] || LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  [[ -n "$LAN_IP" ]] || LAN_IP=localhost
  SYS_TZ="$(timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null || echo America/New_York)"
  [[ -n "$SYS_TZ" && "$SYS_TZ" != "Etc/UTC" ]] || SYS_TZ=America/New_York

  PORT="$(ask 'Port to listen on' "$PORT")"
  BASE_URL="$(ask 'Base URL people will use to reach this server' "http://$LAN_IP:$PORT")"
  TZ_NAME="$(ask 'Timezone (IANA name)' "$SYS_TZ")"
  ADMIN_USER="$(ask 'Admin username' admin)"
  ADMIN_PASS="$(ask 'Admin password (Enter = random)' "$("$INSTALL_DIR/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(12))')")"

  COOKIE_HOST="$(echo "$BASE_URL" | sed -E 's#^[a-zA-Z]+://##; s#[:/].*$##')"
  [[ "$BASE_URL" == https://* ]] && SECURE=True || SECURE=False

  cat > "$ENV_FILE" <<EOF
# --------------- Logging ---------------
# 1=DEBUG 2=INFO 3=WARNING 4=ERROR 5=CRITICAL
LOG_LEVEL=2

# --------------- Timezone IANA ---------------
TIMEZONE=$TZ_NAME

# --------------- Web server ---------------
BASE_URL=$BASE_URL
HOST=0.0.0.0
PORT=$PORT
WEB_CONCURRENCY=1
WEB_THREADS=8
WEB_TIMEOUT=60

# --------------- Cookies ---------------
SESSION_COOKIE_SECURE=$SECURE
SESSION_COOKIE_DOMAIN=$COOKIE_HOST
SESSION_COOKIE_NAME=icad_dispatch
SESSION_COOKIE_PATH=/

# --------------- SQLite ---------------
SQLITE_DATABASE_PATH=var/icad_dispatch.db

# --------------- Root User Bootstrap (first start only) ---------------
ROOT_USERNAME=$ADMIN_USER
ROOT_PASSWORD=$ADMIN_PASS
EOF
  CREATED_ENV=1
  ok ".env written"
fi

# ───────────────────────── Permissions ─────────────────────────
step "Setting permissions"
chown -R "$SVC_USER:$SVC_USER" "$INSTALL_DIR"
chmod 750 "$INSTALL_DIR"
chmod 640 "$ENV_FILE"
chmod -R g+rwX "$INSTALL_DIR"/{log,var,static/audio}
ok "Owned by $SVC_USER"

# ───────────────────────── systemd ─────────────────────────
if [[ $WITH_SERVICE -eq 1 ]]; then
  if command -v systemctl >/dev/null && [[ -d /run/systemd/system ]]; then
    step "Installing systemd service icad_dispatch.service"
    cat > /etc/systemd/system/icad_dispatch.service <<EOF
[Unit]
Description=ECRXN Dispatch (tone detection and alerting)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SVC_USER
Group=$SVC_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/.venv/bin/python $INSTALL_DIR/serve.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
# Hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=$INSTALL_DIR

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable icad_dispatch.service >/dev/null
    systemctl restart icad_dispatch.service
    sleep 3
    if systemctl is-active --quiet icad_dispatch.service; then
      ok "Service is running"
    else
      warn "Service failed to start - check: journalctl -u icad_dispatch -n 50"
    fi
  else
    warn "systemd not available - start manually with: sudo -u $SVC_USER $INSTALL_DIR/.venv/bin/python $INSTALL_DIR/serve.py"
  fi
fi

# ───────────────────────── Firewall ─────────────────────────
if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw allow "$PORT"/tcp >/dev/null && ok "ufw: opened $PORT/tcp"
elif command -v firewall-cmd >/dev/null && firewall-cmd --state >/dev/null 2>&1; then
  firewall-cmd --permanent --add-port="$PORT"/tcp >/dev/null && firewall-cmd --reload >/dev/null && ok "firewalld: opened $PORT/tcp"
fi

# ───────────────────────── Done ─────────────────────────
URL="$(grep -E '^BASE_URL=' "$ENV_FILE" | cut -d= -f2-)"
echo
printf '\033[1;32m============================================================\033[0m\n'
echo " ECRXN Dispatch is installed in $INSTALL_DIR"
echo "   Open:     ${URL:-http://localhost:$PORT}"
if [[ $CREATED_ENV -eq 1 ]]; then
  printf '   Login:    \033[33m%s / %s\033[0m  (change it after first login)\n' "$ADMIN_USER" "$ADMIN_PASS"
fi
echo "   Settings: $ENV_FILE"
echo "   Status:   systemctl status icad_dispatch"
echo "   Logs:     journalctl -u icad_dispatch -f    (or $INSTALL_DIR/log/)"
echo "   Restart:  sudo systemctl restart icad_dispatch"
echo "   Upgrade:  pull new code, then re-run: sudo ./install_linux.sh"
printf '\033[1;32m============================================================\033[0m\n'
