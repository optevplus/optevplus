-- 003 · Manifest for the collected week, SYSTEM_DESIGN.md §3.2 and §4.1.
-- One row per feed per 30-minute slot loaded into car_park_reading or connector_reading.
-- A slot with no row was never loaded; a slot already here is skipped, so loading is re-runnable.

CREATE TABLE IF NOT EXISTS stg_collect_slot (
    feed            text NOT NULL CHECK (feed IN ('car_park', 'ev')),
    slot_ts         timestamptz NOT NULL,
    polled_ts       timestamptz NOT NULL,  -- the poll chosen for the slot = collected_ts
    offset_s        integer NOT NULL CHECK (offset_s >= 0),
    rows_written    integer NOT NULL CHECK (rows_written >= 0),
    rows_skipped    integer NOT NULL CHECK (rows_skipped >= 0),
    PRIMARY KEY (feed, slot_ts)
);
