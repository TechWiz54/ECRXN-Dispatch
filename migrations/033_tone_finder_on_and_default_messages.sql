-- 033_tone_finder_on_and_default_messages.sql
-- 1) Tone Finder on for every system. Systems made before 1.4.2 started with it off, so calls with tones
--    weren't kept and the dashboard stayed empty until it was found and switched on.
-- 2) Message boxes left blank on older systems get the same starter messages (with placeholders) a new
--    system gets, so every alert says something useful without typing placeholders in.
--    Only blank ones change; anything already written is kept.
BEGIN;

UPDATE radio_system_tone_settings SET tone_finder_enabled = 1 WHERE tone_finder_enabled IS NOT 1;

UPDATE radio_system_email_settings SET email_alert_subject = 'Dispatch Alert'
WHERE email_alert_subject IS NULL OR TRIM(email_alert_subject) = '';
UPDATE radio_system_email_settings
SET email_alert_body = '{trigger_list} Alert at {timestamp_24}<br><br>{transcript}<br><br><a href="{audio_url}">Click for Dispatch Audio</a><br><br><a href="{stream_url}">Click Audio Stream</a>'
WHERE email_alert_body IS NULL OR TRIM(email_alert_body) = '';
UPDATE radio_system_email_settings SET email_text_from = 'ECRXN Dispatch'
WHERE email_text_from IS NULL OR TRIM(email_text_from) = '';

UPDATE radio_system_pushover_settings SET pushover_subject = 'Dispatch Alert'
WHERE pushover_subject IS NULL OR TRIM(pushover_subject) = '';
UPDATE radio_system_pushover_settings
SET pushover_body = '<font color="red"><b>{trigger_list}</b></font><br><br><a href="{audio_url}">Click for Dispatch Audio</a><br><br><a href="{stream_url}">Click Audio Stream</a>'
WHERE pushover_body IS NULL OR TRIM(pushover_body) = '';

UPDATE radio_system_telegram_settings SET telegram_message_body = '{timestamp_readable}\n{trigger_list}\n{transcript}'
WHERE telegram_message_body IS NULL OR TRIM(telegram_message_body) = '';

UPDATE radio_system_discord_settings SET discord_embed_title = '🚨 Dispatch Alert'
WHERE discord_embed_title IS NULL OR TRIM(discord_embed_title) = '';
UPDATE radio_system_discord_settings SET discord_embed_color = '#F04646'
WHERE discord_embed_color IS NULL OR TRIM(discord_embed_color) = '';
UPDATE radio_system_discord_settings SET discord_embed_footer = '{timestamp_24}'
WHERE discord_embed_footer IS NULL OR TRIM(discord_embed_footer) = '';

UPDATE radio_system_facebook_settings SET facebook_message_body = '{trigger_list} Alert at {timestamp_24}' || char(10) || char(10) || '{transcript}'
WHERE facebook_message_body IS NULL OR TRIM(facebook_message_body) = '';

-- Discord embed fields / Make keys for systems that have none
INSERT INTO radio_system_discord_embed_fields
    (discord_setting_id, field_key, field_label, field_template, field_inline, field_enabled, sort_order)
SELECT d.discord_setting_id, f.k, f.l, f.t, 0, 1, f.o
FROM radio_system_discord_settings d
CROSS JOIN (SELECT 'departments' AS k, 'Departments' AS l, '{trigger_list}' AS t, 10 AS o
            UNION ALL SELECT 'transcript', 'Transcript', '{transcript}', 20
            UNION ALL SELECT 'audio', 'Dispatch Audio', '{audio_url}', 30) f
WHERE NOT EXISTS (SELECT 1 FROM radio_system_discord_embed_fields e WHERE e.discord_setting_id = d.discord_setting_id);

INSERT INTO radio_system_make_payload_fields (make_setting_id, field_key, field_value, field_enabled)
SELECT m.make_setting_id, f.k, f.v, 1
FROM radio_system_make_settings m
CROSS JOIN (SELECT 'system_name' AS k, '{system_name}' AS v
            UNION ALL SELECT 'departments', '{trigger_list}'
            UNION ALL SELECT 'timestamp_local', '{timestamp_local}'
            UNION ALL SELECT 'transcript', '{transcript}'
            UNION ALL SELECT 'audio_url', '{audio_url}') f
WHERE NOT EXISTS (SELECT 1 FROM radio_system_make_payload_fields p WHERE p.make_setting_id = m.make_setting_id);

COMMIT;
