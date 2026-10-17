-- 003 · Ingest staging, allowed by SYSTEM_DESIGN.md §3.2 when prefixed stg_.
-- Amenities have no table of their own before conform: an amenity becomes a candidate site
-- only when no car park is within AMENITY_LINK_M. load_static writes here; conform reads.

CREATE TABLE IF NOT EXISTS stg_amenity (
    amenity_id  text PRIMARY KEY,   -- §3.3: hawker:<id>, cc:<id>, petrol:<id>
    kind        text NOT NULL CHECK (kind IN ('hawker_centre', 'community_facility',
                    'petrol_station')),
    total_lots  integer CHECK (total_lots >= 0),
    geom        geometry(Point, 4326) NOT NULL
);
