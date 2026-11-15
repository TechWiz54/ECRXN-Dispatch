# routes/api/trigger_groups.py
"""
Trigger groups and their notifiers. Routes are attached to the /api/systems blueprint:

  /api/systems/<sys>/trigger-groups                                   GET | POST
  /api/systems/<sys>/trigger-groups/<gid>                             PATCH | DELETE
  /api/systems/<sys>/trigger-groups/<gid>/notifiers                   GET
  /api/systems/<sys>/trigger-groups/<gid>/notifiers/<channel>         PUT
  /api/systems/<sys>/trigger-groups/<gid>/notifiers/<channel>/test    POST
  /api/systems/<sys>/trigger-groups/<gid>/facebook/background         GET | POST | DELETE
  /api/systems/<sys>/trigger-groups/<gid>/facebook/preview            POST
  /api/systems/<sys>/triggers/<id>/group                              PUT   {alert_trigger_group_id}
"""
from __future__ import annotations

import logging

from flask import abort, current_app, jsonify, request

from lib.facebook_module import remove_background
from lib.trigger_group_module import (
    add_group, delete_group, get_group, get_group_notifiers, get_groups, group_context, save_group_notifier,
    set_group_facebook_background, set_trigger_group, update_group,
)
from lib.trigger_notifier_module import GROUP_CHANNELS, clean_channel_config, fill_template_defaults, send_channel
from routes.api.systems import api_systems
from routes.api.trigger_notifiers import (
    _bg_file, _bg_info, _bg_upload, _body, _preview, _system_or_404, _system_summary, _test_payload, _trigger_or_404,
)
from routes.decorators import csrf_protect, login_required

route_logger = logging.getLogger("icad_dispatch.trigger_groups")


def _group_or_404(db, radio_system_id: int, group_id: int) -> dict:
    g = get_group(db, radio_system_id, group_id)
    if not g:
        abort(404, "Group not found for this system.")
    return g


@api_systems.route("/<int:radio_system_id>/trigger-groups", methods=["GET", "POST"])
@login_required
@csrf_protect
def trigger_groups_collection(radio_system_id: int):
    db = current_app.config["db"]
    _system_or_404(db, radio_system_id)
    if request.method == "GET":
        return jsonify(success=True, message="OK", result=get_groups(db, radio_system_id)), 200
    res = add_group(db, radio_system_id, _body())
    return jsonify(res), (200 if res["success"] else 400)


@api_systems.route("/<int:radio_system_id>/trigger-groups/<int:group_id>", methods=["PATCH", "DELETE"])
@login_required
@csrf_protect
def trigger_group_item(radio_system_id: int, group_id: int):
    db = current_app.config["db"]
    _group_or_404(db, radio_system_id, group_id)
    res = (delete_group(db, radio_system_id, group_id) if request.method == "DELETE"
           else update_group(db, radio_system_id, group_id, _body()))
    return jsonify(res), (200 if res["success"] else 400)


@api_systems.route("/<int:radio_system_id>/triggers/<int:alert_trigger_id>/group", methods=["PUT", "PATCH"])
@login_required
@csrf_protect
def trigger_set_group(radio_system_id: int, alert_trigger_id: int):
    db = current_app.config["db"]
    _trigger_or_404(db, radio_system_id, alert_trigger_id)
    res = set_trigger_group(db, radio_system_id, alert_trigger_id, _body().get("alert_trigger_group_id"))
    return jsonify(res), (200 if res["success"] else 400)


@api_systems.route("/<int:radio_system_id>/trigger-groups/<int:group_id>/notifiers", methods=["GET"])
@login_required
def trigger_group_notifiers_get(radio_system_id: int, group_id: int):
    db = current_app.config["db"]
    group = _group_or_404(db, radio_system_id, group_id)
    system = _system_or_404(db, radio_system_id)
    channels = fill_template_defaults(get_group_notifiers(db, [group_id])[group_id], system)
    return jsonify(success=True, message="OK", result={
        "group": group,
        "channels": channels,
        "facebook_background": _bg_info(channels["facebook"].get("background")),
        "system": _system_summary(system),
    }), 200


