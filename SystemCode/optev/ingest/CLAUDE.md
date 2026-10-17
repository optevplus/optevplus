# ingest

Collectors, conforming, spatial joins, coverage reporting.

**Owner:** P1  ·  **Reads:** `optev/contracts/`

Store raw payloads unmodified and both timestamps — provider and collected. Staleness cannot be reconstructed later. Log every connector status including unavailable ones; the planned/removed filter needs the full series. Never overwrite: append only.

Readings come from the week collected 7–14 Oct 2026, loaded by `collect.load_collected`; how it was gathered is in `Miscellaneous/collector/README.md`.
