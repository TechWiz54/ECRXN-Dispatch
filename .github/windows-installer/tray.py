"""
ECRXN Dispatch tray icon (Windows). Sits next to the clock while you're logged in; ECRXN Dispatch itself
runs at boot as a background task, so it keeps working when nobody is logged in.

Right-click menu: open the dashboard, see whether it's running, start / stop / restart it, change the
settings (port, alert link address, timezone, log level) and open the logs.

  pythonw tray.py             show the icon (started at login)
  pythonw tray.py --open      open the dashboard, and show the icon if it isn't there yet
  pythonw tray.py --settings  open the settings window
"""
from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, available_timezones

HERE = os.path.dirname(os.path.abspath(__file__))     # <install>\windows
ROOT = os.path.dirname(HERE)                           # <install>
ENV = os.path.join(ROOT, ".env")
SERVICE = os.path.join(HERE, "service.ps1")
ICON = os.path.join(HERE, "ecrxn.ico")
DOCS = "https://github.com/TechWiz54/ECRXN-Dispatch/blob/main/docs/setup.md"
NO_WINDOW = 0x08000000                                 # CREATE_NO_WINDOW

LOG_LEVELS = {"1": "Debug (everything)", "2": "Info (normal)", "3": "Warnings", "4": "Errors only", "5": "Critical only"}


