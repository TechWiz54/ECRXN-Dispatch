# lib/facebook_module.py
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests

from lib.alert_audio import _local_file as _local_audio_file
from lib.dispatch_text_render import expand_template, html_to_text

module_logger = logging.getLogger("icad_dispatch.facebook_module")
_PAGE_TOKENS: Dict[Tuple[str, str], Tuple[str, float]] = {}   # (page id, token hash) -> (page token, good until)

FB_MAX_MESSAGE = 5000
POST_TYPES = ("post", "video")

# Background images / clips for video posts live here (not web-served; read by ffmpeg)
MEDIA_DIR = Path(__file__).resolve().parent.parent / "var" / "facebook_media"
# What can be uploaded (anything ffmpeg can open). Uploads are converted on the way in: pictures to a
# JPG up to 2160 px, clips to a silent H.264 MP4 (shorter side up to 1080 px, first 60 s - it loops).
UPLOAD_IMAGE_EXTS = {".jpg", ".jpeg", ".jfif", ".png", ".webp", ".bmp", ".tif", ".tiff", ".avif", ".heic", ".heif"}
UPLOAD_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".wmv", ".flv", ".mpg", ".mpeg",
                     ".3gp", ".ts", ".mts", ".m2ts", ".ogv", ".gif"}
# Stored files (older versions kept the original format, so those are still recognised)
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".gif"}
MAX_IMAGE_BYTES = int(os.getenv("FACEBOOK_MAX_IMAGE_MB", "250")) * 1024 * 1024
MAX_VIDEO_BYTES = int(os.getenv("FACEBOOK_MAX_CLIP_MB", "2048")) * 1024 * 1024
CLIP_MAX_S = 60

# Calls up to REEL_MAX_S are made vertical (9:16), the shape Facebook shows as a Reel; longer ones are widescreen
REEL_MIN_S, REEL_MAX_S = 3.0, 90.0
SIZE_LANDSCAPE = (1280, 720)
SIZE_VERTICAL = (1080, 1920)


def _graph(video: bool = False) -> str:
    """Graph API base + version. FACEBOOK_GRAPH_VERSION in .env overrides the version when Meta retires one."""
    base = (os.getenv("FACEBOOK_GRAPH_VIDEO_URL", "https://graph-video.facebook.com") if video
            else os.getenv("FACEBOOK_GRAPH_URL", "https://graph.facebook.com"))
    return f"{base.rstrip('/')}/{os.getenv('FACEBOOK_GRAPH_VERSION', 'v26.0')}"


DEFAULT_MESSAGE = "{trigger_list} Alert at {timestamp_24}\n\n{transcript}"


# ─────────────────────────────────────────────────────────────────────────────
# Background media (system- and trigger-level)
# ─────────────────────────────────────────────────────────────────────────────
def media_path(name: Optional[str]) -> Optional[Path]:
    """Absolute path of a stored background, or None if unset / missing."""
    if not name:
        return None
    p = (MEDIA_DIR / Path(str(name)).name)
    return p if p.is_file() else None


def media_kind(name: Optional[str]) -> Optional[str]:
    ext = Path(str(name or "")).suffix.lower()
    return "image" if ext in IMAGE_EXTS else "video" if ext in VIDEO_EXTS else None


def background_info(name: Optional[str]) -> Optional[Dict[str, Any]]:
    """{name, kind ('image'|'video'), version (mtime, for cache-busting)} or None."""
    p = media_path(name)
    return {"name": p.name, "kind": media_kind(p.name), "version": int(p.stat().st_mtime)} if p else None


