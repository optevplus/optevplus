# 001 · Neon Postgres with PostGIS

**Owner:** Sushant  ·  **Status:** approved 14 Oct 2026  ·  **Branch:** `sushant/2-neon-postgis` · Issue #2

## Design section
This is setup for the database every stage writes to; there is no §4 module of its own.

> §2.2 · Database | PostgreSQL + PostGIS on **Neon** | **Source of truth** for every number and record

> §3.2 · Migrations `001_init.sql` and `002_pipeline.sql` create every table below. Apply with
> `uv run optev-db migrate`. Ingest-internal staging tables are allowed if prefixed `stg_`.

> §2.3.6 · **Every stage is re-runnable.** Writes are upserts keyed on the table's primary key;
> running a stage twice gives the same tables.

> §7 · SQL through psycopg with parameters, never string formatting; logging with `logging`,
> `print` only in CLIs; secrets only from the environment.

Issue #2: Neon project in the Singapore region, **direct** (not pooled) connection string,
`CREATE EXTENSION postgis` and `SELECT postgis_version()`, string in repo secrets and local
`.env`. **Done when `optev-db migrate` runs clean from a fresh checkout.**

## Problem
There is no shared database yet, so no collector, stage or app can write or read real data.
The migrations and `optev-db migrate` exist but have never run against a live server, and the
CLI reads only `os.environ`, so a fresh checkout with a filled-in `.env` currently prints
"DATABASE_URL is not set".

## Contracts touched
None. `contracts/` is not read or changed. Tables come from the existing migrations; no new
table, column or migration.

## Approach
1. **Provision (manual, me).** Neon project `optev`, region AWS Singapore (`ap-southeast-1`).
   Copy the direct connection string (host without `-pooler`), with `sslmode=require`. In the
   SQL editor: `CREATE EXTENSION postgis; SELECT postgis_version();` and record the version
   in the checkpoint.
2. **Secrets (manual, me).** `DATABASE_URL` in local `SystemCode/.env` (gitignored) and as a
   GitHub Actions repository secret, ready for `collect.yml` (#7, #8).
3. **Code, `optev/ingest/cli.py` only.** Call `dotenv.load_dotenv()` (python-dotenv is already
   a dependency) before reading `DATABASE_URL`, so the issue's `.env` workflow works. Nothing
   else in the CLI changes: it already applies migrations in order in one transaction and
   prints the PostGIS version.
4. **`.env.example`.** Reword the `DATABASE_URL` comment to say "direct connection string, not
   the pooled one; Singapore region", so the next person does not pick the pooler.
5. **Tests, `tests/test_cli.py`.**
   - `main()` with no or wrong argument returns 2 (no DB needed).
   - `migrate()` with `DATABASE_URL` unset returns 1 (no DB needed; monkeypatch env and
     `load_dotenv`).
   - Integration, skipped unless `DATABASE_URL` is set: `migrate()` returns 0 **twice in a
     row** (re-runnable, §2.3.6), every §3.2 table exists in `information_schema.tables`, and
     `postgis_version()` returns a value.

## Verification
From a fresh clone, with only `SystemCode/.env` copied in:

```
uv sync --extra dev
uv run optev-db migrate      # applied 001_init.sql / applied 002_pipeline.sql / postgis 3.x ...
uv run optev-db migrate      # same output again, no error
uv run ruff check . && uv run mypy optev && uv run pytest
```
CI (no secret) runs the two unit tests and skips the integration test; locally all three run.

## Loading the prototype week: separate issue, not this one
Recommend a new issue (or a sub-task of #7 / #8), not #2, because:
- #2 is setup; its done-condition is a clean migrate. Mixing in a data load means the PR can
  pass review only once the data question is settled too.
- The load must apply exactly the §4.1 collect rules (status `"0"/"1"/""` mapping, `lot_type =
  "C"`, HDB feed for HDB car parks and LTA only for URA/mall, both timestamps). Those rules
  will live in `collect.py` (#7, #8); the backfill should reuse them, not be a second parser.
- The design defines no backfill function, so it needs a short §4.1 PR first.
- The prototype polled every **5 min**; the design snapshot is `SNAPSHOT_MINUTES` = 30 and
  coverage (#12) measures completeness against that schedule. Thin to 30 min or keep all is a
  team decision.
- It came from a laptop, which §2.2 says the collector must never depend on; the rows need a
  way to be told apart (or excluded) later.
- It must come from the raw JSON, not the flattened CSVs, if `provider_ts` is not in the CSVs.

## Decisions (14 Oct 2026, Sushant)
1. **Storage.** One EVCBatch poll = 11,595 rows. Estimate below; team to decide plan tier.
2. **No `DATABASE_URL` in `ci.yml`.** A manual run from a fresh clone is the proof.
3. **No pooled-string guard.** Not in the design; the `.env.example` wording is enough.
4. **Branch renamed** to `sushant/2-neon-postgis`.
5. **Prototype week** goes to a separate issue; Sushant raises it with the team.

### Storage runway on the Free plan (1 GB per project since Neon's 2 Oct 2026 changelog)
Estimated from the 001 layout (heap + PK + `(connector_id, collected_ts)` lookup index), not measured:
`connector_reading` ~150–190 B/row x 11,595 x 48 snapshots = **~85–105 MB/day**;
`car_park_reading` ~2,400 car parks (guess) x 48 = **~15 MB/day**. Total **~100–120 MB/day**,
so 1 GB lasts **~8–9 days** after static data, i.e. full around 23–24 Oct if collection
starts 15 Oct: short of 25 Oct, with no room left for analysis tables. Replace the estimate
with `pg_total_relation_size` after the first day of collection.

## Checkpoint · 14 Oct 2026
**Works.** `.env` has a direct (no `-pooler`), `ap-southeast-1` URL with `sslmode=require`.
`cli.migrate()` loads `SystemCode/.env` (never overriding a set variable) and reads migrations as
UTF-8. `.env.example` says direct, Singapore. `tests/test_cli.py`: usage error, missing URL, URL
from `.env` (psycopg.connect stubbed, no network) pass; the live test skips unless DATABASE_URL
is in the real environment (`uv run --env-file .env pytest`), so plain pytest never migrates
the shared DB. ruff and mypy pass.
**Blocked.** From this laptop, TCP to the Neon host on 5432 times out while 443 connects in
0.2 s, so `optev-db migrate` hangs. Not yet known whether the network or the tool sandbox blocks it.
**Not done.** Migrate twice against Neon; PostGIS version; repo secret `DATABASE_URL`.
**Decided.** Live DB test is opt-in by environment, not `.env` (same risk flagged on PR #47).
**Next.** Run `Test-NetConnection` on 5432 from a normal terminal; if blocked, use another
network (e.g. phone hotspot), then migrate twice and run the live test.

## Checkpoint · 15 Oct 2026
**Done.** Sushant ran `uv run optev-db migrate` twice against Neon (Singapore, direct
connection): both clean, PostGIS reported. `uv run --env-file .env pytest tests/test_cli.py`:
4 passed, including the live test (migrate twice, every migration table present, PostGIS).
Rebased onto main after #49; ruff, mypy, pytest pass (26 passed, live test skipped without env).
The 14 Oct timeout on port 5432 did not recur; no code change was needed for it.
**Left.** Sushant adds `DATABASE_URL` as a GitHub Actions repository secret (needed by #7, #8).
Team decides Neon plan tier before collection fills 1 GB (~8–9 days, estimate above).