# ───────────────────────────── .env ─────────────────────────────
def read_env() -> dict:
    values = {}
    try:
        with open(ENV, encoding="utf-8") as fh:
            for line in fh:
                m = re.match(r"\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*$", line)
                if m:
                    values[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    except OSError:
        pass
    return values


def write_env(changes: dict) -> None:
    """Change some keys in .env, keeping every other line (and comment) as it is."""
    try:
        with open(ENV, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        lines = []
    left = dict(changes)
    for i, line in enumerate(lines):
        m = re.match(r"\s*([A-Z_][A-Z0-9_]*)\s*=", line)
        if m and m.group(1) in left:
            lines[i] = f"{m.group(1)}={left.pop(m.group(1))}"
    lines += [f"{k}={v}" for k, v in left.items()]
    with open(ENV, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


def port() -> int:
    try:
        return int(read_env().get("PORT") or 9911)
    except ValueError:
        return 9911


def dashboard_url() -> str:
    return f"http://localhost:{port()}/"


def is_running() -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port()}/login", timeout=2) as r:
            return r.status < 500
    except Exception:  # noqa: BLE001 - refused, timeout, ...: not running
        return False


def service(action: str, *extra: str) -> None:
    """Start / stop / restart the background task (asks for admin rights)."""
    subprocess.Popen(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                      "-File", SERVICE, f"-{action}", *extra], creationflags=NO_WINDOW)


def message(text: str, title: str = "ECRXN Dispatch", error: bool = False) -> None:
    ctypes.windll.user32.MessageBoxW(None, text, title, 0x10 if error else 0x40)


# ───────────────────────────── settings window ─────────────────────────────
def check_settings(port_s: str, base_url: str, tz: str) -> str | None:
    """An error message, or None when the values are fine."""
    if not port_s.isdigit() or not 1 <= int(port_s) <= 65535:
        return "The port must be a number from 1 to 65535."
    u = urlparse(base_url)
    if u.scheme not in ("http", "https") or not u.hostname:
        return "The address for alert links must start with http:// or https://, e.g. http://192.168.1.50:9911"
    try:
        ZoneInfo(tz)
    except Exception:  # noqa: BLE001
        return f"'{tz}' isn't a timezone name. Examples: America/New_York, America/Chicago, America/Denver."
    return None


def settings_window() -> None:
    import tkinter as tk
    from tkinter import ttk

    env = read_env()
    old_port = str(port())
    win = tk.Tk()
    win.title("ECRXN Dispatch settings")
    win.resizable(False, False)
    try:
        win.iconbitmap(ICON)
    except tk.TclError:
        pass
    frm = ttk.Frame(win, padding=16)
    frm.grid()

    fields = {}

    def row(r, label, key, value, hint, widget=None):
        ttk.Label(frm, text=label).grid(row=r * 2, column=0, sticky="w", pady=(8 if r else 0, 0))
        w = widget or ttk.Entry(frm, width=46)
        if not widget:
            w.insert(0, value)
        w.grid(row=r * 2, column=1, sticky="we", padx=(12, 0), pady=(8 if r else 0, 0))
        ttk.Label(frm, text=hint, foreground="#666").grid(row=r * 2 + 1, column=1, sticky="w", padx=(12, 0))
        fields[key] = w

    row(0, "Port", "PORT", old_port, "The dashboard's port (default 9911).")
    row(1, "Address for alert links", "BASE_URL", env.get("BASE_URL", f"http://localhost:{old_port}"),
        "How other devices reach this PC, e.g. http://192.168.1.50:9911")
    tz = ttk.Combobox(frm, width=44, values=sorted(z for z in available_timezones() if z.startswith(("America/", "US/", "Etc/UTC"))))
    tz.set(env.get("TIMEZONE", "America/New_York"))
    row(2, "Timezone", "TIMEZONE", None, "Used for the times in alerts.", widget=tz)
    lvl = ttk.Combobox(frm, width=44, state="readonly", values=list(LOG_LEVELS.values()))
    lvl.set(LOG_LEVELS.get(env.get("LOG_LEVEL", "2"), LOG_LEVELS["2"]))
    row(3, "Log detail", "LOG_LEVEL", None, "Info is right for everyday use.", widget=lvl)

    def save():
        p = fields["PORT"].get().strip()
        base = fields["BASE_URL"].get().strip().rstrip("/")
        zone = fields["TIMEZONE"].get().strip()
        err = check_settings(p, base, zone)
        if err:
            message(err, "ECRXN Dispatch settings", error=True)
            return
        level = next(k for k, v in LOG_LEVELS.items() if v == fields["LOG_LEVEL"].get())
        host = urlparse(base).hostname or ""
        try:
            write_env({"PORT": p, "BASE_URL": base, "TIMEZONE": zone, "LOG_LEVEL": level,
                       "SESSION_COOKIE_DOMAIN": host})
        except OSError as e:
            message(f"Couldn't save the settings: {e}", error=True)
            return
        win.destroy()
        # restart so they take effect (and move the firewall rule when the port changed)
        service("Restart", *(["-Port", p] if p != old_port else []))

    btns = ttk.Frame(frm)
    btns.grid(row=8, column=0, columnspan=2, sticky="e", pady=(16, 0))
    ttk.Button(btns, text="Cancel", command=win.destroy).grid(row=0, column=0, padx=(0, 8))
    ttk.Button(btns, text="Save and restart", command=save).grid(row=0, column=1)
    ttk.Label(frm, text="Saving restarts ECRXN Dispatch (Windows asks for permission).",
              foreground="#666").grid(row=9, column=0, columnspan=2, sticky="w", pady=(10, 0))
    win.mainloop()


def open_settings() -> None:
    # its own process, so the window never blocks the tray icon
    subprocess.Popen([sys.executable, os.path.abspath(__file__), "--settings"], creationflags=NO_WINDOW)


# ───────────────────────────── tray icon ─────────────────────────────
def already_running() -> bool:
    """Only one tray icon per login."""
    ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\ECRXNDispatchTray")
    return ctypes.windll.kernel32.GetLastError() == 183   # ERROR_ALREADY_EXISTS


def run_tray() -> None:
    import pystray
    from PIL import Image

    state = {"up": False}

    def status_text(_item):
        return f"Running on port {port()}" if state["up"] else "Stopped"

    def act(action):
        return lambda icon, item: service(action)

    icon = pystray.Icon(
        "ECRXN Dispatch", Image.open(ICON), "ECRXN Dispatch",
        menu=pystray.Menu(
            pystray.MenuItem("Open dashboard", lambda i, it: webbrowser.open(dashboard_url()), default=True),
            pystray.MenuItem(status_text, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Restart", act("Restart")),
            pystray.MenuItem("Stop", act("Stop"), visible=lambda it: state["up"]),
            pystray.MenuItem("Start", act("Start"), visible=lambda it: not state["up"]),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Settings…", lambda i, it: open_settings()),
            pystray.MenuItem("Open the logs folder", lambda i, it: os.startfile(os.path.join(ROOT, "log"))),
            pystray.MenuItem("Help", lambda i, it: webbrowser.open(DOCS)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Hide this icon", lambda i, it: i.stop()),
        ),
    )

    def watch():
        while True:
            up = is_running()
            if up != state["up"]:
                state["up"] = up
                icon.title = f"ECRXN Dispatch - {status_text(None).lower()}"
                icon.update_menu()
            time.sleep(5)

    threading.Thread(target=watch, daemon=True).start()
    icon.run()


def main() -> None:
    args = sys.argv[1:]
    if "--settings" in args:
        settings_window()
        return
    if "--open" in args:
        webbrowser.open(dashboard_url())
    if already_running():
        return
    run_tray()


if __name__ == "__main__":
    main()