def save_background(stream, filename: str, prefix: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Store an uploaded picture / clip as <prefix>.jpg or <prefix>.mp4, replacing any earlier one with that prefix.
    The upload is converted (and shrunk) with ffmpeg, which also proves it's a usable picture or video.
    Returns (stored_name, error).
    """
    ext = Path(filename or "").suffix.lower()
    kind = "image" if ext in UPLOAD_IMAGE_EXTS else "video" if ext in UPLOAD_VIDEO_EXTS else None
    if not kind:
        return None, "Use a picture (JPG, PNG, WebP, HEIC, TIFF, ...) or a video clip (MP4, MOV, WebM, AVI, GIF, ...)."
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    limit = MAX_IMAGE_BYTES if kind == "image" else MAX_VIDEO_BYTES
    fd, tmp = tempfile.mkstemp(prefix="upload_", suffix=ext, dir=MEDIA_DIR)
    out = None
    size = 0
    try:
        with os.fdopen(fd, "wb") as fh:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise ValueError(f"That file is too big (limit {limit // (1024 * 1024)} MB for "
                                     f"{'pictures' if kind == 'image' else 'video clips'}).")
                fh.write(chunk)
        if size == 0:
            raise ValueError("The file is empty.")
        if not _has_video_stream(tmp):
            raise ValueError("Couldn't read that file as a picture or video."
                             + (" Try saving it as a JPG first." if ext in (".heic", ".heif", ".avif") else ""))
        if ext == ".gif" and _frame_count(tmp) <= 1:
            kind = "image"          # a still GIF is just a picture
        out, err = _normalize(tmp, kind)
        if err:
            raise ValueError(err)
        remove_background(prefix)
        name = f"{prefix}{Path(out).suffix}"
        os.replace(out, MEDIA_DIR / name)
        return name, None
    except ValueError as e:
        return None, str(e)
    finally:
        for p in (tmp, out):
            if p and os.path.exists(p):
                os.remove(p)


def _frame_count(path: str) -> int:
    probe = _ffprobe()
    if not probe:
        return 2
    p = subprocess.run([probe, "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                        "stream=nb_read_packets", "-of", "csv=p=0", path], capture_output=True, text=True, timeout=60)
    try:
        return int(p.stdout.strip().split(",")[0])
    except ValueError:
        return 2


def _normalize(src: str, kind: str) -> Tuple[Optional[str], Optional[str]]:
    """Convert an upload to the stored form (smaller, and a format ffmpeg reads quickly). Returns (path, error)."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        # Can't convert; keep the original if it's a format we can store as-is
        ext = Path(src).suffix.lower()
        if ext in (IMAGE_EXTS if kind == "image" else VIDEO_EXTS):
            fd, out = tempfile.mkstemp(prefix="bg_", suffix=ext, dir=MEDIA_DIR)
            os.close(fd)
            shutil.copyfile(src, out)
            return out, None
        return None, "ffmpeg isn't installed, so this file type can't be converted."
    suffix = ".jpg" if kind == "image" else ".mp4"
    fd, out = tempfile.mkstemp(prefix="bg_", suffix=suffix, dir=MEDIA_DIR)
    os.close(fd)
    if kind == "image":
        # up to 2160 px on the long side (enough for a 1080x1920 frame), high-quality JPG
        cmd = [ffmpeg, "-y", "-v", "error", "-i", src, "-frames:v", "1",
               "-vf", "scale='min(2160,iw)':'min(2160,ih)':force_original_aspect_ratio=decrease,format=yuvj444p",
               "-q:v", "2", out]
        timeout = 120
    else:
        # silent H.264, shorter side up to 1080 px (even sizes), 30 fps, first CLIP_MAX_S seconds (it loops anyway)
        short = "trunc(min(1080,{d})/2)*2"
        vf = (f"scale='if(lte(iw,ih),{short.format(d='iw')},-2)':'if(lte(iw,ih),-2,{short.format(d='ih')})',"
              "fps=30,format=yuv420p")
        cmd = [ffmpeg, "-y", "-v", "error", "-i", src, "-t", str(CLIP_MAX_S), "-an", "-vf", vf,
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-movflags", "+faststart", out]
        timeout = 900
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        os.remove(out)
        return None, "Converting that file took too long - try a shorter or smaller clip."
    if p.returncode != 0 or not os.path.getsize(out):
        os.remove(out)
        err = p.stderr.decode("utf-8", "ignore").strip().splitlines()
        module_logger.warning("Facebook background conversion failed: %s", " | ".join(err[-3:]))
        return None, "Couldn't convert that file" + (f": {err[-1]}" if err else ".")
    return out, None


def remove_background(prefix: str) -> None:
    if MEDIA_DIR.is_dir():
        for p in MEDIA_DIR.glob(f"{prefix}.*"):
            try:
                p.unlink()
            except OSError:
                pass


def _ffprobe() -> Optional[str]:
    ff = shutil.which("ffprobe")
    if ff:
        return ff
    ffm = shutil.which("ffmpeg")
    if ffm:
        cand = Path(ffm).with_name("ffprobe" + Path(ffm).suffix)
        if cand.is_file():
            return str(cand)
    return None


def _has_video_stream(path: str) -> bool:
    """True if the file has a picture with real dimensions that ffmpeg can decode."""
    probe, ffmpeg = _ffprobe(), shutil.which("ffmpeg")
    if not probe or not ffmpeg:
        return True     # can't check; ffmpeg will report it at send time
    p = subprocess.run([probe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                        "-of", "csv=p=0", path], capture_output=True, text=True, timeout=30)
    try:
        w, h = (int(x) for x in p.stdout.strip().split(",")[:2])
    except ValueError:
        return False
    if p.returncode != 0 or w <= 0 or h <= 0:
        return False
    d = subprocess.run([ffmpeg, "-v", "error", "-xerror", "-i", path, "-frames:v", "1", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=60)
    return d.returncode == 0


def audio_duration(path: str) -> Optional[float]:
    probe = _ffprobe()
    if not probe:
        return None
    p = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True, timeout=30)
    try:
        return float(p.stdout.strip())
    except ValueError:
        return None


def download_audio(audio_url: str, log: logging.Logger = module_logger) -> Optional[str]:
    """The call audio as a temp file. Audio saved by this server is copied from static/audio, since the
    server often can't reach its own BASE_URL (Docker, reverse proxies); anything else is downloaded."""
    local = _local_audio_file(audio_url)
    if local:
        fd, path = tempfile.mkstemp(prefix="icad_fb_", suffix=local.suffix or ".mp3")
        os.close(fd)
        shutil.copyfile(local, path)
        return path
    try:
        with requests.get(audio_url, stream=True, timeout=15) as r:
            r.raise_for_status()
            fd, path = tempfile.mkstemp(prefix="icad_fb_", suffix=".mp3")
            with os.fdopen(fd, "wb") as fh:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    fh.write(chunk)
        return path
    except Exception as e:
        log.warning("Facebook: couldn't download audio %s: %s", audio_url, e)
        return None


def _silent_audio(seconds: float) -> Optional[str]:
    """A silent MP3 (for a test video when the system has no saved call yet)."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    fd, path = tempfile.mkstemp(prefix="icad_fb_", suffix=".mp3")
    os.close(fd)
    p = subprocess.run([ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono",
                        "-t", f"{seconds:.1f}", "-c:a", "libmp3lame", "-b:a", "32k", path],
                       capture_output=True, timeout=60)
    if p.returncode != 0 or not os.path.getsize(path):
        os.remove(path)
        return None
    return path


def render_video(audio_path: str, background: Optional[Path], *, vertical: bool = False,
                 max_seconds: Optional[float] = None, min_seconds: float = 0.0,
                 log: logging.Logger = module_logger) -> Tuple[Optional[str], Optional[str]]:
    """
    Make an MP4: the background (image, looping clip, or black) with the call audio.
    Returns (mp4_path, error).
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None, "ffmpeg isn't installed, so a video can't be made."
    w, h = SIZE_VERTICAL if vertical else SIZE_LANDSCAPE
    kind = media_kind(background.name) if background else None

    cmd = [ffmpeg, "-y", "-v", "error"]
    if kind == "image":
        cmd += ["-loop", "1", "-framerate", "30", "-i", str(background)]
    elif kind == "video":
        cmd += ["-stream_loop", "-1", "-i", str(background)]
    else:
        cmd += ["-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r=30"]
    cmd += ["-i", audio_path]

    # fill the frame (crop the overflow), steady 30 fps, standard pixel format
    vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps=30,format=yuv420p"
    af = f"apad=whole_dur={min_seconds}" if min_seconds else "anull"
    fd, out = tempfile.mkstemp(prefix="icad_fb_", suffix=".mp4")
    os.close(fd)
    cmd += ["-map", "0:v:0", "-map", "1:a:0", "-vf", vf, "-af", af, "-shortest",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-profile:v", "high",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-movflags", "+faststart"]
    if kind != "video":
        cmd += ["-tune", "stillimage"]
    # -shortest can run a little long with looping inputs, so cap at the call's real length
    length = max(audio_duration(audio_path) or 0.0, min_seconds or 0.0) or None
    if max_seconds:
        length = min(length, max_seconds) if length else max_seconds
    if length:
        cmd += ["-t", f"{length:.3f}"]
    cmd.append(out)
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=180)
    except subprocess.TimeoutExpired:
        os.remove(out)
        return None, "Making the video took too long."
    if p.returncode != 0 or not os.path.getsize(out):
        os.remove(out)
        err = p.stderr.decode("utf-8", "ignore").strip().splitlines()
        log.warning("Facebook: ffmpeg failed: %s", " | ".join(err[-3:]))
        return None, "Couldn't make the video" + (f": {err[-1]}" if err else ".")
    return out, None


# ─────────────────────────────────────────────────────────────────────────────
# Datamodel
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class FacebookSettings:
    enabled: bool
    page_id: Optional[str]
    page_token: Optional[str]
    post_type: str              # "post" (text + audio link) or "video" (call audio over the background)
    message_body: Optional[str]
    background: Optional[Path] = None    # image / clip behind the audio in video posts


# ─────────────────────────────────────────────────────────────────────────────
# Sender
# ─────────────────────────────────────────────────────────────────────────────
class FacebookSender:
    """
    Publishes an alert to a Facebook Page (Pages can be posted to via the API; personal profiles can't).
    Needs the Page ID and a token with pages_manage_posts, pages_read_engagement and pages_show_list:
    a Page access token, or a user / system-user token for someone who can post on the Page.
    """

    def __init__(self, settings: FacebookSettings, *, logger: Optional[logging.Logger] = None):
        self.settings = settings
        self.log = logger or module_logger
        self.last_error: Optional[str] = None

    @property
    def enabled(self) -> bool:
        return bool(self.settings.enabled and self.settings.page_id and self.settings.page_token)

    @staticmethod
    def from_system_row(system_row: Dict[str, Any], *, logger: Optional[logging.Logger] = None) -> "FacebookSender":
        f = (system_row or {}).get("facebook") or {}
        post_type = str(f.get("post_type") or "post").strip().lower()
        settings = FacebookSettings(
            enabled=bool(int(f.get("enabled") or 0)),
            page_id=(str(f.get("page_id")).strip() if f.get("page_id") else None),
            page_token=(str(f.get("page_token")).strip() if f.get("page_token") else None),
            post_type=post_type if post_type in POST_TYPES else "post",
            message_body=(f.get("message_body") or DEFAULT_MESSAGE),
            background=media_path(f.get("background")),
        )
        return FacebookSender(settings, logger=logger)

    def send(self, ctx: Dict[str, Any], *, timeout_s: int = 20, max_retries: int = 2) -> bool:
        self.last_error = None
        if not self.enabled:
            self.last_error = "Facebook is disabled or the Page ID / Page token is missing."
            self.log.debug("Facebook: %s", self.last_error)
            return False

        message = self.build_message(ctx)
        audio_url = str(ctx.get("audio_url") or "")

        # A test before any call is saved has no audio; it still makes a (silent) video so videos can be checked
        if self.settings.post_type == "video" and (audio_url or ctx.get("is_test")):
            ok = self._send_video(audio_url, message, timeout_s=timeout_s, max_retries=max_retries)
            if ok is not None:
                return ok
            self.log.warning("Facebook: couldn't make a video (%s); posting text instead",
                             self.last_error or "the call audio couldn't be read")
        elif self.settings.post_type == "video":
            self.log.warning("Facebook: this alert has no call audio, so it's posted as text instead of a video")

        data = {"message": message, "access_token": self.settings.page_token}
        if audio_url:
            data["link"] = audio_url
        url = f"{_graph()}/{self.settings.page_id}/feed"
        return self._post(url, data=data, timeout_s=timeout_s, max_retries=max_retries)

    # ───────────────────────── internals ─────────────────────────
    def build_message(self, ctx: Dict[str, Any]) -> str:
        expanded = expand_template(self.settings.message_body or DEFAULT_MESSAGE, ctx).replace("\\n", "\n")
        # Facebook posts are plain text
        if "<" in expanded and ">" in expanded:
            expanded = html_to_text(expanded)
        text = unescape(expanded).strip()
        return text if len(text) <= FB_MAX_MESSAGE else text[: FB_MAX_MESSAGE - 1] + "…"

    def _send_video(self, audio_url: str, message: str, *, timeout_s: int, max_retries: int) -> Optional[bool]:
        """
        Upload the call audio as a video. Calls up to 90 s are made vertical (9:16) so Facebook shows them
        as a Reel; longer calls are widescreen. Returns None if no video could be made (caller posts text).
        """
        mp3 = download_audio(audio_url, self.log) if audio_url else _silent_audio(5.0)
        if not mp3:
            self.last_error = "couldn't get the call audio" if audio_url else "ffmpeg isn't installed"
            return None
        mp4 = None
        try:
            dur = audio_duration(mp3)
            vertical = dur is not None and dur <= REEL_MAX_S
            mp4, err = render_video(mp3, self.settings.background, vertical=vertical,
                                    min_seconds=REEL_MIN_S if vertical else 0.0, log=self.log)
            if not mp4:
                self.last_error = err
                return None
            url = f"{_graph(video=True)}/{self.settings.page_id}/videos"
            with open(mp4, "rb") as fh:
                return self._post(url, data={"description": message, "access_token": self.settings.page_token},
                                  files={"source": ("dispatch.mp4", fh, "video/mp4")},
                                  timeout_s=max(timeout_s, 60), max_retries=max_retries)
        finally:
            for p in (mp3, mp4):
                if p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass

    def _page_token(self) -> Optional[str]:
        """The token to post with. A Page token is used as it is; a user or system-user token (e.g. the
        never-expiring one from Meta Business Suite) is swapped for the Page's own token, asked from Facebook
        and kept for an hour."""
        given = self.settings.page_token
        key = (self.settings.page_id, hashlib.sha256((given or "").encode()).hexdigest())
        hit = _PAGE_TOKENS.get(key)
        if hit and hit[1] > time.time():
            return hit[0]
        token = given
        try:
            r = requests.get(f"{_graph()}/{self.settings.page_id}",
                             params={"fields": "access_token", "access_token": given}, timeout=10)
            body = r.json() if 200 <= r.status_code < 300 else {}
            if isinstance(body, dict) and body.get("access_token"):
                token = body["access_token"]
        except Exception:     # noqa: BLE001 - any trouble: use the token as given; posting reports real problems
            pass
        _PAGE_TOKENS[key] = (token, time.time() + 3600)
        return token

    def _post(self, url: str, *, data: Dict[str, Any], files: Optional[Dict[str, Any]] = None,
              timeout_s: int, max_retries: int) -> bool:
        if data.get("access_token"):
            data = dict(data, access_token=self._page_token())
        attempt = 0
        while attempt <= max_retries:
            attempt += 1
            try:
                if files:
                    for _, spec in files.items():
                        spec[1].seek(0)
                resp = requests.post(url, data=data, files=files, timeout=timeout_s)
                if 200 <= resp.status_code < 300:
                    self.log.info("Facebook: posted to page %s", self.settings.page_id)
                    return True
                self.last_error = _graph_error(resp)
                # 429 / transient Graph errors are worth one more try
                if resp.status_code in (429, 500, 502, 503) and attempt <= max_retries:
                    time.sleep(1.5)
                    continue
                self.log.warning("Facebook: HTTP %s: %s", resp.status_code, self.last_error)
                return False
            except Exception as e:
                self.last_error = f"Couldn't reach Facebook: {e}"
                self.log.debug("Facebook: request error %s (attempt %d/%d)", e, attempt, max_retries)
                time.sleep(0.5)
        self.log.warning("Facebook: %s", self.last_error)
        return False


def _graph_error(resp: requests.Response) -> str:
    try:
        err = (resp.json() or {}).get("error") or {}
        if err.get("message"):
            return f"Facebook said: {err['message']}"
    except (ValueError, json.JSONDecodeError, AttributeError):
        pass
    return f"Facebook returned HTTP {resp.status_code}: {(resp.text or '')[:300]}"
