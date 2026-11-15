# lib/trigger_group_module.py
"""
Trigger groups: a system's triggers can be grouped (e.g. "Fire", "EMS"; a trigger can be in several), and each
group can send its own alert on Telegram, Discord, Make, Pushover, Email, n8n and Facebook (each group with its
own Facebook background).

When triggers fire, each group with fired triggers sends one alert per channel naming them in {trigger_list}
(and the group in {group_name}). A trigger with its own alert on a channel is left out of its groups' alerts on
that channel, and its blank settings are filled from its groups'. The system's own alerts are separate.

Groups have an order. When several groups fire on one call, the system's "together" setting decides, per
channel: each group sends its own ('separate'), one alert with the top group's settings naming every fired
trigger ('top'), or that with the system's "several groups" Facebook background ('image').

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
TOGETHER_MODES = ("separate", "top", "image")
DEFAULT_TOGETHER = "top"


def _ok(result: Any = None, message: str = "OK") -> Dict[str, Any]:
    return {"success": True, "message": message, "result": result}


def _err(message: str) -> Dict[str, Any]:
    return {"success": False, "message": message, "result": []}


def _blank_group(channel: str) -> Dict[str, Any]:
    if channel == "pushover":
        return {"enabled": 0, **{k: "" for k in CHANNEL_FIELDS["pushover"]}}
    return _blank(channel)


def _order_key(g: Dict[str, Any]):
    return int(g.get("sort_order") or 0), str(g.get("group_name") or "").lower()


# ─────────────────────────────────────────────────────────────────────────────
# Groups
# ─────────────────────────────────────────────────────────────────────────────
def get_groups(db, radio_system_id: int) -> List[Dict[str, Any]]:
    """The system's groups, top first, each with trigger_ids, trigger_count and the channels whose alert is on."""
    res = db.execute_query(
        "SELECT alert_trigger_group_id, radio_system_id, group_name, group_color, sort_order "
        "FROM alert_trigger_groups WHERE radio_system_id = ?",
        (int(radio_system_id),), fetch_mode="all",
    )
    groups = sorted((res.get("result") or []) if res.get("success") else [], key=_order_key)
    if not groups:
        return []
    ids = [int(g["alert_trigger_group_id"]) for g in groups]
    members = _members(db, ids)
    on = get_group_notifiers(db, ids)
    for g in groups:
        gid = int(g["alert_trigger_group_id"])
        g["trigger_ids"] = members.get(gid, [])
        g["trigger_count"] = len(g["trigger_ids"])
        g["channels_on"] = [c for c in GROUP_CHANNELS if int(((on.get(gid) or {}).get(c) or {}).get("enabled") or 0)]
    return groups


def _members(db, group_ids: List[int]) -> Dict[int, List[int]]:
    if not group_ids:
        return {}
    res = db.execute_query(
        f"SELECT alert_trigger_group_id, alert_trigger_id FROM alert_trigger_group_members "
        f"WHERE alert_trigger_group_id IN ({','.join('?' for _ in group_ids)}) ORDER BY alert_trigger_id",
        list(group_ids), fetch_mode="all",
    )
    out: Dict[int, List[int]] = {}
    for r in (res.get("result") or []) if res.get("success") else []:
        out.setdefault(int(r["alert_trigger_group_id"]), []).append(int(r["alert_trigger_id"]))
    return out


def get_group(db, radio_system_id: int, group_id: int) -> Optional[Dict[str, Any]]:
    return next((g for g in get_groups(db, radio_system_id) if int(g["alert_trigger_group_id"]) == int(group_id)), None)


