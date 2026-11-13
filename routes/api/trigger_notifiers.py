# routes/api/trigger_notifiers.py
"""
Per-trigger notifier settings + test sends, and the system-level Facebook settings.
Routes are attached to the /api/systems blueprint.
"""
from __future__ import annotations

import io
import logging
import os
import time

from flask import request, jsonify, abort, current_app, send_file

from lib.alert_trigger_module import get_triggers, get_pushover_settings
from lib.facebook_module import (
    FacebookSender, background_info, media_path, media_kind, save_background, remove_background, download_audio,
    audio_duration, render_video, REEL_MAX_S, REEL_MIN_S,
)
from lib.pushover_module import PushoverSender
from lib.system_module import get_systems, update_system_facebook_settings, set_system_facebook_background
from lib.trigger_notifier_module import (
    CHANNELS, SYSTEM_CHANNELS, get_trigger_notifiers, save_trigger_notifier, clean_channel_config,
    send_channel, trigger_context, get_system_includes, set_system_include, set_trigger_facebook_background,
    fill_template_defaults,
)
from routes.api.systems import api_systems
from routes.decorators import login_required, csrf_protect

route_logger = logging.getLogger("icad_dispatch.trigger_notifiers")


def _body() -> dict:
    return (request.get_json(silent=True) if request.is_json else request.form.to_dict()) or {}


def _system_or_404(db, radio_system_id: int) -> dict:
    res = get_systems(db, radio_system_id=radio_system_id, include_config=True)
    if not res.get("success") or not res.get("result"):
        abort(404, "System not found.")
    return res["result"][0]


def _trigger_or_404(db, radio_system_id: int, alert_trigger_id: int) -> dict:
    res = get_triggers(db, alert_trigger_id=alert_trigger_id)
    rows = (res.get("result") or []) if res.get("success") else []
    if not rows or int(rows[0].get("radio_system_id")) != int(radio_system_id):
        abort(404, "Trigger not found for this system.")
    return rows[0]


def _system_summary(system: dict) -> dict:
    """What the system already has, so the page can say 'blank = use the system's ...'."""
    tg, em, n8n, fb = (system.get(k) or {} for k in ("telegram", "email", "n8n", "facebook"))
    return {
        "telegram_bot_token": bool(tg.get("bot_token")),
        "email_server": em.get("smtp_hostname") or "",
        "email_from": em.get("email_address_from") or "",
        "email_subject": em.get("email_alert_subject") or "",
        "pushover_subject": (system.get("pushover") or {}).get("subject") or "Dispatch Alert",
        "pushover_body": (system.get("pushover") or {}).get("body") or "",
        "n8n_passphrase": bool(n8n.get("jwt_passphrase")),
        "facebook_page_token": bool(fb.get("page_token")),
        "facebook_background": _bg_info(fb.get("background")),
        "discord_fields": len([f for f in (system.get("discord") or {}).get("fields") or [] if f.get("field_enabled")]),
        "make_fields": len([f for f in (system.get("make") or {}).get("fields") or [] if f.get("field_enabled")]),
        # which of the system's own channels are switched on
        "enabled": {ch: bool(int((system.get(ch) or {}).get("enabled") or 0)) for ch in SYSTEM_CHANNELS},
    }


def _test_payload(db, system: dict, trigger: dict) -> dict:
    """Use the system's latest call for the audio link so the test looks like a real alert."""
    rsid = system["radio_system_id"]
    last = db.execute_query(
        "SELECT talkgroup, file_path, duration_s, start_epoch_s FROM call_records "
        "WHERE radio_system_id = ? ORDER BY call_id DESC LIMIT 1",
        (rsid,), fetch_mode="one",
    )
    row = (last.get("result") or {}) if last.get("success") else {}
    return {
        "radio_system_id": rsid,
        "talkgroup": str(trigger.get("alert_trigger_talkgroup") or row.get("talkgroup") or ""),
        "talkgroup_name": "",
        "duration_s": float(row.get("duration_s") or 0),
        "start_epoch_s": int(time.time()),
        "audio_url": row.get("file_path") or "",
    }


