# lib/trigger_notifier_module.py
"""
Per-trigger notifiers: a trigger can send its own alert through Telegram, Discord, Make, Email, n8n
and Facebook, separate from (and in addition to) the system-wide alert.
(Per-trigger Pushover lives in alert_trigger_pushover_settings and is sent by PushoverSender.)

Settings are stored in alert_trigger_notifiers as one JSON object per trigger + channel.
Where to send (channel ID, webhook URL, recipients, Page ID) must be set on the trigger;
credentials and message templates left blank fall back to the system's settings.

Sending reuses the existing senders by handing them a system-row-shaped dict.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from lib.discord_module import DiscordSender
from lib.dispatch_text_render import build_context
from lib.email_module import EmailSender
from lib.facebook_module import FacebookSender
from lib.make_module import MakeSender
from lib.n8n_module import N8nSender
from lib.pushover_module import PushoverSender
from lib.telegram_module import TelegramSender

module_logger = logging.getLogger("icad_dispatch.trigger_notifier_module")

CHANNELS = ("telegram", "discord", "make", "email", "n8n", "facebook")
# A trigger group's alert can also go to Pushover (a trigger's own Pushover lives in its own table)
GROUP_CHANNELS = ("telegram", "discord", "make", "pushover", "email", "n8n", "facebook")
# Channels a system can alert on (a trigger can be left out of each one)
SYSTEM_CHANNELS = ("telegram", "discord", "make", "pushover", "email", "n8n", "facebook")
# New triggers are in the system's alert on every channel (migrations 030 / 032 saved the older defaults
# for the triggers made before then)
SYSTEM_INCLUDE_DEFAULT = {c: 1 for c in SYSTEM_CHANNELS}
MAX_FIELDS = 25

# Allowed config keys per channel (anything else is dropped on save)
CHANNEL_FIELDS: Dict[str, Tuple[str, ...]] = {
    "telegram": ("channel_id", "bot_token", "message_body", "send_audio"),
    "discord":  ("webhook_url", "message", "embed_title", "embed_color", "embed_footer", "render_map", "attach_audio", "fields"),
    "make":     ("webhook_url", "api_key", "fields", "attach_audio"),
    "email":    ("recipients", "subject", "body", "attach_audio", "own_server", "smtp_hostname", "smtp_port",
                 "smtp_username", "smtp_password", "email_address_from", "email_text_from"),
    "n8n":      ("webhook_url", "jwt_passphrase", "attach_audio"),
    "facebook": ("page_id", "page_token", "post_type", "message_body"),
    "pushover": ("pushover_group_token", "pushover_app_token", "pushover_subject", "pushover_body", "pushover_sound"),
}

# Fields only the server sets (e.g. an uploaded file), kept when the form is saved
SERVER_FIELDS: Dict[str, Tuple[str, ...]] = {"facebook": ("background",)}

# The one field that says *where* the alert goes; required to enable the channel
DESTINATION: Dict[str, Tuple[str, str]] = {
    "telegram": ("channel_id", "Enter the Telegram channel ID."),
    "discord":  ("webhook_url", "Enter the Discord webhook URL."),
    "make":     ("webhook_url", "Enter the Make webhook URL."),
    "email":    ("recipients", "Enter at least one email address."),
    "n8n":      ("webhook_url", "Enter the n8n webhook URL."),
    "facebook": ("page_id", "Enter the Facebook Page ID."),
    "pushover": ("pushover_group_token", "Enter the Pushover group / user key."),
}

_BOOL_FIELDS = {"render_map", "attach_audio", "send_audio", "own_server"}

# Starter message templates. A trigger's own alert opens with the system's current template (or these,
# when the system has none) so there's always something sensible to edit.
DEFAULT_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "telegram": {"message_body": "{timestamp_readable}\n{trigger_list}\n{transcript}"},
    "discord":  {"embed_title": "🚨 Dispatch Alert", "embed_color": "#F04646", "embed_footer": "{timestamp_24}",
                 "fields": [{"label": "Departments", "value": "{trigger_list}", "inline": 0},
                            {"label": "Transcript", "value": "{transcript}", "inline": 0},
                            {"label": "Dispatch Audio", "value": "{audio_url}", "inline": 0}]},
    "make":     {"fields": [{"key": "system_name", "value": "{system_name}"},
                            {"key": "departments", "value": "{trigger_list}"},
                            {"key": "timestamp_local", "value": "{timestamp_local}"},
                            {"key": "transcript", "value": "{transcript}"},
                            {"key": "audio_url", "value": "{audio_url}"}]},
    "email":    {"subject": "Dispatch Alert",
                 "body": '{trigger_list} Alert at {timestamp_24}<br><br>{transcript}<br><br>'
                         '<a href="{audio_url}">Click for Dispatch Audio</a><br><br><a href="{stream_url}">Click Audio Stream</a>'},
    "facebook": {"message_body": "{trigger_list} Alert at {timestamp_24}\n\n{transcript}"},
    # a group's Pushover alert (a trigger's own Pushover has its own table and editor)
    "pushover": {"pushover_subject": "Dispatch Alert", "pushover_body": "{trigger_list}"},
}
_LIST_FIELDS = {"fields"}
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ─────────────────────────────────────────────────────────────────────────────
# Storage
# ─────────────────────────────────────────────────────────────────────────────
def _blank(channel: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {"enabled": 0}
    for k in CHANNEL_FIELDS[channel] + SERVER_FIELDS.get(channel, ()):
        out[k] = 0 if k in _BOOL_FIELDS else [] if k in _LIST_FIELDS else ""
    if channel == "facebook":
        out["post_type"] = "post"
    return out


def _system_templates(channel: str, system_row: Dict[str, Any]) -> Dict[str, Any]:
    """The system's message templates for a channel, in the trigger's field names."""
    s = (system_row or {}).get(channel) or {}
    if channel == "telegram":
        return {"message_body": str(s.get("message_body") or "").replace("\\n", "\n")}
    if channel == "discord":
        return {"embed_title": s.get("embed_title"), "embed_color": s.get("embed_color"),
                "embed_footer": s.get("embed_footer"),
                "fields": [{"label": f.get("field_label") or f.get("field_key") or "", "value": f.get("field_template") or "",
                            "inline": int(f.get("field_inline") or 0)}
                           for f in s.get("fields") or [] if int(f.get("field_enabled", 1) or 0)]}
    if channel == "make":
        return {"fields": [{"key": f.get("field_key") or "", "value": f.get("field_value") or ""}
                           for f in s.get("fields") or [] if int(f.get("field_enabled", 1) or 0)]}
    if channel == "email":
        return {"subject": s.get("email_alert_subject"), "body": s.get("email_alert_body")}
    if channel == "facebook":
        return {"message_body": s.get("message_body")}
    if channel == "pushover":
        return {"pushover_subject": s.get("subject") or s.get("pushover_subject"),
                "pushover_body": s.get("body") or s.get("pushover_body")}
    return {}


def fill_template_defaults(channels: Dict[str, Dict[str, Any]], system_row: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Fill a trigger's blank message fields with the system's templates (else the starters), for the editor.
    A blank field already meant "use the system's", so showing it filled in sends exactly the same thing."""
    for ch, defaults in DEFAULT_TEMPLATES.items():
        cfg = channels.get(ch)
        if cfg is None:
            continue
        sys_t = _system_templates(ch, system_row)
        for k, starter in defaults.items():
            if cfg.get(k) in (None, "", []):
                cfg[k] = sys_t.get(k) or starter
    return channels


