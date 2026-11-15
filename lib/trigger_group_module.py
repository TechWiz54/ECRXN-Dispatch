# lib/trigger_group_module.py
"""
Trigger groups: a system's triggers can be grouped (e.g. "Fire", "EMS"), and each group can send its own
alert on Telegram, Discord, Make, Pushover, Email, n8n and Facebook (each with its own Facebook background).

When triggers fire, each group sends one alert per channel naming the group's fired triggers in
{trigger_list} (and the group in {group_name}). A trigger with its own alert on a channel is left out of
its group's alert on that channel, and its blank settings are filled from the group's.
The system's own alerts are separate and unchanged.

Settings are stored in alert_trigger_group_notifiers like trigger notifiers (one JSON object per channel).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from lib.dispatch_text_render import build_context
from lib.facebook_module import remove_background
from lib.trigger_notifier_module import (
    CHANNEL_FIELDS, GROUP_CHANNELS, SERVER_FIELDS, _blank, clean_channel_config, get_notifiers_for_triggers,
    send_channel,
)

module_logger = logging.getLogger("icad_dispatch.trigger_group_module")

MAX_NAME = 60
DEFAULT_COLOR = "#6C757D"
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _ok(result: Any = None, message: str = "OK") -> Dict[str, Any]:
    return {"success": True, "message": message, "result": result}


def _err(message: str) -> Dict[str, Any]:
    return {"success": False, "message": message, "result": []}


def _blank_group(channel: str) -> Dict[str, Any]:
    if channel == "pushover":
        return {"enabled": 0, **{k: "" for k in CHANNEL_FIELDS["pushover"]}}
    return _blank(channel)


# ─────────────────────────────────────────────────────────────────────────────
# Groups
# ─────────────────────────────────────────────────────────────────────────────
def get_groups(db, radio_system_id: int) -> List[Dict[str, Any]]:
    """The system's groups by name, each with trigger_count and the channels whose alert is on."""
    res = db.execute_query(
        """
        SELECT g.alert_trigger_group_id, g.radio_system_id, g.group_name, g.group_color,
               (SELECT COUNT(*) FROM alert_triggers t WHERE t.alert_trigger_group_id = g.alert_trigger_group_id)
                   AS trigger_count
        FROM alert_trigger_groups g
        WHERE g.radio_system_id = ?
        ORDER BY g.group_name COLLATE NOCASE
        """,
        (int(radio_system_id),), fetch_mode="all",
    )
    groups = (res.get("result") or []) if res.get("success") else []
    if not groups:
        return []
    on = get_group_notifiers(db, [g["alert_trigger_group_id"] for g in groups])
    for g in groups:
        chans = on.get(int(g["alert_trigger_group_id"])) or {}
        g["channels_on"] = [c for c in GROUP_CHANNELS if int((chans.get(c) or {}).get("enabled") or 0)]
    return groups


def get_group(db, radio_system_id: int, group_id: int) -> Optional[Dict[str, Any]]:
    return next((g for g in get_groups(db, radio_system_id) if int(g["alert_trigger_group_id"]) == int(group_id)), None)


def _clean_group(data: Dict[str, Any]) -> tuple:
    name = re.sub(r"\s+", " ", str((data or {}).get("group_name") or "")).strip()
    if not name:
        return None, None, "Enter a name for the group."
    if len(name) > MAX_NAME:
        return None, None, f"Group names can be up to {MAX_NAME} characters."
    color = str((data or {}).get("group_color") or DEFAULT_COLOR).strip()
    if not color.startswith("#"):
        color = "#" + color
    if not _COLOR_RE.match(color):
        return None, None, "The color must be a hex color like #D9534F."
    return name, color.upper(), None


def _name_taken(db, radio_system_id: int, name: str, except_id: Optional[int] = None) -> bool:
    res = db.execute_query(
        "SELECT alert_trigger_group_id FROM alert_trigger_groups WHERE radio_system_id = ? AND group_name = ? COLLATE NOCASE",
        (int(radio_system_id), name), fetch_mode="all",
    )
    return any(int(r["alert_trigger_group_id"]) != int(except_id or 0) for r in (res.get("result") or []))


