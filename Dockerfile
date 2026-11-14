# ECRXN Dispatch in Docker. Published as pbradford15/ecrxn-dispatch (amd64 and arm64) on each version tag.
# Settings come from environment variables (the same names as .env.example); data lives in three volumes.

FROM python:3.12-slim-bookworm AS build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/requirements.txt
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt

FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 9911 icad_dispatch \
    && useradd -u 9911 -g 9911 -d /app -s /usr/sbin/nologin icad_dispatch

COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY . /app
RUN chmod +x /app/docker-entrypoint.sh \
    && mkdir -p var log static/audio \
    && chown -R icad_dispatch:icad_dispatch var log static/audio

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=9911 \
    LOG_LEVEL=2 \
    TIMEZONE=America/New_York \
    SQLITE_DATABASE_PATH=var/icad_dispatch.db \
    ROOT_USERNAME=admin

EXPOSE 9911
VOLUME ["/app/var", "/app/log", "/app/static/audio"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/login' % os.getenv('PORT','9911'), timeout=4)" || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["python", "serve.py"]
