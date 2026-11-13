-- 025_storage_local_path.sql
-- Optional custom folder for LOCAL storage. NULL/blank = default (static/audio in the install folder).
BEGIN;

ALTER TABLE radio_system_storage_settings ADD COLUMN local_path TEXT;

COMMIT;