def get_trigger_notifiers(db, alert_trigger_id: int) -> Dict[str, Dict[str, Any]]:
    """Return {channel: {"enabled": 0|1, ...config}} for every channel (unsaved channels are blank)."""
    return get_notifiers_for_triggers(db, [alert_trigger_id]).get(int(alert_trigger_id)) or {c: _blank(c) for c in CHANNELS}


def get_notifiers_for_triggers(db, trigger_ids: List[int]) -> Dict[int, Dict[str, Dict[str, Any]]]:
    ids = [int(i) for i in trigger_ids or []]
    out: Dict[int, Dict[str, Dict[str, Any]]] = {i: {c: _blank(c) for c in CHANNELS} for i in ids}
    if not ids:
        return out
    res = db.execute_query(
        f"SELECT alert_trigger_id, channel, enabled, config FROM alert_trigger_notifiers "
        f"WHERE alert_trigger_id IN ({','.join('?' for _ in ids)})",
        ids, fetch_mode="all",
    )
    if not res.get("success"):
        module_logger.error("Couldn't load trigger notifiers: %s", res.get("message"))
        return out
    for row in res.get("result") or []:
        ch = row["channel"]
        if ch not in CHANNELS:
            continue
        try:
            cfg = json.loads(row.get("config") or "{}") or {}
        except ValueError:
            cfg = {}
        merged = _blank(ch)
        merged.update({k: v for k, v in cfg.items() if k in CHANNEL_FIELDS[ch] + SERVER_FIELDS.get(ch, ())})
        if ch == "email" and "own_server" not in cfg:     # saved before the switch existed
            merged["own_server"] = 1 if cfg.get("smtp_hostname") else 0
        merged["enabled"] = int(row.get("enabled") or 0)
        out[int(row["alert_trigger_id"])][ch] = merged
    return out


