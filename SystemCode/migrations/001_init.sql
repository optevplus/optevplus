-- 001 · PostGIS and the three data layers.
-- Observed, simulated and planned never share a table. Merging them is the one
-- mistake that corrupts measurement silently.

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS planning_area (
    code        text PRIMARY KEY,
    name        text NOT NULL,
    region      text,
    geom        geometry(MultiPolygon, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS planning_area_geom_idx ON planning_area USING GIST (geom);

CREATE TABLE IF NOT EXISTS car_park (
    car_park_id     text PRIMARY KEY,
    name            text NOT NULL,
    total_lots      integer CHECK (total_lots >= 0),
    car_park_type   text,
    has_live_feed   boolean NOT NULL DEFAULT false,
    planning_area   text REFERENCES planning_area(code),
    geom            geometry(Point, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS car_park_geom_idx ON car_park USING GIST (geom);

CREATE TABLE IF NOT EXISTS station (
    station_id      text PRIMARY KEY,
    operator        text,
    address         text,
    provenance      text NOT NULL DEFAULT 'observed',
    planning_area   text REFERENCES planning_area(code),
    geom            geometry(Point, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS station_geom_idx ON station USING GIST (geom);

CREATE TABLE IF NOT EXISTS connector (
    connector_id    text PRIMARY KEY,
    station_id      text NOT NULL REFERENCES station(station_id),
    plug_type       text,
    power_kw        numeric CHECK (power_kw > 0),
    -- false until seen AVAILABLE or OCCUPIED; until then it may be planned or removed
    ever_active     boolean NOT NULL DEFAULT false
);

-- Readings keep both timestamps. Staleness cannot be reconstructed later.
CREATE TABLE IF NOT EXISTS car_park_reading (
    id              bigserial PRIMARY KEY,
    car_park_id     text NOT NULL,
    lots_available  integer NOT NULL CHECK (lots_available >= 0),
    total_lots      integer CHECK (total_lots >= 0),
    lot_type        text NOT NULL DEFAULT 'C',
    provider_ts     timestamptz,
    collected_ts    timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS car_park_reading_lookup ON car_park_reading (car_park_id, collected_ts);

CREATE TABLE IF NOT EXISTS connector_reading (
    id              bigserial PRIMARY KEY,
    connector_id    text NOT NULL,
    status          text NOT NULL,
    provider_ts     timestamptz,
    collected_ts    timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS connector_reading_lookup ON connector_reading (connector_id, collected_ts);

-- Planner selections. Separate from station/connector so observed stock is untouched
-- and a selection stays reversible.
CREATE TABLE IF NOT EXISTS planned_capacity (
    id              bigserial PRIMARY KEY,
    scenario_id     text NOT NULL,
    site_id         text NOT NULL,
    connectors      integer NOT NULL CHECK (connectors >= 1),
    selected_by     text,
    selected_at     timestamptz NOT NULL DEFAULT now()
);
