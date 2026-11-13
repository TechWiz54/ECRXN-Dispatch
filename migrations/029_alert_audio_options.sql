-- Choose per channel whether the call audio goes along as a file, a link (via {audio_url}), or both.
--   Telegram: voice message or a plain text message
--   Make / n8n: also send the audio file (multipart upload) next to the usual fields
--   Email: attach the audio file
ALTER TABLE radio_system_telegram_settings ADD COLUMN telegram_send_audio INTEGER NOT NULL DEFAULT 1;
ALTER TABLE radio_system_make_settings ADD COLUMN make_attach_audio INTEGER NOT NULL DEFAULT 0;
ALTER TABLE radio_system_n8n_settings ADD COLUMN n8n_attach_audio INTEGER NOT NULL DEFAULT 0;
ALTER TABLE radio_system_email_settings ADD COLUMN email_attach_audio INTEGER NOT NULL DEFAULT 0;
