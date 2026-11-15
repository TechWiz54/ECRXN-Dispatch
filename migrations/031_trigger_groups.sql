-- 031_trigger_groups.sql
-- Trigger groups (e.g. "Fire", "EMS"): each system can group its triggers, and a group sends its own
-- alert on each channel, once per call, naming the group's fired triggers. A trigger with its own
-- alert on a channel is left out of its group's alert on that channel.
BEGIN;

CREATE TABLE IF NOT EXISTS alert_trigger_groups
(
    alert_trigger_group_id INTEGER PRIMARY KEY AUTOINCREMENT,
    radio_system_id        INTEGER NOT NULL
        REFERENCES radio_systems (radio_system_id) ON DELETE CASCADE,
    group_name             TEXT    NOT NULL,
    group_color            TEXT    NOT NULL DEFAULT '#6C757D',
    UNIQUE (radio_system_id, group_name)
);

-- Same shape as alert_trigger_notifiers; Pushover is stored here too (as JSON) for groups.
CREATE TABLE IF NOT EXISTS alert_trigger_group_notifiers
(
    alert_trigger_group_id INTEGER NOT NULL
        REFERENCES alert_trigger_groups (alert_trigger_group_id) ON DELETE CASCADE,
    channel                TEXT    NOT NULL
        CHECK (channel IN ('telegram','discord','make','pushover','email','n8n','facebook')),
    enabled                INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
    config                 TEXT    NOT NULL DEFAULT '{}',
    PRIMARY KEY (alert_trigger_group_id, channel)
);

ALTER TABLE alert_triggers ADD COLUMN alert_trigger_group_id INTEGER DEFAULT NULL
    REFERENCES alert_trigger_groups (alert_trigger_group_id) ON DELETE SET NULL;

COMMIT;
