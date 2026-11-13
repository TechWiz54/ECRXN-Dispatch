-- 026_trigger_notifiers_facebook.sql
-- Per-trigger notifiers (Telegram, Discord, Make, Email, n8n, Facebook) and system-level Facebook.
-- Pushover per-trigger settings stay in alert_trigger_pushover_settings.
BEGIN;

-- One row per trigger + channel. config is a JSON object with that channel's settings;
-- blank credentials / templates fall back to the system's settings at send time.
CREATE TABLE IF NOT EXISTS alert_trigger_notifiers
(
    alert_trigger_id INTEGER NOT NULL
        REFERENCES alert_triggers (alert_trigger_id) ON DELETE CASCADE,
    channel          TEXT    NOT NULL
        CHECK (channel IN ('telegram','discord','make','email','n8n','facebook')),
    enabled          INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
    config           TEXT    NOT NULL DEFAULT '{}',
    PRIMARY KEY (alert_trigger_id, channel)
);

CREATE TABLE IF NOT EXISTS radio_system_facebook_settings
(
    facebook_setting_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    radio_system_id       INTEGER NOT NULL UNIQUE
        REFERENCES radio_systems (radio_system_id) ON DELETE CASCADE,
    facebook_enabled      INTEGER NOT NULL DEFAULT 0 CHECK (facebook_enabled IN (0, 1)),
    facebook_page_id      TEXT    DEFAULT NULL,
    facebook_page_token   TEXT    DEFAULT NULL,
    -- 'post' = text post (audio link attached), 'video' = audio uploaded as a video
    facebook_post_type    TEXT    NOT NULL DEFAULT 'post' CHECK (facebook_post_type IN ('post','video')),
    facebook_message_body TEXT    DEFAULT '{trigger_list} Alert at {timestamp_24}

{transcript}'
);

INSERT INTO radio_system_facebook_settings (radio_system_id)
SELECT radio_system_id FROM radio_systems
WHERE radio_system_id NOT IN (SELECT radio_system_id FROM radio_system_facebook_settings);

COMMIT;