def clean_channel_config(channel: str, data: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], int, Optional[str]]:
    """Validate incoming settings. Returns (config, enabled, error_message)."""
    if channel not in CHANNEL_FIELDS:
        return None, 0, f"Unknown notifier '{channel}'."
    data = data or {}
    cfg: Dict[str, Any] = {}
    for k in CHANNEL_FIELDS[channel]:
        v = data.get(k)
        if k in _LIST_FIELDS:
            fields, err = _clean_fields(channel, v)
            if err:
                return None, 0, err
            cfg[k] = fields
        elif k in _BOOL_FIELDS:
            if k not in data:           # not sent (older page / API caller): keep the default
                cfg[k] = _blank(channel)[k]
            else:
                cfg[k] = 1 if str(v).strip().lower() in ("1", "true", "on", "yes") else 0
        else:
            cfg[k] = "" if v is None else str(v).strip()

    enabled = 1 if str(data.get("enabled", 0)).strip().lower() in ("1", "true", "on", "yes") else 0

    for k in ("webhook_url",):
        if cfg.get(k) and not re.match(r"^https?://", cfg[k], re.I):
            return None, enabled, "The webhook URL must start with http:// or https://"

    if channel == "email":
        addrs = split_recipients(cfg.get("recipients", ""))
        bad = [a for a in addrs if not _EMAIL_RE.match(a)]
        if bad:
            return None, enabled, f"Not a valid email address: {bad[0]}"
        cfg["recipients"] = ", ".join(addrs)
        if cfg.get("own_server") and not cfg.get("smtp_hostname"):
            return None, enabled, "Enter the SMTP server, or switch off \"Use a different mail server\"."
        if cfg.get("smtp_port"):
            if not cfg["smtp_port"].isdigit() or not (0 < int(cfg["smtp_port"]) < 65536):
                return None, enabled, "SMTP port must be a number like 587."
    if channel == "facebook":
        cfg["post_type"] = cfg.get("post_type") if cfg.get("post_type") in ("post", "video") else "post"
    if channel == "discord" and cfg.get("embed_color") and not re.match(r"^#?[0-9a-fA-F]{6}$", cfg["embed_color"]):
        return None, enabled, "Embed color must be a hex color like #F04646."

    dest_key, dest_msg = DESTINATION[channel]
    if enabled and not cfg.get(dest_key):
        return None, enabled, dest_msg
    return cfg, enabled, None


def _clean_fields(channel: str, raw: Any) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Custom Make keys ({key, value}) or Discord embed fields ({label, value, inline}). Blank rows are dropped."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "[]")
        except ValueError:
            return [], "Couldn't read the fields."
    out: List[Dict[str, Any]] = []
    seen = set()
    for row in raw or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("key" if channel == "make" else "label") or "").strip()
        value = str(row.get("value") or "").strip()
        if not name and not value:
            continue
        if not name or not value:
            what = "key" if channel == "make" else "field"
            return [], f"Each {what} needs both a {'key' if channel == 'make' else 'label'} and a value."
        if len(name) > 256 or len(value) > 1024:
            return [], "A field is too long (names up to 256 characters, values up to 1024)."
        if channel == "make":
            if name.lower() in seen:
                return [], f"The key '{name}' is used twice."
            seen.add(name.lower())
            out.append({"key": name, "value": value})
        else:
            inline = str(row.get("inline")).strip().lower() in ("1", "true", "on", "yes")
            out.append({"label": name, "value": value, "inline": 1 if inline else 0})
    if len(out) > MAX_FIELDS:
        return [], f"Up to {MAX_FIELDS} fields."
    return out, None


