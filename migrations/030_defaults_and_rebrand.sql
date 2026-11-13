-- 030_defaults_and_rebrand.sql
-- 1) New default: a trigger is only in the system's Pushover alert until you switch others on.
--    Triggers made before this keep what they had (no row used to mean "included"), so save that.
-- 2) Rebrand: the old starter Telegram message ended with "iCAD Dispatch" and the email "from" name
--    was "iCAD Dispatch"; change them only where they were never edited.

INSERT OR IGNORE INTO alert_trigger_system_channels (alert_trigger_id, channel, include)
SELECT t.alert_trigger_id, c.channel, 1
FROM alert_triggers t
CROSS JOIN (SELECT 'telegram' AS channel UNION ALL SELECT 'discord' UNION ALL SELECT 'make'
            UNION ALL SELECT 'pushover' UNION ALL SELECT 'email' UNION ALL SELECT 'n8n'
            UNION ALL SELECT 'facebook') c;

UPDATE radio_system_telegram_settings
SET telegram_message_body = '{timestamp_readable}' || char(10) || '{trigger_list}' || char(10) || '{transcript}'
WHERE telegram_message_body = '{timestamp}\n{trigger_list}\n{transcript}\niCAD Dispatch';

UPDATE radio_system_email_settings
SET email_text_from = 'ECRXN Dispatch'
WHERE email_text_from = 'iCAD Dispatch';