def add_group(db, radio_system_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
    name, color, err = _clean_group(data)
    if err:
        return _err(err)
    if _name_taken(db, radio_system_id, name):
        return _err(f"There's already a group called “{name}”.")
    res = db.execute_commit(
        "INSERT INTO alert_trigger_groups (radio_system_id, group_name, group_color) VALUES (?, ?, ?)",
        (int(radio_system_id), name, color), return_row_id=True,
    )
    if not res.get("success"):
        return _err(res.get("message") or "Couldn't add the group.")
    return _ok(get_group(db, radio_system_id, int(res["result"])), "Group added.")


def update_group(db, radio_system_id: int, group_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
    name, color, err = _clean_group(data)
    if err:
        return _err(err)
    if _name_taken(db, radio_system_id, name, except_id=group_id):
        return _err(f"There's already a group called “{name}”.")
    res = db.execute_commit(
        "UPDATE alert_trigger_groups SET group_name = ?, group_color = ? WHERE alert_trigger_group_id = ? AND radio_system_id = ?",
        (name, color, int(group_id), int(radio_system_id)),
    )
    if not res.get("success"):
        return _err(res.get("message") or "Couldn't save the group.")
    return _ok(get_group(db, radio_system_id, group_id), "Group saved.")


def delete_group(db, radio_system_id: int, group_id: int) -> Dict[str, Any]:
    """Delete a group; its triggers stay, just without a group."""
    db.execute_commit("UPDATE alert_triggers SET alert_trigger_group_id = NULL WHERE alert_trigger_group_id = ?",
                      (int(group_id),))
    res = db.execute_commit("DELETE FROM alert_trigger_groups WHERE alert_trigger_group_id = ? AND radio_system_id = ?",
                            (int(group_id), int(radio_system_id)))
    if not res.get("success"):
        return _err(res.get("message") or "Couldn't delete the group.")
    remove_background(f"group_{int(group_id)}")
    return _ok(None, "Group deleted. Its triggers are kept, without a group.")


def set_trigger_group(db, radio_system_id: int, alert_trigger_id: int, group_id: Any) -> Dict[str, Any]:
    """Put a trigger in one of its system's groups, or in none (group_id blank / 0)."""
    gid = int(group_id) if str(group_id or "").strip().isdigit() and int(group_id) > 0 else None
    if gid is not None and not get_group(db, radio_system_id, gid):
        return _err("That group isn't on this system.")
    res = db.execute_commit("UPDATE alert_triggers SET alert_trigger_group_id = ? WHERE alert_trigger_id = ? AND radio_system_id = ?",
                            (gid, int(alert_trigger_id), int(radio_system_id)))
    if not res.get("success"):
        return _err(res.get("message") or "Couldn't change the group.")
    return _ok({"alert_trigger_group_id": gid}, "Group changed.")


# ─────────────────────────────────────────────────────────────────────────────
# Group notifiers
# ─────────────────────────────────────────────────────────────────────────────
def get_group_notifiers(db, group_ids: List[int]) -> Dict[int, Dict[str, Dict[str, Any]]]:
    """{group id: {channel: {"enabled": 0|1, ...config}}} for every channel (unsaved channels are blank)."""
    ids = [int(i) for i in group_ids or []]
    out = {i: {c: _blank_group(c) for c in GROUP_CHANNELS} for i in ids}
    if not ids:
        return out
    res = db.execute_query(
        f"SELECT alert_trigger_group_id, channel, enabled, config FROM alert_trigger_group_notifiers "
        f"WHERE alert_trigger_group_id IN ({','.join('?' for _ in ids)})",
        ids, fetch_mode="all",
    )
    for row in (res.get("result") or []) if res.get("success") else []:
        ch = row["channel"]
        if ch not in GROUP_CHANNELS:
            continue
        try:
            cfg = json.loads(row.get("config") or "{}") or {}
        except ValueError:
            cfg = {}
        merged = _blank_group(ch)
        merged.update({k: v for k, v in cfg.items() if k in CHANNEL_FIELDS[ch] + SERVER_FIELDS.get(ch, ())})
        if ch == "email" and "own_server" not in cfg:
            merged["own_server"] = 1 if cfg.get("smtp_hostname") else 0
        merged["enabled"] = int(row.get("enabled") or 0)
        out[int(row["alert_trigger_group_id"])][ch] = merged
    return out


def _write_group_notifier(db, group_id: int, channel: str, enabled: int, cfg: Dict[str, Any], *, keep_enabled=False):
    return db.execute_commit(
        f"""
        INSERT INTO alert_trigger_group_notifiers (alert_trigger_group_id, channel, enabled, config)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(alert_trigger_group_id, channel) DO UPDATE SET
            {'' if keep_enabled else 'enabled = excluded.enabled,'} config = excluded.config
        """,
        (int(group_id), channel, int(enabled), json.dumps(cfg)),
    )


def save_group_notifier(db, group_id: int, channel: str, data: Dict[str, Any]) -> Dict[str, Any]:
    if channel not in GROUP_CHANNELS:
        return _err(f"Unknown notifier '{channel}'.")
    cfg, enabled, err = clean_channel_config(channel, data)
    if err:
        return _err(err)
    current = get_group_notifiers(db, [group_id])[int(group_id)][channel]
    for k in SERVER_FIELDS.get(channel, ()):
        cfg[k] = current.get(k) or ""
    res = _write_group_notifier(db, group_id, channel, enabled, cfg)
    if not res.get("success"):
        return _err(res.get("message") or "Couldn't save.")
    return _ok(get_group_notifiers(db, [group_id])[int(group_id)][channel], "Saved.")


def set_group_facebook_background(db, group_id: int, name: Optional[str]) -> Dict[str, Any]:
    current = get_group_notifiers(db, [group_id])[int(group_id)]["facebook"]
    enabled = int(current.pop("enabled", 0) or 0)
    current["background"] = name or ""
    res = _write_group_notifier(db, group_id, "facebook", enabled, current, keep_enabled=True)
    return {"success": bool(res.get("success")), "message": res.get("message") or "Saved.", "result": []}


def groups_for_triggers(db, fired_trigger_data: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    """{group id: {"group": row, "channels": {...}}} for the groups the fired triggers are in."""
    gids = sorted({int(t["alert_trigger_group_id"]) for t in fired_trigger_data or [] if t.get("alert_trigger_group_id")})
    if not gids:
        return {}
    res = db.execute_query(
        f"SELECT * FROM alert_trigger_groups WHERE alert_trigger_group_id IN ({','.join('?' for _ in gids)})",
        gids, fetch_mode="all",
    )
    rows = {int(r["alert_trigger_group_id"]): r for r in (res.get("result") or [])} if res.get("success") else {}
    chans = get_group_notifiers(db, list(rows))
    return {gid: {"group": row, "channels": chans.get(gid) or {}} for gid, row in rows.items()}


# ─────────────────────────────────────────────────────────────────────────────
# Sending
# ─────────────────────────────────────────────────────────────────────────────
def group_context(system_row: Dict[str, Any], payload: Dict[str, Any], group: Dict[str, Any],
                  members: List[Dict[str, Any]], *, detect_result: Any = None, transcript_text: Optional[str] = None,
                  transcript_segments: Optional[list] = None, tz: str) -> Dict[str, Any]:
    """Placeholder context for a group's alert: {trigger_list} names its fired triggers, {group_name} the group."""
    row = dict(system_row)
    stream = next((t.get("alert_trigger_stream_url") for t in members if t.get("alert_trigger_stream_url")), None)
    if stream:
        row["stream_url"] = stream
    ctx = build_context(row, payload, members, detect_result=detect_result, transcript_text=transcript_text,
                        transcript_segments=transcript_segments, tz=tz)
    ctx["group_name"] = group.get("group_name") or ""
    ctx.setdefault("trigger_name", ", ".join(str(t.get("alert_trigger_name") or "") for t in members))
    return ctx


def _has_own(trigger: Dict[str, Any], channel: str, own: Dict[str, Dict[str, Any]]) -> bool:
    """Does this trigger send its own alert on this channel (so it's left out of its group's)?"""
    if channel == "pushover":
        return bool(int(trigger.get("enable_pushover") or 0) and trigger.get("pushover_group_token")
                    and trigger.get("pushover_app_token"))
    return bool(int((own.get(channel) or {}).get("enabled") or 0))


def dispatch_group_notifiers(db, system_row: Dict[str, Any], payload: Dict[str, Any],
                             fired_trigger_data: List[Dict[str, Any]], *, groups: Dict[int, Dict[str, Any]],
                             detect_result: Any = None, transcript_text: Optional[str] = None,
                             transcript_segments: Optional[list] = None, tz: str) -> int:
    """One alert per group and channel for the fired triggers in each group. Returns how many were sent."""
    if not groups:
        return 0
    own_all = get_notifiers_for_triggers(db, [int(t["alert_trigger_id"]) for t in fired_trigger_data])
    sent = 0
    for gid, g in groups.items():
        members = [t for t in fired_trigger_data if int(t.get("alert_trigger_group_id") or 0) == gid]
        for ch in GROUP_CHANNELS:
            cfg = (g.get("channels") or {}).get(ch) or {}
            if not int(cfg.get("enabled") or 0):
                continue
            subset = [t for t in members if not _has_own(t, ch, own_all.get(int(t["alert_trigger_id"])) or {})]
            if not subset:
                module_logger.info("Group '%s' %s: every fired trigger sends its own; skipping",
                                   g["group"].get("group_name"), ch)
                continue
            ctx = group_context(system_row, payload, g["group"], subset, detect_result=detect_result,
                                transcript_text=transcript_text, transcript_segments=transcript_segments, tz=tz)
            ok, msg = send_channel(ch, cfg, system_row, ctx)
            module_logger.info("Group '%s' %s: %s", g["group"].get("group_name"), ch, msg)
            sent += int(ok)
    return sent