def get_system_includes(db, trigger_ids: List[int]) -> Dict[int, Dict[str, int]]:
    """{trigger_id: {channel: 1|0}} - whether each trigger is in the system's alert on each channel.
    With no saved choice a trigger is in every one (migrations 030 / 032 saved the older defaults
    for triggers made before then)."""
    ids = [int(i) for i in trigger_ids or []]
    out = {i: {c: SYSTEM_INCLUDE_DEFAULT.get(c, 0) for c in SYSTEM_CHANNELS} for i in ids}
    if not ids:
        return out
    res = db.execute_query(
        f"SELECT alert_trigger_id, channel, include FROM alert_trigger_system_channels "
        f"WHERE alert_trigger_id IN ({','.join('?' for _ in ids)})",
        ids, fetch_mode="all",
    )
    for row in (res.get("result") or []) if res.get("success") else []:
        if row["channel"] in SYSTEM_CHANNELS:
            out[int(row["alert_trigger_id"])][row["channel"]] = int(row["include"] or 0)
    return out


def set_system_include(db, alert_trigger_id: int, channel: str, include: Any) -> Dict[str, Any]:
    if channel not in SYSTEM_CHANNELS:
        return {"success": False, "message": f"Unknown notifier '{channel}'.", "result": []}
    on = 1 if str(include).strip().lower() in ("1", "true", "on", "yes") else 0
    res = db.execute_commit(
        """
        INSERT INTO alert_trigger_system_channels (alert_trigger_id, channel, include) VALUES (?, ?, ?)
        ON CONFLICT(alert_trigger_id, channel) DO UPDATE SET include = excluded.include
        """,
        (int(alert_trigger_id), channel, on),
    )
    if not res.get("success"):
        return {"success": False, "message": res.get("message") or "Couldn't save.", "result": []}
    return {"success": True, "message": "Saved.", "result": {"include": on}}


def save_trigger_notifier(db, alert_trigger_id: int, channel: str, data: Dict[str, Any]) -> Dict[str, Any]:
    if channel not in CHANNELS:
        return {"success": False, "message": f"Unknown notifier '{channel}'.", "result": []}
    cfg, enabled, err = clean_channel_config(channel, data)
    if err:
        return {"success": False, "message": err, "result": []}
    current = get_trigger_notifiers(db, alert_trigger_id)[channel]
    for k in SERVER_FIELDS.get(channel, ()):
        cfg[k] = current.get(k) or ""
    res = db.execute_commit(
        """
        INSERT INTO alert_trigger_notifiers (alert_trigger_id, channel, enabled, config)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(alert_trigger_id, channel) DO UPDATE SET
            enabled = excluded.enabled, config = excluded.config
        """,
        (int(alert_trigger_id), channel, enabled, json.dumps(cfg)),
    )
    if not res.get("success"):
        return {"success": False, "message": res.get("message") or "Couldn't save.", "result": []}
    return {"success": True, "message": "Saved.", "result": get_trigger_notifiers(db, alert_trigger_id)[channel]}


def set_trigger_facebook_background(db, alert_trigger_id: int, name: Optional[str]) -> Dict[str, Any]:
    """Store (or clear) the file name of this trigger's Facebook video background, keeping its other settings."""
    current = get_trigger_notifiers(db, alert_trigger_id)["facebook"]
    enabled = int(current.pop("enabled", 0) or 0)
    current["background"] = name or ""
    res = db.execute_commit(
        """
        INSERT INTO alert_trigger_notifiers (alert_trigger_id, channel, enabled, config)
        VALUES (?, 'facebook', ?, ?)
        ON CONFLICT(alert_trigger_id, channel) DO UPDATE SET config = excluded.config
        """,
        (int(alert_trigger_id), enabled, json.dumps(current)),
    )
    return {"success": bool(res.get("success")), "message": res.get("message") or "Saved.", "result": []}