# ──────────────────────────────────────────────────────────────────────
# /api/systems/<sys>/triggers/<id>/notifiers           GET
# /api/systems/<sys>/triggers/<id>/notifiers/<channel> PUT
# /api/systems/<sys>/triggers/<id>/notifiers/<channel>/test  POST
# ──────────────────────────────────────────────────────────────────────
@api_systems.route("/<int:radio_system_id>/triggers/<int:alert_trigger_id>/notifiers", methods=["GET"])
@login_required
def trigger_notifiers_get(radio_system_id: int, alert_trigger_id: int):
    db = current_app.config["db"]
    _trigger_or_404(db, radio_system_id, alert_trigger_id)
    system = _system_or_404(db, radio_system_id)
    channels = fill_template_defaults(get_trigger_notifiers(db, alert_trigger_id), system)
    return jsonify(success=True, message="OK", result={
        "channels": channels,
        "facebook_background": _bg_info(channels["facebook"].get("background")),
        "system": _system_summary(system),
        "system_includes": get_system_includes(db, [alert_trigger_id])[alert_trigger_id],
    }), 200


@api_systems.route("/<int:radio_system_id>/triggers/<int:alert_trigger_id>/notifiers/<channel>/system", methods=["PUT", "PATCH"])
@login_required
@csrf_protect
def trigger_notifier_system_include(radio_system_id: int, alert_trigger_id: int, channel: str):
    """Include / leave out this trigger from the system's alert on one channel."""
    db = current_app.config["db"]
    _trigger_or_404(db, radio_system_id, alert_trigger_id)
    if channel not in SYSTEM_CHANNELS:
        abort(404, "Unknown notifier.")
    res = set_system_include(db, alert_trigger_id, channel, _body().get("include", 1))
    return jsonify(res), (200 if res["success"] else 400)


@api_systems.route("/<int:radio_system_id>/triggers/<int:alert_trigger_id>/notifiers/<channel>", methods=["PUT", "PATCH"])
@login_required
@csrf_protect
def trigger_notifier_save(radio_system_id: int, alert_trigger_id: int, channel: str):
    db = current_app.config["db"]
    _trigger_or_404(db, radio_system_id, alert_trigger_id)
    if channel not in CHANNELS:
        abort(404, "Unknown notifier.")
    res = save_trigger_notifier(db, alert_trigger_id, channel, _body())
    return jsonify(res), (200 if res["success"] else 400)


@api_systems.route("/<int:radio_system_id>/triggers/<int:alert_trigger_id>/notifiers/<channel>/test", methods=["POST"])
@login_required
@csrf_protect
def trigger_notifier_test(radio_system_id: int, alert_trigger_id: int, channel: str):
    """Send a test alert using the settings in the request (so unsaved edits can be tried)."""
    db = current_app.config["db"]
    trigger = _trigger_or_404(db, radio_system_id, alert_trigger_id)
    system = _system_or_404(db, radio_system_id)
    data = _body()

    ctx = trigger_context(system, _test_payload(db, system, trigger), trigger,
                          transcript_text="This is a test alert from ECRXN Dispatch.",
                          tz=current_app.config["TIMEZONE"])
    ctx["trigger_list"] = f"[TEST] {ctx.get('trigger_list') or trigger.get('alert_trigger_name')}"

    if channel == "pushover":
        po = get_pushover_settings(db, alert_trigger_id).get("result") or {}
        po.update({k: v for k, v in data.items() if k.startswith("pushover_")})
        if not (po.get("pushover_app_token") and po.get("pushover_group_token")):
            return jsonify(success=False, message="Enter the Pushover group and app tokens.", result=[]), 400
        sender = PushoverSender.from_system_row(system, [{**trigger, **po, "enable_pushover": 1}])
        ok = sender.send_for_triggers(ctx) > 0
        return jsonify(success=ok, message="Test sent to Pushover." if ok else
                       "Pushover didn't accept it - check the tokens.", result=[]), (200 if ok else 400)

    if channel not in CHANNELS:
        abort(404, "Unknown notifier.")
    cfg, _enabled, err = clean_channel_config(channel, dict(data, enabled=1))
    if err:
        return jsonify(success=False, message=err, result=[]), 400
    if channel == "telegram" and int(cfg.get("send_audio") or 0) and not ctx.get("audio_url"):
        return jsonify(success=False, message="A voice-message test needs at least one call on this system "
                                              "(or turn off \"Send the audio\" to test a text message).", result=[]), 400

    ok, msg = send_channel(channel, cfg, system, ctx)
    route_logger.info("Trigger %s test %s: %s", alert_trigger_id, channel, msg)
    name = {"n8n": "n8n"}.get(channel, channel.capitalize())
    return jsonify(success=ok, message=(f"Test sent to {name}." if ok else msg), result=[]), (200 if ok else 400)


