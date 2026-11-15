-- 032_group_members_and_order.sql
-- 1) A trigger can be in several groups: membership moves to its own table
--    (alert_triggers.alert_trigger_group_id from 031 is no longer used and is cleared).
-- 2) Groups have an order (sort_order): the top group wins when several fire on one call.
-- 3) Per system: what happens when several groups fire together, as a default plus per-notifier choices:
--      'separate' = each group sends its own alert
--      'top'      = one alert with the top group's settings, naming every fired trigger
--      'image'    = like 'top', but Facebook uses the system's "several groups" background
-- 4) New triggers are now in the system's alert on every channel; existing triggers keep what they had
--    (no saved choice used to mean "only Pushover"), so that is saved for them here.
BEGIN;

CREATE TABLE IF NOT EXISTS alert_trigger_group_members
(
    alert_trigger_group_id INTEGER NOT NULL
        REFERENCES alert_trigger_groups (alert_trigger_group_id) ON DELETE CASCADE,
    alert_trigger_id       INTEGER NOT NULL
        REFERENCES alert_triggers (alert_trigger_id) ON DELETE CASCADE,
    PRIMARY KEY (alert_trigger_group_id, alert_trigger_id)
);

INSERT OR IGNORE INTO alert_trigger_group_members (alert_trigger_group_id, alert_trigger_id)
SELECT alert_trigger_group_id, alert_trigger_id FROM alert_triggers WHERE alert_trigger_group_id IS NOT NULL;

UPDATE alert_triggers SET alert_trigger_group_id = NULL WHERE alert_trigger_group_id IS NOT NULL;

ALTER TABLE alert_trigger_groups ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0;

UPDATE alert_trigger_groups
SET sort_order = (SELECT COUNT(*) FROM alert_trigger_groups g2
                  WHERE g2.radio_system_id = alert_trigger_groups.radio_system_id
                    AND g2.group_name COLLATE NOCASE < alert_trigger_groups.group_name COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS radio_system_group_settings
(
    radio_system_id     INTEGER PRIMARY KEY
        REFERENCES radio_systems (radio_system_id) ON DELETE CASCADE,
    together_mode       TEXT    NOT NULL DEFAULT 'top' CHECK (together_mode IN ('separate', 'top', 'image')),
    channel_modes       TEXT    NOT NULL DEFAULT '{}',     -- {"facebook": "image", "discord": "separate", ...}
    combined_background TEXT    DEFAULT NULL               -- file in var/facebook_media
);

INSERT OR IGNORE INTO alert_trigger_system_channels (alert_trigger_id, channel, include)
SELECT t.alert_trigger_id, c.channel, CASE c.channel WHEN 'pushover' THEN 1 ELSE 0 END
FROM alert_triggers t
CROSS JOIN (SELECT 'telegram' AS channel UNION ALL SELECT 'discord' UNION ALL SELECT 'make'
            UNION ALL SELECT 'pushover' UNION ALL SELECT 'email' UNION ALL SELECT 'n8n'
            UNION ALL SELECT 'facebook') c;

COMMIT;