def groups_of_trigger(db, radio_system_id: int, alert_trigger_id: int) -> List[Dict[str, Any]]:
    """The trigger's groups, top first."""
    return [g for g in get_groups(db, radio_system_id) if int(alert_trigger_id) in g["trigger_ids"]]


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
    """Add a group at the bottom of the order."""
    name, color, err = _clean_group(data)
    if err:
        return _err(err)
    if _name_taken(db, radio_system_id, name):
        return _err(f"There's already a group called “{name}”.")
    last = db.execute_query("SELECT COALESCE(MAX(sort_order), -1) AS m FROM alert_trigger_groups WHERE radio_system_id = ?",
                            (int(radio_system_id),), fetch_mode="one")
    top = (last.get("result") or {}).get("m") if last.get("success") else None
    order = (int(top) if top is not None else -1) + 1
    res = db.execute_commit(
        "INSERT INTO alert_trigger_groups (radio_system_id, group_name, group_color, sort_order) VALUES (?, ?, ?, ?)",
        (int(radio_system_id), name, color, order), return_row_id=True,
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
    """Delete a group; its triggers stay (in their other groups, if any)."""
    res = db.execute_commit("DELETE FROM alert_trigger_groups WHERE alert_trigger_group_id = ? AND radio_system_id = ?",
                            (int(group_id), int(radio_system_id)))
    if not res.get("success"):
        return _err(res.get("message") or "Couldn't delete the group.")
    remove_background(f"group_{int(group_id)}")
    return _ok(None, "Group deleted. Its triggers are kept.")


def reorder_groups(db, radio_system_id: int, group_ids: List[Any]) -> Dict[str, Any]:
    """Save the order (top first). Groups left out keep their place after the listed ones."""
    have = [int(g["alert_trigger_group_id"]) for g in get_groups(db, radio_system_id)]
    wanted = [int(i) for i in group_ids or [] if str(i).strip().isdigit() and int(i) in have]
    order = list(dict.fromkeys(wanted)) + [i for i in have if i not in wanted]
    for pos, gid in enumerate(order):
        db.execute_commit("UPDATE alert_trigger_groups SET sort_order = ? WHERE alert_trigger_group_id = ?", (pos, gid))
    return _ok(get_groups(db, radio_system_id), "Order saved.")


def set_member(db, radio_system_id: int, group_id: int, alert_trigger_id: int, member: bool) -> Dict[str, Any]:
    """Put a trigger in a group, or take it out (its other groups are unchanged)."""
    if not get_group(db, radio_system_id, group_id):
        return _err("That group isn't on this system.")
    if member:
        res = db.execute_commit("INSERT OR IGNORE INTO alert_trigger_group_members (alert_trigger_group_id, alert_trigger_id) "
                                "VALUES (?, ?)", (int(group_id), int(alert_trigger_id)))
    else:
        res = db.execute_commit("DELETE FROM alert_trigger_group_members WHERE alert_trigger_group_id = ? AND alert_trigger_id = ?",
                                (int(group_id), int(alert_trigger_id)))
    if not res.get("success"):
        return _err(res.get("message") or "Couldn't change the group.")
    return _ok({"group_ids": [g["alert_trigger_group_id"] for g in groups_of_trigger(db, radio_system_id, alert_trigger_id)]},
               "Added to the group." if member else "Taken out of the group.")


def set_trigger_groups(db, radio_system_id: int, alert_trigger_id: int, group_ids: List[Any]) -> Dict[str, Any]:
    """Make the trigger's groups exactly these (any of this system's groups; others are ignored)."""
    have = {int(g["alert_trigger_group_id"]) for g in get_groups(db, radio_system_id)}
    wanted = {int(i) for i in group_ids or [] if str(i).strip().isdigit()}
    if wanted - have:
        return _err("That group isn't on this system.")
    for gid in have:
        set_member(db, radio_system_id, gid, alert_trigger_id, gid in wanted)
    return _ok({"group_ids": [g["alert_trigger_group_id"] for g in groups_of_trigger(db, radio_system_id, alert_trigger_id)]},
               "Groups changed.")


# ─────────────────────────────────────────────────────────────────────────────
# When several groups fire together (per system)
# ─────────────────────────────────────────────────────────────────────────────
def get_together(db, radio_system_id: int) -> Dict[str, Any]:
    """{"together_mode", "channel_modes": {ch: mode}, "combined_background"} with defaults filled in."""
    res = db.execute_query("SELECT * FROM radio_system_group_settings WHERE radio_system_id = ?",
                           (int(radio_system_id),), fetch_mode="one")
    row = (res.get("result") or {}) if res.get("success") else {}
    try:
        modes = json.loads(row.get("channel_modes") or "{}") or {}
    except ValueError:
        modes = {}
    mode = row.get("together_mode") if row.get("together_mode") in TOGETHER_MODES else DEFAULT_TOGETHER
    return {"together_mode": mode,
            "channel_modes": {c: m for c, m in modes.items() if c in GROUP_CHANNELS and m in TOGETHER_MODES},
            "combined_background": row.get("combined_background") or None}


def _write_together(db, radio_system_id: int, mode: str, modes: Dict[str, str], background: Optional[str]):
    return db.execute_commit(
        """
        INSERT INTO radio_system_group_settings (radio_system_id, together_mode, channel_modes, combined_background)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(radio_system_id) DO UPDATE SET
            together_mode = excluded.together_mode, channel_modes = excluded.channel_modes,
            combined_background = excluded.combined_background
        """,
        (int(radio_system_id), mode, json.dumps(modes), background),
    )


def save_together(db, radio_system_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
    cur = get_together(db, radio_system_id)
    mode = str((data or {}).get("together_mode") or cur["together_mode"])
    if mode not in TOGETHER_MODES:
        return _err("Choose what happens when several groups fire together.")
    raw = (data or {}).get("channel_modes")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "{}")
        except ValueError:
            raw = {}
    modes = cur["channel_modes"] if raw is None else {
        c: m for c, m in (raw or {}).items() if c in GROUP_CHANNELS and m in TOGETHER_MODES and m != mode}
    res = _write_together(db, radio_system_id, mode, modes, cur["combined_background"])
    if not res.get("success"):
        return _err(res.get("message") or "Couldn't save.")
    return _ok(get_together(db, radio_system_id), "Saved.")


def set_combined_background(db, radio_system_id: int, name: Optional[str]) -> Dict[str, Any]:
    cur = get_together(db, radio_system_id)
    res = _write_together(db, radio_system_id, cur["together_mode"], cur["channel_modes"], name or None)
    return {"success": bool(res.get("success")), "message": res.get("message") or "Saved.", "result": []}


def mode_for(together: Dict[str, Any], channel: str) -> str:
    return (together.get("channel_modes") or {}).get(channel) or together.get("together_mode") or DEFAULT_TOGETHER


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
    """{group id: {"group": row, "channels": {...}, "member_ids": {fired trigger ids in it}}} for the groups
    the fired triggers are in."""
    tids = sorted({int(t["alert_trigger_id"]) for t in fired_trigger_data or [] if t.get("alert_trigger_id") is not None})
    if not tids:
        return {}
    res = db.execute_query(
        f"SELECT g.*, m.alert_trigger_id FROM alert_trigger_group_members m "
        f"JOIN alert_trigger_groups g ON g.alert_trigger_group_id = m.alert_trigger_group_id "
        f"WHERE m.alert_trigger_id IN ({','.join('?' for _ in tids)})",
        tids, fetch_mode="all",
    )
    out: Dict[int, Dict[str, Any]] = {}
    for r in (res.get("result") or []) if res.get("success") else []:
        gid = int(r["alert_trigger_group_id"])
        g = out.setdefault(gid, {"group": {k: v for k, v in r.items() if k != "alert_trigger_id"}, "member_ids": set()})
        g["member_ids"].add(int(r["alert_trigger_id"]))
    chans = get_group_notifiers(db, list(out))
    for gid, g in out.items():
        g["channels"] = chans.get(gid) or {}
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Sending
# ─────────────────────────────────────────────────────────────────────────────
def group_context(system_row: Dict[str, Any], payload: Dict[str, Any], groups: Any,
                  members: List[Dict[str, Any]], *, detect_result: Any = None, transcript_text: Optional[str] = None,
                  transcript_segments: Optional[list] = None, tz: str) -> Dict[str, Any]:
    """Placeholder context for a group alert: {trigger_list} names the fired triggers, {group_name} the group
    (several groups' names when one alert covers them)."""
    groups = groups if isinstance(groups, list) else [groups]
    row = dict(system_row)
    stream = next((t.get("alert_trigger_stream_url") for t in members if t.get("alert_trigger_stream_url")), None)
    if stream:
        row["stream_url"] = stream
    ctx = build_context(row, payload, members, detect_result=detect_result, transcript_text=transcript_text,
                        transcript_segments=transcript_segments, tz=tz)
    ctx["group_name"] = ", ".join(str(g.get("group_name") or "") for g in groups)
    ctx.setdefault("trigger_name", ", ".join(str(t.get("alert_trigger_name") or "") for t in members))
    return ctx


def _has_own(trigger: Dict[str, Any], channel: str, own: Dict[str, Dict[str, Any]]) -> bool:
    """Does this trigger send its own alert on this channel (so it's left out of its groups')?"""
    if channel == "pushover":
        return bool(int(trigger.get("enable_pushover") or 0) and trigger.get("pushover_group_token")
                    and trigger.get("pushover_app_token"))
    return bool(int((own.get(channel) or {}).get("enabled") or 0))


def plan_group_alerts(fired_trigger_data: List[Dict[str, Any]], groups: Dict[int, Dict[str, Any]],
                      own_all: Dict[int, Dict[str, Dict[str, Any]]], together: Dict[str, Any],
                      combined_background: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    The group alerts to send for one call: [{"channel", "groups": [rows, top first], "members": [triggers],
    "cfg": settings}]. Each group with this channel on and fired triggers (that don't send their own) counts;
    when several do, the channel's together mode decides between one alert each and one for all.
    """
    plan: List[Dict[str, Any]] = []
    ordered = sorted(groups.values(), key=lambda g: _order_key(g["group"]))
    for ch in GROUP_CHANNELS:
        active = []
        for g in ordered:
            cfg = (g.get("channels") or {}).get(ch) or {}
            if not int(cfg.get("enabled") or 0):
                continue
            subset = [t for t in fired_trigger_data
                      if int(t["alert_trigger_id"]) in g["member_ids"]
                      and not _has_own(t, ch, own_all.get(int(t["alert_trigger_id"])) or {})]
            if subset:
                active.append((g, cfg, subset))
            else:
                module_logger.info("Group '%s' %s: every fired trigger sends its own; skipping", g["group"].get("group_name"), ch)
        if not active:
            continue
        mode = mode_for(together, ch)
        if len(active) == 1 or mode == "separate":
            plan += [{"channel": ch, "groups": [g["group"]], "members": subset, "cfg": cfg} for g, cfg, subset in active]
            continue
        # one alert for all of them: the top group's settings, every fired trigger once (in firing order)
        top_cfg = dict(active[0][1])
        ids = {int(t["alert_trigger_id"]) for _g, _c, sub in active for t in sub}
        members = [t for t in fired_trigger_data if int(t["alert_trigger_id"]) in ids]
        if ch == "facebook" and mode == "image" and combined_background:
            top_cfg["background"] = combined_background
        plan.append({"channel": ch, "groups": [g["group"] for g, _c, _s in active], "members": members, "cfg": top_cfg})
    return plan


def dispatch_group_notifiers(db, system_row: Dict[str, Any], payload: Dict[str, Any],
                             fired_trigger_data: List[Dict[str, Any]], *, groups: Dict[int, Dict[str, Any]],
                             detect_result: Any = None, transcript_text: Optional[str] = None,
                             transcript_segments: Optional[list] = None, tz: str) -> int:
    """Send the group alerts for the fired triggers. Returns how many were sent."""
    if not groups:
        return 0
    own_all = get_notifiers_for_triggers(db, [int(t["alert_trigger_id"]) for t in fired_trigger_data])
    together = get_together(db, system_row.get("radio_system_id"))
    sent = 0
    for item in plan_group_alerts(fired_trigger_data, groups, own_all, together, together.get("combined_background")):
        ctx = group_context(system_row, payload, item["groups"], item["members"], detect_result=detect_result,
                            transcript_text=transcript_text, transcript_segments=transcript_segments, tz=tz)
        ok, msg = send_channel(item["channel"], item["cfg"], system_row, ctx)
        module_logger.info("Group '%s' %s: %s", ctx["group_name"], item["channel"], msg)
        sent += int(ok)
    return sent
