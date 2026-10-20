# analysis

Indicators and demand inference.

**Owner:** P2  ·  **Reads:** `optev/contracts/`

Occupancy is a level; the allocator needs a rate. Utilisation is None where supply_state is NO_SUPPLY or UNOBSERVED — the contract enforces this, do not work around it. Above roughly 0.93 utilisation, report a lower bound rather than a point estimate.

Spec: `specs/011-indicators/` — indicators count in SQL for Postgres and in Python for the sample, through one `_measure`.

Spec: `specs/012-demand/` — demand inverts occupancy per time bin, never over the whole window; `all` is a lower bound only when window utilisation is at or above `RELIABLE_UP_TO`.

Spec: `specs/014-patterns/` — k-means on min-max normalised 48-bin profiles; labels come from cluster centroids by rule, never from site kind.
