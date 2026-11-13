-- 027_trigger_system_channels.sql
-- Per trigger + channel: is this trigger included in the SYSTEM's alert on that channel?
-- No row = included (the default). Replaces alert_trigger_enable_discord/_make/_telegram/_n8n,
-- which are no longer read (only Telegram ever honoured them).
BEGIN;

CREATE TABLE IF NOT EXISTS alert_trigger_system_channels
(
    alert_trigger_id INTEGER NOT NULL
        REFERENCES alert_triggers (alert_trigger_id) ON DELETE CASCADE,
    channel          TEXT    NOT NULL
        CHECK (channel IN ('telegram','discord','make','pushover','email','n8n','facebook')),
    include          INTEGER NOT NULL DEFAULT 1 CHECK (include IN (0, 1)),
    PRIMARY KEY (alert_trigger_id, channel)
);

COMMIT;