def split_recipients(raw: Any) -> List[str]:
    if isinstance(raw, list):
        items = raw
    else:
        items = re.split(r"[;,\s]+", str(raw or ""))
    seen, out = set(), []
    for a in items:
        a = str(a).strip()
        if a and a.lower() not in seen:
            seen.add(a.lower())
            out.append(a)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Building senders (trigger settings layered over the system's)
# ─────────────────────────────────────────────────────────────────────────────
def _pick(trig_val: Any, sys_val: Any) -> Any:
    return trig_val if trig_val not in (None, "") else sys_val


def layer_over_group(channel: str, cfg: Dict[str, Any], group_cfg: Any) -> Dict[str, Any]:
    """A trigger's own settings with its blank tokens / messages / background taken from its group's - or,
    given a list (its groups, top first), from the first group that has one. The system's are used after
    that, at send time. Where it goes and the on/off switches stay the trigger's."""
    if isinstance(group_cfg, list):
        for g in group_cfg:
            cfg = layer_over_group(channel, cfg, g)
        return cfg
    if not group_cfg:
        return cfg
    out = dict(cfg)
    dest = DESTINATION[channel][0]
    for k in CHANNEL_FIELDS[channel] + SERVER_FIELDS.get(channel, ()):
        if k == dest or k in _BOOL_FIELDS or k == "post_type":
            continue
        if out.get(k) in (None, "", []) and group_cfg.get(k) not in (None, "", []):
            out[k] = group_cfg[k]
    if channel == "email" and not out.get("own_server") and group_cfg.get("own_server"):
        for k in ("own_server", "smtp_hostname", "smtp_port", "smtp_username", "smtp_password",
                  "email_address_from", "email_text_from"):
            out[k] = group_cfg.get(k)
    return out


def _row_for(channel: str, cfg: Dict[str, Any], system_row: Dict[str, Any]) -> Dict[str, Any]:
    """A system-row-shaped dict holding just this channel, as the senders expect."""
    sys_cfg = (system_row or {}).get(channel) or {}
    row: Dict[str, Any] = {"radio_system_id": system_row.get("radio_system_id")}

    if channel == "telegram":
        row["telegram"] = {
            "enabled": 1,
            "channel_id": cfg.get("channel_id"),
            "bot_token": _pick(cfg.get("bot_token"), sys_cfg.get("bot_token")),
            "message_body": _pick(cfg.get("message_body"), sys_cfg.get("message_body")),
            "send_audio": int(cfg.get("send_audio") or 0),
        }
    elif channel == "discord":
        row["discord"] = {
            "enabled": 1,
            "webhook_url": cfg.get("webhook_url"),
            "embed_title": _pick(cfg.get("embed_title"), sys_cfg.get("embed_title")),
            "embed_color": _pick(cfg.get("embed_color"), sys_cfg.get("embed_color")),
            "embed_footer": _pick(cfg.get("embed_footer"), sys_cfg.get("embed_footer")),
            "render_map": int(cfg.get("render_map") or 0),
            "attach_audio": int(cfg.get("attach_audio") or 0),
            # the trigger's own embed fields, or the system's when it has none
            "fields": ([{"field_key": f"f{i}", "field_label": f["label"], "field_template": f["value"],
                         "field_inline": int(f.get("inline") or 0), "field_enabled": 1, "sort_order": i}
                        for i, f in enumerate(cfg["fields"])] if cfg.get("fields") else sys_cfg.get("fields") or []),
        }
    elif channel == "make":
        row["make"] = {
            "enabled": 1,
            "webhook_url": cfg.get("webhook_url"),
            "api_key": _pick(cfg.get("api_key"), sys_cfg.get("api_key")),
            "attach_audio": int(cfg.get("attach_audio") or 0),
            # the trigger's own JSON keys, or the system's when it has none
            "fields": ([{"field_key": f["key"], "field_value": f["value"], "field_enabled": 1, "sort_order": i}
                        for i, f in enumerate(cfg["fields"])] if cfg.get("fields") else sys_cfg.get("fields") or []),
        }
    elif channel == "email":
        own_server = bool(cfg.get("own_server")) and bool(cfg.get("smtp_hostname"))
        srv = cfg if own_server else {k: sys_cfg.get(k) for k in ("smtp_hostname", "smtp_port", "smtp_username", "smtp_password")}
        row["email"] = {
            "enabled": 1,
            "smtp_hostname": srv.get("smtp_hostname"),
            "smtp_port": srv.get("smtp_port") or (587 if own_server else None),
            "smtp_username": srv.get("smtp_username"),
            "smtp_password": srv.get("smtp_password"),
            "email_address_from": _pick(cfg.get("email_address_from") if own_server else None, sys_cfg.get("email_address_from")),
            "email_text_from": _pick(cfg.get("email_text_from") if own_server else None, sys_cfg.get("email_text_from")),
            "email_alert_subject": _pick(cfg.get("subject"), sys_cfg.get("email_alert_subject")),
            "email_alert_body": _pick(cfg.get("body"), sys_cfg.get("email_alert_body")),
            "recipients": split_recipients(cfg.get("recipients")),
            "attach_audio": int(cfg.get("attach_audio") or 0),
        }
    elif channel == "n8n":
        row["n8n"] = dict(sys_cfg, enabled=1,
                          webhook_url=cfg.get("webhook_url"),
                          jwt_passphrase=_pick(cfg.get("jwt_passphrase"), sys_cfg.get("jwt_passphrase")),
                          attach_audio=int(cfg.get("attach_audio") or 0))
    elif channel == "facebook":
        row["facebook"] = {
            "enabled": 1,
            "page_id": cfg.get("page_id"),
            "page_token": _pick(cfg.get("page_token"), sys_cfg.get("page_token")),
            "post_type": cfg.get("post_type") or "post",
            "message_body": _pick(cfg.get("message_body"), sys_cfg.get("message_body")),
            # this trigger's background, else the system's (else black)
            "background": _pick(cfg.get("background"), sys_cfg.get("background")),
        }
    elif channel == "pushover":
        row["pushover"] = {
            "enabled": 1,
            "group_token": cfg.get("pushover_group_token"),
            "app_token": _pick(cfg.get("pushover_app_token"), sys_cfg.get("app_token") or sys_cfg.get("pushover_app_token")),
            "subject": _pick(cfg.get("pushover_subject"), sys_cfg.get("subject") or sys_cfg.get("pushover_subject")),
            "body": _pick(cfg.get("pushover_body"), sys_cfg.get("body") or sys_cfg.get("pushover_body")),
            "sound": _pick(cfg.get("pushover_sound"), sys_cfg.get("sound") or sys_cfg.get("pushover_sound")),
        }
    return row


def _missing_setting(channel: str, row: Dict[str, Any]) -> Optional[str]:
    c = row.get(channel) or {}
    if channel == "telegram" and not c.get("bot_token"):
        return "No Telegram bot token - set one here or on the system's Telegram settings."
    if channel == "email" and not c.get("smtp_hostname"):
        return "No mail server - set one here or on the system's Email settings."
    if channel == "n8n" and not c.get("jwt_passphrase"):
        return "No n8n passphrase - set one here or on the system's n8n settings."
    if channel == "facebook" and not c.get("page_token"):
        return "No Facebook Page access token - set one here or on the system's Facebook settings."
    if channel == "pushover":
        if not c.get("app_token"):
            return "No Pushover app token - set one here or on the system's Pushover settings."
        return None if c.get("group_token") else DESTINATION["pushover"][1]
    dest_key, dest_msg = DESTINATION[channel]
    if channel == "email":
        return None if c.get("recipients") else dest_msg
    return None if c.get(dest_key) else dest_msg


class _Collect(logging.Handler):
    """Captures a sender's warnings so a failed send can say why."""
    def __init__(self):
        super().__init__(logging.WARNING)
        self.messages: List[str] = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def send_channel(channel: str, cfg: Dict[str, Any], system_row: Dict[str, Any], ctx: Dict[str, Any],
                 *, logger: Optional[logging.Logger] = None) -> Tuple[bool, str]:
    """Send one trigger-level notification. Returns (ok, message)."""
    row = _row_for(channel, cfg, system_row)
    missing = _missing_setting(channel, row)
    if missing:
        return False, missing

    log = logging.getLogger(f"icad_dispatch.trigger_notifier.{channel}")
    collector = _Collect()
    log.addHandler(collector)
    try:
        if channel == "telegram":
            ok = TelegramSender.from_system_row(row, logger=log).send(ctx)
        elif channel == "discord":
            ok = DiscordSender.from_system_row(row, logger=log).send(ctx, content=cfg.get("message") or None)
        elif channel == "make":
            ok = MakeSender.from_system_row(row, logger=log).send(ctx)
        elif channel == "email":
            ok = EmailSender.from_system_row(row, logger=log).send(ctx)
        elif channel == "n8n":
            ok = N8nSender.from_system_row(row, logger=log).send(ctx)
        elif channel == "pushover":
            ok = PushoverSender.from_system_row(row, logger=log).send_system(ctx)
        else:
            fb = FacebookSender.from_system_row(row, logger=log)
            ok = fb.send(ctx)
            if not ok and fb.last_error:
                collector.messages.append(fb.last_error)
    except Exception as e:
        (logger or module_logger).exception("Trigger %s notifier crashed", channel)
        return False, f"Error: {e}"
    finally:
        log.removeHandler(collector)

    if ok:
        return True, "Sent."
    return False, (collector.messages[-1] if collector.messages else "Not sent - check the settings.")


def trigger_context(system_row: Dict[str, Any], payload: Dict[str, Any], trigger: Dict[str, Any], *,
                    detect_result: Any = None, transcript_text: Optional[str] = None,
                    transcript_segments: Optional[list] = None, tz: str) -> Dict[str, Any]:
    """Placeholder context for one trigger: {trigger_list} is just this trigger, and its own stream URL wins."""
    row = dict(system_row)
    if trigger.get("alert_trigger_stream_url"):
        row["stream_url"] = trigger["alert_trigger_stream_url"]
    ctx = build_context(row, payload, [trigger], detect_result=detect_result,
                        transcript_text=transcript_text, transcript_segments=transcript_segments, tz=tz)
    ctx.setdefault("trigger_name", trigger.get("alert_trigger_name") or "")
    return ctx


def dispatch_trigger_notifiers(db, system_row: Dict[str, Any], payload: Dict[str, Any],
                               fired_trigger_data: List[Dict[str, Any]], *, detect_result: Any = None,
                               transcript_text: Optional[str] = None, transcript_segments: Optional[list] = None,
                               tz: str, groups: Optional[Dict[int, Dict[str, Any]]] = None) -> int:
    """Send every enabled trigger-level notifier for the fired triggers. Returns how many were sent.
    groups ({group id: {"group": row, "channels": {...}, "member_ids": {...}}}) fills a trigger's blank settings
    from its groups' (top group first)."""
    ids = [int(t["alert_trigger_id"]) for t in fired_trigger_data or [] if t.get("alert_trigger_id") is not None]
    if not ids:
        return 0
    all_cfg = get_notifiers_for_triggers(db, ids)
    sent = 0
    for trig in fired_trigger_data:
        cfgs = all_cfg.get(int(trig["alert_trigger_id"])) or {}
        active = [c for c in CHANNELS if int((cfgs.get(c) or {}).get("enabled") or 0)]
        if not active:
            continue
        mine = sorted((g for g in (groups or {}).values() if int(trig["alert_trigger_id"]) in g.get("member_ids", ())),
                      key=lambda g: (int(g["group"].get("sort_order") or 0), str(g["group"].get("group_name") or "").lower()))
        ctx = trigger_context(system_row, payload, trig, detect_result=detect_result, transcript_text=transcript_text,
                              transcript_segments=transcript_segments, tz=tz)
        ctx["group_name"] = ", ".join(str(g["group"].get("group_name") or "") for g in mine)
        for ch in active:
            cfg = layer_over_group(ch, cfgs[ch], [(g.get("channels") or {}).get(ch) for g in mine])
            ok, msg = send_channel(ch, cfg, system_row, ctx)
            module_logger.info("Trigger '%s' %s: %s", trig.get("alert_trigger_name"), ch, msg)
            sent += int(ok)
    return sent
