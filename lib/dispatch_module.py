# lib/dispatch_module.py
from __future__ import annotations

import logging
from typing import Optional

from icad_tone_detection import ToneDetectionResult

from lib.discord_module import DiscordSender
from lib.dispatch_text_render import build_context
from lib.make_module import MakeSender
from lib.n8n_module import N8nSender
from lib.pushover_module import PushoverSender
from lib.sqlite_module import SQLiteDatabase
from lib.system_module import get_systems  # you can remove this if you pass config in
from lib.email_module import EmailSender
from lib.facebook_module import FacebookSender
from lib.telegram_module import TelegramSender
from lib.trigger_notifier_module import dispatch_trigger_notifiers, get_system_includes
from lib.trigger_group_module import dispatch_group_notifiers, groups_for_triggers

module_logger = logging.getLogger('icad_dispatch.dispatch_module')


def _first_system_row(radio_system_config: dict) -> Optional[dict]:
    try:
        rows = (radio_system_config or {}).get("result") or []
        return rows[0] if rows else None
    except Exception:
        return None


def _dispatch_triggers(
        db: SQLiteDatabase,
        fired_trigger_data: list[dict],
        payload: dict,
        detect_result: ToneDetectionResult,
        *,
        radio_system_config: dict | None = None,
        transcript_text: str | None = None,
        transcript_segments: list[dict] | None = None,
        tz: str,
) -> None:
    """
    Send one consolidated notification (email/discord/telegram/...) for all fired triggers.

    Args:
      db: SQLite handle (not used for email)
      fired_trigger_data: list of trigger rows that fired
      payload: {'radio_system_id', 'talkgroup', 'duration_s', 'start_epoch_s', 'audio_url', ...}
      detect_result: ToneDetectionResult for tones summary
      radio_system_config: (optional) pass-through of system config you already have
      transcript_text / transcript_segments: (optional) if you already have transcription
      tz: REQUIRED IANA timezone name (validated at app startup),
        e.g. "America/New_York".
    """
    module_logger.info(
        "Dispatch Triggers → triggers=%s url=%s",
        [t['alert_trigger_name'] for t in fired_trigger_data],
        payload.get("audio_url"),
    )

    # Use the config you already have; fall back to a lookup if it's not provided.
    if radio_system_config is None:
        radio_system_config = get_systems(
            db,
            radio_system_id=payload["radio_system_id"],
            include_config=True
        )
    module_logger.debug("radio_system_config=%s", radio_system_config)
    module_logger.debug("payload=%s", payload)
    module_logger.debug("fired_trigger_data=%s", fired_trigger_data)

    system_row = _first_system_row(radio_system_config)
    if not system_row:
        module_logger.warning("No system row found; aborting dispatch")
        return

    # Each system channel alerts on the fired triggers that are included in it (a trigger can be
    # left out per channel on its Notifiers tab; new triggers are only in Pushover). The placeholder context is
    # built per distinct trigger set so {trigger_list} etc. only name the included triggers.
    includes = get_system_includes(db, [t["alert_trigger_id"] for t in fired_trigger_data if t.get("alert_trigger_id") is not None])
    ctx_cache: dict = {}

    def for_channel(channel: str):
        subset = [t for t in fired_trigger_data
                  if includes.get(int(t.get("alert_trigger_id") or 0), {}).get(channel, 1)]
        if not subset:
            module_logger.info("System %s: no fired trigger is included; skipping", channel)
            return None, None
        key = tuple(t.get("alert_trigger_id") for t in subset)
        if key not in ctx_cache:
            # provides {trigger_list}, {timestamp_24}, {timestamp_12}, {timestamp}, {transcript},
            # {transcript_segments}, {audio_url}, {stream_url}, {system_name}, etc.
            ctx_cache[key] = build_context(
                system_row,
                payload,
                subset,
                detect_result=detect_result,
                transcript_text=transcript_text,
                transcript_segments=transcript_segments,
                tz=tz,
            )
        return subset, ctx_cache[key]

    sid = system_row.get("radio_system_id")

    # ───────────────────────── Email ─────────────────────────
    try:
        emailer = EmailSender.from_system_row(system_row, logger=module_logger)
        subset, ctx = for_channel("email") if emailer.enabled else (None, None)
        if ctx:
            module_logger.info("Email dispatched: %s", emailer.send(ctx))
        elif not emailer.enabled:
            module_logger.debug("Email disabled for system_id=%s", sid)
    except Exception:
        module_logger.exception("Email dispatch failed")

    # ───────────────────────── Discord ─────────────────────────
    try:
        discord = DiscordSender.from_system_row(system_row, logger=module_logger)
        subset, ctx = for_channel("discord") if discord.enabled else (None, None)
        if ctx:
            module_logger.info("Discord dispatched: %s", discord.send(ctx))
        elif not discord.enabled:
            module_logger.debug("Discord disabled for system_id=%s", sid)
    except Exception:
        module_logger.exception("Discord dispatch failed")

    # ───────────────────────── Telegram ─────────────────────────
    try:
        telegram = TelegramSender.from_system_row(system_row, logger=module_logger)
        subset, ctx = for_channel("telegram") if telegram.enabled else (None, None)
        if ctx:
            # inclusion is decided above, so the sender's legacy per-trigger gate is not used
            module_logger.info("Telegram dispatched: %s", telegram.send(ctx))
        elif not telegram.enabled:
            module_logger.debug("Telegram disabled for system_id=%s", sid)
    except Exception:
        module_logger.exception("Telegram dispatch failed")

    # ───────────────────────── Pushover ─────────────────────────
    try:
        pushover = PushoverSender.from_system_row(system_row, fired_trigger_data, logger=module_logger)
        # 1) Systemwide channel (if enabled on the system), for the included triggers
        if pushover.sys.enabled:
            subset, ctx = for_channel("pushover")
            if ctx:
                module_logger.info("Pushover systemwide dispatched: %s", pushover.send_system(ctx))
        # 2) Per-trigger channels (each fired trigger w/ its own tokens) - always, independent of the above
        if any(t.enabled for t in pushover.trg):
            ctx_all = build_context(system_row, payload, fired_trigger_data, detect_result=detect_result,
                                    transcript_text=transcript_text, transcript_segments=transcript_segments, tz=tz)
            module_logger.info("Pushover per-trigger dispatched: %d", pushover.send_for_triggers(ctx_all))
    except Exception:
        module_logger.exception("Pushover dispatch failed")

    # ───────────────────────── Make ─────────────────────────
    try:
        make_sender = MakeSender.from_system_row(system_row, logger=module_logger)
        subset, ctx = for_channel("make") if make_sender.enabled else (None, None)
        if ctx:
            module_logger.info("Make webhook dispatched: %s", make_sender.send(ctx))
        elif not make_sender.enabled:
            module_logger.debug("Make webhook disabled for system_id=%s", sid)
    except Exception:
        module_logger.exception("Make dispatch failed")

    # ───────────────────────── n8n ─────────────────────────
    try:
        n8n = N8nSender.from_system_row(system_row, logger=module_logger)
        subset, ctx = for_channel("n8n") if n8n.enabled else (None, None)
        if ctx:
            ok = n8n.send(ctx, fired_trigger_data=subset, only_if_any_trigger_enabled=False)
            module_logger.info("n8n webhook dispatched: %s", ok)
        elif not n8n.enabled:
            module_logger.debug("n8n disabled for system_id=%s", sid)
    except Exception:
        module_logger.exception("n8n dispatch failed")

    # ───────────────────────── Facebook ─────────────────────────
    try:
        facebook = FacebookSender.from_system_row(system_row, logger=module_logger)
        subset, ctx = for_channel("facebook") if facebook.enabled else (None, None)
        if ctx:
            ok = facebook.send(ctx)
            module_logger.info("Facebook dispatched: %s", ok if ok else facebook.last_error)
        elif not facebook.enabled:
            module_logger.debug("Facebook disabled for system_id=%s", sid)
    except Exception:
        module_logger.exception("Facebook dispatch failed")

    # ─────────────── Per-trigger notifiers (each trigger's own channels) ───────────────
    try:
        groups = groups_for_triggers(db, fired_trigger_data)
    except Exception:
        module_logger.exception("Couldn't load the trigger groups")
        groups = {}
    try:
        n = dispatch_trigger_notifiers(
            db, system_row, payload, fired_trigger_data,
            detect_result=detect_result,
            transcript_text=transcript_text,
            transcript_segments=transcript_segments,
            tz=tz,
            groups=groups,
        )
        if n:
            module_logger.info("Per-trigger notifications sent: %d", n)
    except Exception:
        module_logger.exception("Per-trigger notifier dispatch failed")

    # ─────────────── Group notifiers (one alert per trigger group) ───────────────
    try:
        n = dispatch_group_notifiers(
            db, system_row, payload, fired_trigger_data,
            groups=groups,
            detect_result=detect_result,
            transcript_text=transcript_text,
            transcript_segments=transcript_segments,
            tz=tz,
        )
        if n:
            module_logger.info("Group notifications sent: %d", n)
    except Exception:
        module_logger.exception("Group notifier dispatch failed")
