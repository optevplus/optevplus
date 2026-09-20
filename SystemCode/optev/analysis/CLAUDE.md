# analysis

Indicators and demand inference.

**Owner:** P2  ·  **Reads:** `optev/contracts/`

Occupancy is a level; the allocator needs a rate. Utilisation is None where supply_state is NO_SUPPLY or UNOBSERVED — the contract enforces this, do not work around it. Above roughly 0.93 utilisation, report a lower bound rather than a point estimate.
