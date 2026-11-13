# lib/alert_audio.py
"""
Fetch a call's audio so an alert can send it as a file (email attachment, Make / n8n upload, ...).

Audio saved by this server is read straight from static/audio (no HTTP round trip, and it works
even when BASE_URL points somewhere the server itself can't reach). Anything else is downloaded,
up to a size limit.
"""
from __future__ import annotations

import logging
import mimetypes
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import unquote, urlparse

import requests

module_logger = logging.getLogger("icad_dispatch.alert_audio")

AUDIO_ROOT = Path(__file__).resolve().parent.parent / "static" / "audio"
MAX_ATTACH_BYTES = int(os.getenv("ALERT_MAX_ATTACH_BYTES", str(25 * 1024 * 1024)))
TIMEOUT_S = int(os.getenv("ALERT_MEDIA_TIMEOUT_S", "20"))

Audio = Tuple[str, bytes, str]      # (filename, data, content_type)


def _local_file(url: str) -> Optional[Path]:
    """static/audio/... on this server -> its path on disk (never anything outside that folder)."""
    path = unquote(urlparse(url).path or "")
    marker = "/static/audio/"
    if marker not in path:
        return None
    rel = path.split(marker, 1)[1]
    p = (AUDIO_ROOT / rel).resolve()
    try:
        p.relative_to(AUDIO_ROOT.resolve())
    except ValueError:
        return None
    return p if p.is_file() else None


def fetch_audio(ctx: Dict[str, Any], *, max_bytes: int = MAX_ATTACH_BYTES,
                log: logging.Logger = module_logger) -> Optional[Audio]:
    """The call audio from ctx["audio_url"], or None (no URL, too big, or unreachable)."""
    url = str((ctx or {}).get("audio_url") or "").strip()
    if not url:
        return None
    name = Path(unquote(urlparse(url).path or "")).name or "dispatch_audio.mp3"
    ctype = mimetypes.guess_type(name)[0] or "audio/mpeg"

    local = _local_file(url)
    if local:
        size = local.stat().st_size
        if size > max_bytes:
            log.warning("Audio %s is too big to attach (%d MB)", name, size // (1024 * 1024))
            return None
        return name, local.read_bytes(), ctype

    try:
        with requests.get(url, stream=True, timeout=TIMEOUT_S) as r:
            r.raise_for_status()
            buf = bytearray()
            for chunk in r.iter_content(chunk_size=64 * 1024):
                buf.extend(chunk)
                if len(buf) > max_bytes:
                    log.warning("Audio %s is too big to attach (over %d MB)", name, max_bytes // (1024 * 1024))
                    return None
            ct = (r.headers.get("Content-Type") or "").split(";")[0].strip()
            return name, bytes(buf), (ct if ct.startswith("audio/") else ctype)
    except Exception as e:
        log.warning("Couldn't fetch the audio to attach (%s): %s", url, e)
        return None
