#!/bin/sh
# Starts ECRXN Dispatch in the container: fixes folder ownership (bind mounts are often owned by root),
# makes a random admin password on the very first start if none is set, then runs as the icad_dispatch user.
set -e
cd /app

if [ "$(id -u)" = "0" ]; then
    mkdir -p var log static/audio
    chown -R icad_dispatch:icad_dispatch var log static/audio
fi

db="${SQLITE_DATABASE_PATH:-var/icad_dispatch.db}"
if [ ! -s "$db" ] && [ -z "$ROOT_PASSWORD" ] && [ -z "$ROOT_PASSWORD_FILE" ]; then
    ROOT_PASSWORD="$(python -c 'import secrets; print(secrets.token_urlsafe(12))')"
    export ROOT_PASSWORD
    echo "=================================================================="
    echo " ECRXN Dispatch first start - your admin login:"
    echo "   Username: ${ROOT_USERNAME:-admin}"
    echo "   Password: $ROOT_PASSWORD"
    echo " Write it down. It's only shown this once (change it in the dashboard)."
    echo "=================================================================="
fi

if [ "$(id -u)" = "0" ]; then
    exec setpriv --reuid=icad_dispatch --regid=icad_dispatch --init-groups "$@"
fi
exec "$@"