# ──────────────────────────────────────────────────────────────────────
# System-level Facebook      GET | PATCH  /api/systems/<sys>/facebook/settings
#                            POST         /api/systems/<sys>/facebook/test
# ──────────────────────────────────────────────────────────────────────
@api_systems.route("/<int:radio_system_id>/facebook/settings", methods=["GET", "PATCH"])
@login_required
@csrf_protect
def systems_facebook_settings(radio_system_id: int):
    db = current_app.config["db"]
    if request.method == "GET":
        return jsonify(success=True, message="OK", result=_system_or_404(db, radio_system_id).get("facebook") or {}), 200

    _system_or_404(db, radio_system_id)
    payload = dict(_body(), radio_system_id=radio_system_id)
    upd = update_system_facebook_settings(db, payload)
    if not upd.get("success"):
        return jsonify(success=False, message=upd.get("message"), result=[]), 400
    return jsonify(success=True, message="Facebook settings updated.",
                   result=_system_or_404(db, radio_system_id).get("facebook") or {}), 200


@api_systems.route("/<int:radio_system_id>/facebook/test", methods=["POST"])
@login_required
@csrf_protect
def systems_facebook_test(radio_system_id: int):
    db = current_app.config["db"]
    system = _system_or_404(db, radio_system_id)
    fb_cfg = dict(system.get("facebook") or {})
    data = _body()
    for key in ("page_id", "page_token", "post_type", "message_body"):
        if data.get(f"facebook_{key}") not in (None, ""):
            fb_cfg[key] = data[f"facebook_{key}"]
    fb_cfg["enabled"] = 1
    sender = FacebookSender.from_system_row({"facebook": fb_cfg})
    if not sender.enabled:
        return jsonify(success=False, message="Enter the Facebook Page ID and Page access token.", result=[]), 400

    fake_trigger = {"alert_trigger_name": "[TEST] ECRXN Dispatch"}
    ctx = trigger_context(system, _test_payload(db, system, fake_trigger), fake_trigger,
                          transcript_text="This is a test alert from ECRXN Dispatch.",
                          tz=current_app.config["TIMEZONE"])
    ok = sender.send(ctx)
    return jsonify(success=ok, message="Test posted to Facebook." if ok else sender.last_error, result=[]), (200 if ok else 400)


# ──────────────────────────────────────────────────────────────────────
# Facebook video backgrounds (image or clip behind the call audio)
#   system : /api/systems/<sys>/facebook/background                 GET | POST | DELETE
#   trigger: /api/systems/<sys>/triggers/<id>/facebook/background   GET | POST | DELETE
#   preview: .../facebook/preview   POST -> short MP4 made from the latest call's audio
# A trigger's background wins over the system's; with neither, the video is black.
# ──────────────────────────────────────────────────────────────────────
def _bg_info(name):
    return background_info(name)


def _bg_upload(prefix: str, store):
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify(success=False, message="Choose an image or video clip to upload.", result=[]), 400
    name, err = save_background(f.stream, f.filename, prefix)
    if err:
        return jsonify(success=False, message=err, result=[]), 400
    store(name)
    return jsonify(success=True, message="Background saved.", result=_bg_info(name)), 200


def _bg_file(name):
    p = media_path(name)
    if not p:
        abort(404, "No background.")
    return send_file(p, conditional=True, max_age=0)


