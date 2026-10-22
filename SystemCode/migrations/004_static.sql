-- 004 · Staging tables for the static loads, SYSTEM_DESIGN.md §3.2 and §4.1 (spec 004).
-- Written by ingest load_static, read by conform. Upserted on their primary keys, so a
-- re-run changes nothing.

-- One row per amenity that could become a candidate site (§3.3 ids). conform links it to a
-- car park within AMENITY_LINK_M or makes it a standalone site.
CREATE TABLE IF NOT EXISTS stg_amenity (
    amenity_id  text PRIMARY KEY,           -- 'hawker:<OBJECTID>' | 'cc:<OBJECTID>'
    kind        text NOT NULL CHECK (kind IN ('hawker_centre', 'community_facility',
                    'petrol_station')),     -- SiteKind values
    name        text NOT NULL,
    address     text,
    status      text,                       -- hawker STATUS, cc DESCRIPTION, as published
    geom        geometry(Point, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS stg_amenity_geom_idx ON stg_amenity USING GIST (geom);

-- MP2025 land-use plots: only what point-in-polygon needs, geometry simplified on load.
CREATE TABLE IF NOT EXISTS stg_land_use (
    land_use_id text PRIMARY KEY,           -- source OBJECTID
    lu_desc     text NOT NULL,              -- e.g. RESIDENTIAL, COMMERCIAL
    geom        geometry(MultiPolygon, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS stg_land_use_geom_idx ON stg_land_use USING GIST (geom);

-- Residents per planning area (Census 2020, the "<Area> - Total" rows).
CREATE TABLE IF NOT EXISTS stg_residents (
    planning_area text PRIMARY KEY REFERENCES planning_area(code),
    residents     integer NOT NULL CHECK (residents >= 0),     -- Total
    residents_hdb integer CHECK (residents_hdb >= 0),          -- HDBDwellings_Total
    source_year   integer NOT NULL
);
