#!/usr/bin/env python3
"""
Native (non-Docker) launcher for ECRXN Dispatch.

Works on Windows and Linux:
  - always runs from the project folder, so log/, var/ and static/audio/ land in the right place
  - loads .env
  - finds ffmpeg: the copy the Windows installer bundles, else the one installed on the computer
  - Linux: runs gunicorn (same settings as the Docker image)
  - Windows: runs waitress (gunicorn does not support Windows)

Usage:
  python serve.py                # uses PORT / WEB_THREADS / WEB_CONCURRENCY / WEB_TIMEOUT from .env
  python serve.py --waitress     # force waitress on Linux too
  python serve.py --reset-password [username]   # forgot the password? set a new one
"""
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

# The Windows installer ships its own ffmpeg next to the app
_BUNDLED_FFMPEG = os.path.join(ROOT, "ffmpeg", "bin")
if os.path.isdir(_BUNDLED_FFMPEG):
    os.environ["PATH"] = _BUNDLED_FFMPEG + os.pathsep + os.environ.get("PATH", "")

if sys.platform == "win32" and shutil.which("ffmpeg") is None:
    # Programs started at boot (or before ffmpeg was installed) can have a stale PATH;
    # pick up the current machine + user PATH so a winget-installed ffmpeg is found.
    import winreg

    def _registry_path(root, key):
        try:
            with winreg.OpenKey(root, key) as k:
                return os.path.expandvars(winreg.QueryValueEx(k, "Path")[0])
        except OSError:
            return ""

    os.environ["PATH"] = os.pathsep.join(filter(None, [
        os.environ.get("PATH", ""),
        _registry_path(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
        _registry_path(winreg.HKEY_CURRENT_USER, "Environment"),
    ]))

PORT = int(os.getenv("PORT", "9911"))
HOST = os.getenv("HOST", "0.0.0.0")
THREADS = int(os.getenv("WEB_THREADS", "8"))
WORKERS = int(os.getenv("WEB_CONCURRENCY", "1"))
TIMEOUT = int(os.getenv("WEB_TIMEOUT", "60"))
# Largest request accepted (Facebook background clips can be up to 2 GB; they're shrunk once saved)
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "2100"))


def reset_password() -> None:
    """python serve.py --reset-password [username] : set a new password without knowing the old one."""
    import getpass
    from lib.sqlite_module import SQLiteDatabase
    from lib.user_module import reset_admin_password

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    username = args[0] if args else (os.getenv("ROOT_USERNAME") or None)
    print(f"Set a new password for {username or 'the admin account'}.")
    new = getpass.getpass("New password (at least 8 characters): ")
    if new != getpass.getpass("Type it again: "):
        sys.exit("The passwords didn't match - nothing changed.")
    res = reset_admin_password(SQLiteDatabase(), new, username)
    print(res["message"])
    if not res["success"]:
        sys.exit(1)
    print("Done. Log in with the new password (restart ECRXN Dispatch first if it's running).")


def main() -> None:
    if shutil.which("ffmpeg") is None:
        print("WARNING: ffmpeg was not found. Audio processing will fail until it is installed "
              "(Windows: winget install Gyan.FFmpeg.Essentials, Linux: your package manager).",
              file=sys.stderr)

    use_waitress = sys.platform == "win32" or "--waitress" in sys.argv

    if use_waitress:
        from waitress import serve
        from app import app

        print(f"ECRXN Dispatch listening on http://{HOST}:{PORT}  (waitress, {THREADS} threads)")
        serve(app, host=HOST, port=PORT, threads=THREADS, channel_timeout=TIMEOUT,
              max_request_body_size=1024 * 1024 * MAX_UPLOAD_MB, ident="icad_dispatch")
    else:
        gunicorn = os.path.join(os.path.dirname(sys.executable), "gunicorn")  # the venv's copy
        if not os.path.exists(gunicorn):
            gunicorn = shutil.which("gunicorn")
        if not gunicorn:
            sys.exit("gunicorn is not installed - run: pip install -r requirements.txt")
        args = [gunicorn, "-b", f"{HOST}:{PORT}", "-w", str(WORKERS), "--threads", str(THREADS),
                "--worker-class", "gthread", "--timeout", str(TIMEOUT), "--keep-alive", "5",
                "--access-logfile", "-", "--error-logfile", "-", "app:app"]
        os.execv(gunicorn, args)


if __name__ == "__main__":
    if "--reset-password" in sys.argv:
        reset_password()
    else:
        main()