def _preview(system: dict, background_name):
    """Render up to 15 s of the latest call over the background, shaped as a real post would be."""
    db = current_app.config["db"]
    row = db.execute_query("SELECT file_path FROM call_records WHERE radio_system_id = ? ORDER BY call_id DESC LIMIT 1",
                           (system["radio_system_id"],), fetch_mode="one")
    url = ((row.get("result") or {}) if row.get("success") else {}).get("file_path")
    if not url:
        return jsonify(success=False, message="A preview needs at least one call on this system to use its audio.", result=[]), 400
    mp3 = download_audio(url, route_logger)
    if not mp3:
        return jsonify(success=False, message="Couldn't load the latest call's audio.", result=[]), 400
    try:
        dur = audio_duration(mp3)
        vertical = dur is not None and dur <= REEL_MAX_S
        mp4, err = render_video(mp3, media_path(background_name), vertical=vertical,
                                min_seconds=REEL_MIN_S if vertical else 0.0, max_seconds=15, log=route_logger)
    finally:
        os.remove(mp3)
    if not mp4:
        return jsonify(success=False, message=err, result=[]), 400

    # a 15 s preview is small: read it and delete the temp file right away
    with open(mp4, "rb") as fh:
        data = io.BytesIO(fh.read())
    os.remove(mp4)
    resp = send_file(data, mimetype="video/mp4", max_age=0, download_name="preview.mp4")
    resp.headers["X-Video-Shape"] = "vertical" if vertical else "widescreen"
    return resp


@api_systems.route("/<int:radio_system_id>/facebook/background", methods=["GET", "POST", "DELETE"])
@login_required
@csrf_protect
def systems_facebook_background(radio_system_id: int):
    db = current_app.config["db"]
    system = _system_or_404(db, radio_system_id)
    current = (system.get("facebook") or {}).get("background")
    if request.method == "GET":
        return _bg_file(current)
    if request.method == "DELETE":
        remove_background(f"system_{radio_system_id}")
        set_system_facebook_background(db, radio_system_id, None)
        return jsonify(success=True, message="Background removed.", result=None), 200
    return _bg_upload(f"system_{radio_system_id}", lambda name: set_system_facebook_background(db, radio_system_id, name))


@api_systems.route("/<int:radio_system_id>/triggers/<int:alert_trigger_id>/facebook/background", methods=["GET", "POST", "DELETE"])
@login_required
@csrf_protect
def trigger_facebook_background(radio_system_id: int, alert_trigger_id: int):
    db = current_app.config["db"]
    _trigger_or_404(db, radio_system_id, alert_trigger_id)
    current = get_trigger_notifiers(db, alert_trigger_id)["facebook"].get("background")
    if request.method == "GET":
        return _bg_file(current)
    if request.method == "DELETE":
        remove_background(f"trigger_{alert_trigger_id}")
        set_trigger_facebook_background(db, alert_trigger_id, None)
        return jsonify(success=True, message="Background removed.", result=None), 200
    return _bg_upload(f"trigger_{alert_trigger_id}", lambda name: set_trigger_facebook_background(db, alert_trigger_id, name))


@api_systems.route("/<int:radio_system_id>/facebook/preview", methods=["POST"])
@login_required
@csrf_protect
def systems_facebook_preview(radio_system_id: int):
    system = _system_or_404(current_app.config["db"], radio_system_id)
    return _preview(system, (system.get("facebook") or {}).get("background"))


@api_systems.route("/<int:radio_system_id>/triggers/<int:alert_trigger_id>/facebook/preview", methods=["POST"])
@login_required
@csrf_protect
def trigger_facebook_preview(radio_system_id: int, alert_trigger_id: int):
    db = current_app.config["db"]
    _trigger_or_404(db, radio_system_id, alert_trigger_id)
    system = _system_or_404(db, radio_system_id)
    own = get_trigger_notifiers(db, alert_trigger_id)["facebook"].get("background")
    return _preview(system, own or (system.get("facebook") or {}).get("background"))
