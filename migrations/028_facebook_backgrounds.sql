-- 028_facebook_backgrounds.sql
-- Facebook video posts: file name (under var/facebook_media) of the image or clip shown behind the call audio.
-- Trigger-level backgrounds are kept in that trigger's Facebook settings (alert_trigger_notifiers.config).
BEGIN;

ALTER TABLE radio_system_facebook_settings ADD COLUMN facebook_background TEXT DEFAULT NULL;

COMMIT;
