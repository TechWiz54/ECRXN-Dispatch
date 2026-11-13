#!/usr/bin/env python3
"""
Builds the browser-only demo in public/ecrxn-dispatch-demo/ from the real app.

  python public/build_demo.py

How it works:
  1. starts ECRXN Dispatch in-process on a throw-away database (your real one is never opened),
  2. adds a demo system + triggers and uploads three made-up calls so the real tone finder marks them
     (the third has tones no trigger covers, for the "Tones without a trigger" panel),
  3. saves every page as static HTML and every API answer the pages need as demo-data.js,
  4. copies the CSS / JS / fonts, pointing links at the static pages.
The pages then run on demo-api.js, which answers the dashboard's API calls from that data and
keeps any changes in the browser tab only (sessionStorage, reset after an hour) - no server, no database.
A Content-Security-Policy on every page stops the demo from contacting any other site.

Needs ffmpeg (to make the demo audio). Re-run it after changing the dashboard.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "public" / "ecrxn-dispatch-demo"
SRC = Path(__file__).resolve().parent / "demo_src"
PAGES = {  # app path -> demo file
    "/dashboard": "index.html",
    "/dashboard/systems": "systems.html",
    "/dashboard/triggers": "triggers.html",
    "/dashboard/change_password": "change_password.html",
    "/login": "login.html",
}
DEMO_USER, DEMO_PASS = "demo", "Demo-pass-123!"


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def make_audio(path: Path, a_hz: float, b_hz: float, seconds_voice: float = 6.0):
    """Two-tone page (1 s + 3 s) then a few seconds of radio-ish noise standing in for the voice."""
    ffmpeg("-f", "lavfi", "-i", f"sine=frequency={a_hz}:duration=1.0:sample_rate=16000",
           "-f", "lavfi", "-i", f"sine=frequency={b_hz}:duration=3.0:sample_rate=16000",
           "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-f", "lavfi",
           "-i", f"anoisesrc=d={seconds_voice}:c=pink:r=16000:a=0.05",
           "-filter_complex",
           "[2]atrim=0:0.4[g];[3]bandpass=f=1200:width_type=h:w=1800,volume=2.5[v];"
           "[0][1][g][v]concat=n=4:v=0:a=1,volume=0.6",
           "-ac", "1", "-b:a", "48k", str(path))


def main():
    tmp = Path(tempfile.mkdtemp(prefix="ecrxn_demo_"))
    shutil.rmtree(OUT, ignore_errors=True)
    shutil.rmtree(OUT.parent / "icad-dispatch-demo", ignore_errors=True)    # the folder's old name
    OUT.mkdir(parents=True)
    os.environ.update({
        "SQLITE_DATABASE_PATH": str(tmp / "demo.db"), "ROOT_USERNAME": DEMO_USER, "ROOT_PASSWORD": DEMO_PASS,
        "LOG_LEVEL": "4", "BASE_URL": "http://demo.local", "TIMEZONE": "America/New_York",
    })
    os.environ.pop("RESET_ADMIN_PASSWORD", None)
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    from app import app  # noqa: E402  (after the env is set)

    c = app.test_client()
    csrf = re.search(r'name="_csrf_token" value="([^"]+)"', c.get("/login").get_data(as_text=True)).group(1)
    H = {"X-CSRFToken": csrf, "Accept": "application/json"}
    assert c.post("/auth/login", data={"loginEmail": DEMO_USER, "loginPassword": DEMO_PASS, "_csrf_token": csrf},
                  headers=H).status_code == 200
    with c.session_transaction() as s:
        s["default_password"] = False

    def api(method, path, body=None):
        r = c.open(path, method=method, json=dict(body or {}, _csrf_token=csrf), headers=H)
        j = r.get_json(silent=True)
        if r.status_code >= 400:
            raise SystemExit(f"{method} {path} -> {r.status_code}: {r.get_data(as_text=True)[:300]}")
        return j

    # ── demo data ────────────────────────────────────────────────────
    sid = api("POST", "/api/systems", {"system_decimal": 1001, "system_name": "Demo County",
                                       "stream_url": "https://example.com/demo-stream"})["result"]
    sid = sid if isinstance(sid, int) else sid.get("radio_system_id", 1)
    api("PATCH", f"/api/systems/{sid}/tone/settings", {"tone_finder_enabled": 1, "tone_a_min_length": 0.7,
                                                        "tone_b_min_length": 2.6, "long_tone_min_length": 1.8})
    api("PATCH", f"/api/systems/{sid}/discord/settings", {"discord_enabled": 1, "discord_attach_audio": 1,
                                                          "discord_webhook_url": "https://discord.com/api/webhooks/0/demo",
                                                          "discord_embed_title": "{trigger_list}", "discord_embed_color": "#F04646"})
    api("PATCH", f"/api/systems/{sid}/facebook/settings", {"facebook_enabled": 1, "facebook_page_id": "100000000000001",
                                                           "facebook_page_token": "demo-token", "facebook_post_type": "video"})
    triggers = [("Station 4 Fire", 433.8, 1641.7, 100), ("County EMS", 568.1, 1153.4, 100),
                ("Station 12 Rescue", 707.3, 1045.7, None)]
    tids = []
    for name, a, b, tg in triggers:
        tids.append(api("POST", f"/api/systems/{sid}/triggers", {
            "alert_trigger_name": name, "alert_trigger_enabled": 1, "alert_trigger_type": "OR",
            "alert_trigger_ignore_time": 30, "alert_trigger_tone_tolerance": 2,
            **({"alert_trigger_talkgroup": tg} if tg else {}),
            "two_tone_sets": [{"rule_uid": "demo1", "freq_a_hz": a, "min_len_a_s": 0.7, "freq_b_hz": b, "min_len_b_s": 2.6}],
        })["result"]["alert_trigger_id"])
    api("PUT", f"/api/systems/{sid}/triggers/{tids[0]}/notifiers/discord",
        {"enabled": 1, "webhook_url": "https://discord.com/api/webhooks/0/station4", "message": "@here {trigger_list} dispatched",
         "attach_audio": 1})
    api("PUT", f"/api/systems/{sid}/triggers/{tids[1]}/notifiers/email",
        {"enabled": 1, "recipients": "ems-chief@example.com", "attach_audio": 1})

    key = c.get("/api/systems?include_config=1").get_json()["result"][0]["api_key"]
    audio_dir = tmp / "audio"
    audio_dir.mkdir()
    saved = []
    # two calls the triggers catch, and one page no trigger covers yet
    for i, (name, a, b, _tg) in enumerate(triggers[:2] + [("Station 9 (no trigger yet)", 600.9, 1251.4, 100)]):
        mp3 = audio_dir / f"demo_call_{i + 1}.mp3"
        make_audio(mp3, a, b)
        with open(mp3, "rb") as fh:
            r = c.post("/api/call-upload", data={"system": "1001", "key": key, "talkgroup": "100",
                                                 "start_time": str(int(time.time()) - 3600 * (3 - i)),
                                                 "audio": (fh, mp3.name, "audio/mpeg")})
        if r.status_code >= 400:
            raise SystemExit(f"upload failed: {r.get_data(as_text=True)[:300]}")
        saved.append(mp3)
    time.sleep(3)   # let the background tone check / alert threads finish

    # ── API answers the pages read ───────────────────────────────────
    data = {"systems": c.get("/api/systems?include_config=1").get_json()["result"]}
    for s in data["systems"]:
        s["api_key"] = "demo-api-key-0000-0000-000000000000"
    data["triggers"] = c.get(f"/api/systems/{sid}/triggers?full=1").get_json()["result"]
    data["notifiers"], data["pushover"] = {}, {}
    for t in data["triggers"]:
        tid = t["alert_trigger_id"]
        data["notifiers"][tid] = c.get(f"/api/systems/{sid}/triggers/{tid}/notifiers").get_json()["result"]
        data["pushover"][tid] = c.get(f"/api/systems/{sid}/triggers/{tid}/pushover/settings").get_json()["result"]
    data["unmatched"] = c.get(f"/api/tone-finder/unmatched?radio_system_id={sid}&days=365").get_json()["result"]
    calls = c.get(f"/api/tone-finder/calls?radio_system_id={sid}&limit=100").get_json()
    data["calls"] = calls
    data["call_details"] = {}
    for row in (calls.get("result") or calls.get("calls") or []):
        cid = row.get("call_id") or row.get("id")
        data["call_details"][cid] = c.get(f"/api/tone-finder/calls/{cid}").get_json()

    # where the uploads landed under static/audio -> demo audio/
    blob = json.dumps(data)
    for url in set(re.findall(r'http://demo\.local/static/audio/[^"\\]+\.mp3', blob)):
        rel = url.split("/static/audio/", 1)[1]
        local = ROOT / "static" / "audio" / rel
        name = Path(rel).name
        (OUT / "audio").mkdir(parents=True, exist_ok=True)
        if local.exists():
            shutil.move(str(local), OUT / "audio" / name)
        blob = blob.replace(url, f"audio/{name}")
    data = json.loads(blob)

    # ── pages ────────────────────────────────────────────────────────
    for src, dest in PAGES.items():
        if src == "/login":
            html = app.test_client().get("/login").get_data(as_text=True)
        else:
            html = c.get(src).get_data(as_text=True)
        (OUT / dest).write_text(rewrite_html(html), encoding="utf-8")

    # ── static files ─────────────────────────────────────────────────
    for sub in ("css", "img", "vendor", "js"):
        shutil.copytree(ROOT / "static" / sub, OUT / "static" / sub, dirs_exist_ok=True)
    for js in (OUT / "static" / "js").rglob("*.js"):
        js.write_text(rewrite_js(js.read_text(encoding="utf-8")), encoding="utf-8")
    (OUT / "demo-data.js").write_text("window.DEMO_DATA = " + json.dumps(data, indent=1) + ";\n", encoding="utf-8")
    for f in SRC.iterdir():
        shutil.copy(f, OUT / f.name)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"Demo written to {OUT}")


# Only this site's own files: the demo can't send anything anywhere, whatever is typed into it
CSP = ('<meta http-equiv="Content-Security-Policy" content="'
       "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data: blob:; media-src 'self' blob: data:; font-src 'self' data:; connect-src 'self'; "
       "form-action 'none'; frame-src 'none'; object-src 'none'; base-uri 'self'" + '">')

LINKS = [("/dashboard/systems", "systems.html"), ("/dashboard/triggers", "triggers.html"),
         ("/dashboard/change_password", "change_password.html"),
         ("/dashboard", "index.html"), ("/auth/logout", "login.html"), ("/login", "login.html")]


def rewrite_html(html: str) -> str:
    html = re.sub(r'(href|src)="/static/', r'\1="static/', html)
    html = html.replace('url("/static/', 'url("static/')       # inline @font-face
    for a, b in LINKS:
        html = re.sub(rf'(href|action)="{re.escape(a)}(["?#])', rf'\1="{b}\2', html)
    html = html.replace('href="/"', 'href="index.html"')
    # the demo layer goes first so it can answer the page's very first requests
    inject = ('<script src="demo-data.js"></script><script src="demo-api.js"></script>'
              '<link rel="stylesheet" href="demo.css">')
    html = html.replace("<head>", "<head>\n    " + CSP + "\n    " + inject, 1)
    html = re.sub(r"<title>(.*?)</title>", r"<title>\1 Demo</title>", html, count=1)
    return html


def rewrite_js(js: str) -> str:
    for a, b in LINKS:
        js = re.sub(rf'([`"\']){re.escape(a)}(?=[`"\'?#])', rf"\1{b}", js)
    return js


if __name__ == "__main__":
    main()
