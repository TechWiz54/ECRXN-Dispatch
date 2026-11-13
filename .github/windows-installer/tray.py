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
    """Start / stop / restart through service.ps1, which asks for admin rights. Only used when the task
    can't be controlled directly (see control()), or to move the firewall rule after a port change."""
    subprocess.Popen(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                      "-File", SERVICE, f"-{action}", *extra], creationflags=NO_WINDOW)


TASK = "ECRXN Dispatch"


def schtasks(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["schtasks.exe", *args], capture_output=True, text=True, creationflags=NO_WINDOW)


def task_running() -> bool:
    """Whether Windows says the background task is running (it may still be starting up)."""
    r = schtasks("/Query", "/TN", TASK, "/FO", "CSV", "/NH")
    return r.returncode == 0 and '"Running"' in r.stdout


def wait_for(check, seconds: float) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if check():
            return True
        time.sleep(1)
    return check()


def control(action: str) -> tuple[bool, str]:
    """Start / Stop / Restart and wait until it has really happened. The setup lets logged-in users run and
    end this task, so no admin prompt; if that permission is missing, fall back to service.ps1 (prompt)."""
    def end() -> bool:
        if not task_running() and not is_running():
            return True
        r = schtasks("/End", "/TN", TASK)
        if r.returncode != 0:
            return False
        return wait_for(lambda: not task_running() and not is_running(), 20)

    def run() -> bool:
        for _ in range(2):                       # once more if the first start didn't take
            if not task_running():
                if schtasks("/Run", "/TN", TASK).returncode != 0:
                    return False
            if wait_for(is_running, 45):
                return True
        return False

    if action in ("Stop", "Restart") and not end():
        if task_running() or is_running():        # no permission to end it: ask for admin rights instead
            service(action)
            ok = wait_for(lambda: (not is_running()) if action == "Stop" else is_running(), 60)
            return ok, "" if ok else "Windows didn't allow stopping ECRXN Dispatch."
    if action in ("Start", "Restart") and not run():
        if not is_running():
            service("Start")
            if wait_for(is_running, 60):
                return True, ""
            return False, "ECRXN Dispatch didn't start. The logs folder (right-click the icon) says why."
    return True, ""


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
        # restart so they take effect. A new port also moves the firewall rule, which needs admin rights.
        if p != old_port:
            service("Restart", "-Port", p)
            return
        ok, why = control("Restart")
        if not ok:
            message(why, error=True)

    btns = ttk.Frame(frm)
    btns.grid(row=8, column=0, columnspan=2, sticky="e", pady=(16, 0))
    ttk.Button(btns, text="Cancel", command=win.destroy).grid(row=0, column=0, padx=(0, 8))
    ttk.Button(btns, text="Save and restart", command=save).grid(row=0, column=1)
    ttk.Label(frm, text="Saving restarts ECRXN Dispatch. Changing the port asks for admin rights (firewall).",
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

    state = {"up": False, "starting": False, "busy": None}   # busy: "Starting…" etc. while an action runs

    def status_text(_item):
        if state["busy"]:
            return state["busy"]
        if state["up"]:
            return f"Running on port {port()}"
        return "Starting…" if state["starting"] else "Stopped"

    def refresh():
        state["up"] = is_running()
        state["starting"] = not state["up"] and task_running()
        icon.title = f"ECRXN Dispatch - {status_text(None).lower()}"
        icon.update_menu()

    def act(action, label):
        def go():
            state["busy"] = label
            refresh()
            try:
                ok, why = control(action)
            finally:
                state["busy"] = None
                refresh()
            if not ok:
                icon.notify(why, "ECRXN Dispatch")

        return lambda icon_, item: threading.Thread(target=go, daemon=True).start()

    idle = lambda: not state["busy"] and not state["starting"]
    icon = pystray.Icon(
        "ECRXN Dispatch", Image.open(ICON), "ECRXN Dispatch",
        menu=pystray.Menu(
            pystray.MenuItem("Open dashboard", lambda i, it: webbrowser.open(dashboard_url()), default=True),
            pystray.MenuItem(status_text, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Restart", act("Restart", "Restarting…"), enabled=lambda it: idle()),
            pystray.MenuItem("Stop", act("Stop", "Stopping…"), visible=lambda it: state["up"] or state["starting"],
                             enabled=lambda it: not state["busy"]),
            pystray.MenuItem("Start", act("Start", "Starting…"), visible=lambda it: not state["up"] and not state["starting"],
                             enabled=lambda it: idle()),
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
            if not state["busy"]:
                refresh()
            time.sleep(2 if state["starting"] else 5)

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
