-- 002 · Tables for stages 1-4, as named in SYSTEM_DESIGN.md §3.2.
-- Each mirrors a contract in optev/contracts/. Simulated rows never enter observed tables:
-- projections live in scenario_demand, planner picks in planned_capacity (001).
-- Baseline (non-scenario) decisions use scenario_id 'observed'.

-- Stage 1 · candidate sites and their context ------------------------------------------
CREATE TABLE IF NOT EXISTS candidate_site (
    site_id             text PRIMARY KEY,
    kind                text NOT NULL CHECK (kind IN ('hdb_car_park', 'public_car_park',
                            'petrol_station', 'hawker_centre', 'community_facility',
                            'existing_station')),
    planning_area       text REFERENCES planning_area(code),
    car_park_id         text REFERENCES car_park(car_park_id),
    total_lots          integer CHECK (total_lots >= 0),
    -- invariant 3: only connectors seen available or occupied
    existing_connectors integer NOT NULL DEFAULT 0 CHECK (existing_connectors >= 0),
    provenance          text NOT NULL DEFAULT 'observed',
    geom                geometry(Point, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS candidate_site_geom_idx ON candidate_site USING GIST (geom);

-- Spatial association, not proof of ownership. One row per station-site pair.
CREATE TABLE IF NOT EXISTS station_site (
    station_id   text NOT NULL REFERENCES station(station_id),
    site_id      text NOT NULL REFERENCES candidate_site(site_id),
    distance_m   double precision NOT NULL CHECK (distance_m >= 0),
    threshold_m  integer NOT NULL CHECK (threshold_m IN (50, 100, 200)),
    PRIMARY KEY (station_id, site_id)
);

CREATE TABLE IF NOT EXISTS site_context (
    site_id           text PRIMARY KEY REFERENCES candidate_site(site_id),
    land_use          text,
    residents_in_area integer CHECK (residents_in_area >= 0),
    amenities_nearby  integer NOT NULL DEFAULT 0 CHECK (amenities_nearby >= 0),
    nearest_point_m   double precision CHECK (nearest_point_m >= 0)
);

CREATE TABLE IF NOT EXISTS coverage_report (
    run_at  timestamptz NOT NULL DEFAULT now(),
    metric  text NOT NULL,
    value   double precision NOT NULL,
    detail  text,
    PRIMARY KEY (run_at, metric)
);

-- Stage 2 · indicators, demand, patterns ----------------------------------------------
CREATE TABLE IF NOT EXISTS site_indicators (
    site_id              text NOT NULL REFERENCES candidate_site(site_id),
    window_start         timestamptz NOT NULL,
    window_end           timestamptz NOT NULL,
    supply_state         text NOT NULL CHECK (supply_state IN ('no_supply', 'supply_idle',
                             'supply_active', 'unobserved')),
    active_connectors    integer NOT NULL DEFAULT 0 CHECK (active_connectors >= 0),
    utilisation          double precision CHECK (utilisation BETWEEN 0 AND 1),
    saturated_fraction   double precision CHECK (saturated_fraction BETWEEN 0 AND 1),
    dwell_opportunity    double precision CHECK (dwell_opportunity >= 0),
    observation_coverage double precision NOT NULL CHECK (observation_coverage BETWEEN 0 AND 1),
    PRIMARY KEY (site_id, window_start, window_end),
    -- invariant 2: no supply means utilisation is undefined, never 0
    CHECK (supply_state NOT IN ('no_supply', 'unobserved') OR utilisation IS NULL)
);

CREATE TABLE IF NOT EXISTS demand_estimate (
    site_id           text NOT NULL REFERENCES candidate_site(site_id),
    time_bin          text NOT NULL CHECK (time_bin ~ '^(all|wd-[0-2][0-9]|we-[0-2][0-9])$'),
    arrivals_per_hour double precision NOT NULL CHECK (arrivals_per_hour >= 0),
    kind              text NOT NULL CHECK (kind IN ('point', 'lower_bound')),
    method            text NOT NULL CHECK (method IN ('queueing', 'regression')),
    note              text,
    PRIMARY KEY (site_id, time_bin)
);

CREATE TABLE IF NOT EXISTS site_pattern (
    site_id  text PRIMARY KEY REFERENCES candidate_site(site_id),
    cluster  integer NOT NULL CHECK (cluster >= 0),
    label    text
);

-- Stage 3 · scenarios (simulated layer) -----------------------------------------------
CREATE TABLE IF NOT EXISTS scenario (
    scenario_id       text PRIMARY KEY,
    seed              integer NOT NULL DEFAULT 0,
    growth_multiplier double precision NOT NULL CHECK (growth_multiplier > 0),
    horizon_months    integer NOT NULL CHECK (horizon_months >= 1),
    baseline_window   text,
    provenance        text NOT NULL DEFAULT 'simulated' CHECK (provenance = 'simulated')
);

CREATE TABLE IF NOT EXISTS scenario_demand (
    scenario_id       text NOT NULL REFERENCES scenario(scenario_id),
    site_id           text NOT NULL REFERENCES candidate_site(site_id),
    time_bin          text NOT NULL CHECK (time_bin ~ '^(all|wd-[0-2][0-9]|we-[0-2][0-9])$'),
    arrivals_per_hour double precision NOT NULL CHECK (arrivals_per_hour >= 0),
    kind              text NOT NULL CHECK (kind IN ('point', 'lower_bound')),
    PRIMARY KEY (scenario_id, site_id, time_bin)
);

-- Stage 4 · rules, decisions, allocation ----------------------------------------------
CREATE TABLE IF NOT EXISTS rule (
    rule_id              text PRIMARY KEY,
    condition            text NOT NULL,
    source               text NOT NULL CHECK (source IN ('gov_dataset', 'gov_policy',
                             'math_constraint', 'project_assumption')),
    source_ref           text,
    required_facts       text[] NOT NULL DEFAULT '{}',
    explanation_template text NOT NULL,
    on_fail              text NOT NULL CHECK (on_fail IN ('reject', 'conditional'))
);

CREATE TABLE IF NOT EXISTS decision (
    site_id     text NOT NULL REFERENCES candidate_site(site_id),
    scenario_id text NOT NULL DEFAULT 'observed',
    outcome     text NOT NULL CHECK (outcome IN ('accept', 'reject', 'defer', 'conditional')),
    decided_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (site_id, scenario_id)
);

-- One row per rule evaluated, never only the first. passed NULL = unevaluated.
CREATE TABLE IF NOT EXISTS rule_result (
    site_id     text NOT NULL,
    scenario_id text NOT NULL DEFAULT 'observed',
    rule_id     text NOT NULL REFERENCES rule(rule_id),
    passed      boolean,
    detail      text,
    PRIMARY KEY (site_id, scenario_id, rule_id),
    FOREIGN KEY (site_id, scenario_id) REFERENCES decision(site_id, scenario_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS allocation (
    allocation_id        text PRIMARY KEY,
    scenario_id          text NOT NULL,
    budget               double precision NOT NULL CHECK (budget >= 0),
    requested_connectors integer CHECK (requested_connectors >= 0),
    checked              boolean NOT NULL DEFAULT false,
    violations           text[] NOT NULL DEFAULT '{}',
    created_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS allocation_item (
    allocation_id   text NOT NULL REFERENCES allocation(allocation_id) ON DELETE CASCADE,
    site_id         text NOT NULL REFERENCES candidate_site(site_id),
    connectors      integer NOT NULL CHECK (connectors >= 1),
    cost            double precision NOT NULL CHECK (cost >= 0),
    marginal_relief double precision,
    PRIMARY KEY (allocation_id, site_id)
);

CREATE TABLE IF NOT EXISTS infeasibility (
    report_id            text PRIMARY KEY,
    scenario_id          text NOT NULL,
    requested_connectors integer NOT NULL CHECK (requested_connectors >= 0),
    max_feasible         integer NOT NULL CHECK (max_feasible >= 0),
    binding_constraints  text[] NOT NULL DEFAULT '{}',
    affected_areas       text[] NOT NULL DEFAULT '{}'
);