@api_systems.route("/<int:radio_system_id>/trigger-groups/<int:group_id>/notifiers/<channel>", methods=["PUT", "PATCH"])
@login_required
@csrf_protect
def trigger_group_notifier_save(radio_system_id: int, group_id: int, channel: str):
    db = current_app.config["db"]
    _group_or_404(db, radio_system_id, group_id)
    if channel not in GROUP_CHANNELS:
        abort(404, "Unknown notifier.")
    res = save_group_notifier(db, group_id, channel, _body())
    return jsonify(res), (200 if res["success"] else 400)


@api_systems.route("/<int:radio_system_id>/trigger-groups/<int:group_id>/notifiers/<channel>/test", methods=["POST"])
@login_required
@csrf_protect
def trigger_group_notifier_test(radio_system_id: int, group_id: int, channel: str):
    """Send a test of the group's alert with the settings in the request (so unsaved edits can be tried)."""
    db = current_app.config["db"]
    group = _group_or_404(db, radio_system_id, group_id)
    system = _system_or_404(db, radio_system_id)
    if channel not in GROUP_CHANNELS:
        abort(404, "Unknown notifier.")
    cfg, _enabled, err = clean_channel_config(channel, dict(_body(), enabled=1))
    if err:
        return jsonify(success=False, message=err, result=[]), 400
    if channel == "facebook":
        cfg["background"] = get_group_notifiers(db, [group_id])[group_id]["facebook"].get("background") or ""

    member = {"alert_trigger_name": f"[TEST] {group['group_name']}"}
    ctx = group_context(system, _test_payload(db, system, member), group, [member],
                        transcript_text="This is a test alert from ECRXN Dispatch.", tz=current_app.config["TIMEZONE"])
    ctx["is_test"] = True
    if channel == "telegram" and int(cfg.get("send_audio") or 0) and not ctx.get("audio_url"):
        return jsonify(success=False, message="A voice-message test needs at least one call on this system "
                                              "(or turn off \"Send the audio\" to test a text message).", result=[]), 400

    ok, msg = send_channel(channel, cfg, system, ctx)
    route_logger.info("Group %s test %s: %s", group_id, channel, msg)
    name = {"n8n": "n8n"}.get(channel, channel.capitalize())
    return jsonify(success=ok, message=(f"Test sent to {name}." if ok else msg), result=[]), (200 if ok else 400)


@api_systems.route("/<int:radio_system_id>/trigger-groups/<int:group_id>/facebook/background", methods=["GET", "POST", "DELETE"])
@login_required
@csrf_protect
def trigger_group_facebook_background(radio_system_id: int, group_id: int):
    db = current_app.config["db"]
    _group_or_404(db, radio_system_id, group_id)
    current = get_group_notifiers(db, [group_id])[group_id]["facebook"].get("background")
    if request.method == "GET":
        return _bg_file(current)
    if request.method == "DELETE":
        remove_background(f"group_{group_id}")
        set_group_facebook_background(db, group_id, None)
        return jsonify(success=True, message="Background removed.", result=None), 200
    return _bg_upload(f"group_{group_id}", lambda name: set_group_facebook_background(db, group_id, name))


@api_systems.route("/<int:radio_system_id>/trigger-groups/<int:group_id>/facebook/preview", methods=["POST"])
@login_required
@csrf_protect
def trigger_group_facebook_preview(radio_system_id: int, group_id: int):
    db = current_app.config["db"]
    _group_or_404(db, radio_system_id, group_id)
    system = _system_or_404(db, radio_system_id)
    own = get_group_notifiers(db, [group_id])[group_id]["facebook"].get("background")
    return _preview(system, own or (system.get("facebook") or {}).get("background"))
