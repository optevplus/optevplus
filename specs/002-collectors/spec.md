# 002 · Collected week: load HDB car park and EV charging readings

**Owner:** Sushant  ·  **Status:** approved 15 Oct 2026; built and loaded  ·  **Branch:** `sushant/7-collectors` · Issues #7, #8

## Design section

> §4.1 · **Modules and interface**
> ```python
> # optev/ingest/collect.py   (run by .github/workflows/collect.yml every 30 minutes)
> def collect_ev(now: datetime) -> int            # rows written to connector_reading
> def collect_car_parks(now: datetime) -> int     # rows written to car_park_reading
> ```

> §4.1 · **Method 1. Collect.** EV status mapping: `"0"` → occupied, `"1"` → available, `""` →
> unavailable. Store both `provider_ts` and `collected_ts`. Car parks: keep `lot_type = "C"`.
> Use the HDB data.gov.sg feed for HDB car parks and LTA's feed for URA and mall car parks only,
> so no car park is counted twice. [...] One bad record is logged and skipped; it never fails
> the run.

> §2.2 · Collector | **GitHub Actions** cron, every 30 min | Writes readings to Postgres. Never
> depends on a laptop

> §3.2 · `car_park_reading`, `connector_reading` · written by ingest collectors · read by
> analysis. Ingest-internal staging tables are allowed if prefixed `stg_`.
> §3.3 · HDB car park site `hdb:<car_park_no>` · Connector: LTA `evCpId`.
> §3.5 · `SNAPSHOT_MINUTES` (30).
> §7 · SQL through psycopg with parameters; `logging`, `print` only in CLIs; secrets only from
> the environment. Never commit data.

**This spec departs from §2.2 and §4.1** (see Design change below). The team decision is that
the week collected on my laptop, 7–14 Oct 2026, is the observed dataset for the project. There
is no live collector and no `collect.yml`.

## Problem

`connector_reading` and `car_park_reading` are empty, so stage 2 has nothing real to measure.
The data exists: `poll_ev_data.py` polled data.gov.sg car park availability and LTA `EVCBatch`
every 5 minutes from 7 Oct 13:55 to 14 Oct 10:56 SGT, saving every raw response (12 GB). There
were 1,981 EV polls and 1,980 car park polls, no gaps over 6 minutes, and one failed poll. None
of it is in Postgres, and the format is the script's own files rather than the design's tables.

## Contracts touched

Reads only: `CarParkReading`, `ConnectorReading`, `ConnectorStatus`. Every record is built as a
contract model before insert, so validation is the "bad record" check. No contract changes.

## Design change (PR to `SYSTEM_DESIGN.md`, needs Ghanashyam's approval before code)

- §2.2 Collector row: "One week of 5-minute polls, 7–14 Oct 2026, collected by
  `poll_ev_data.py` and loaded once at 30-minute snapshots. No scheduled collector."
- §4.1 interface: replace `collect_ev` / `collect_car_parks` with
  ```python
  # optev/ingest/collect.py
  def load_collected(root: Path, day: date | None = None) -> dict[str, int]
  ```
- §4.1 Method 1 keeps the status mapping, `lot_type = "C"`, both timestamps and
  skip-bad-records, and adds: "Keep the poll nearest each :00 and :30 SGT slot, within 150 s.
  A slot with no poll is recorded as missing, never filled."
- §6 stage 1 completeness is measured against the 330 slots of the collected week.
- `.github/workflows/collect.yml` is dropped from the design.

## Approach

**The input.** `root` is the `collected_data` folder: `carpark_availability_raw_<date>.jsonl`
(one line per poll: `polled_at` + the raw response) and
`ev_charging_points_raw_<date>/<polled_at>.dat` (one decompressed `EVCBatch` file per poll).
Only the raw files are read; the script's CSVs are ignored because the car park CSV has the
wrong provider timestamp. The folder stays on my machine and is never committed.

**`optev/ingest/collect.py`** (under ~300 lines):

1. `_slots(polls)`: for each :00 and :30 SGT slot in the window, pick the poll nearest to it
   within 150 s. Checked on the real data: all 330 EV and 329 car park slots match, worst
   offset 101 s.
2. `_parse_car_parks(payload, collected_ts)`: for each car park, keep `lot_type == "C"` and
   build `CarParkReading(car_park_id="hdb:<carpark_number>", ..., provider_ts=<that car park's
   own update_datetime as SGT>, collected_ts=<polled_at as SGT>)`.
3. `_parse_ev(payload, collected_ts)`: walk `evLocationsData → chargingPoints → plugTypes →
   evIds`. For each `evCpId`: `ConnectorReading(status=<§4.1 mapping>, provider_ts=
   LastUpdatedTime)`. Unknown status: logged and skipped. Unavailable connectors are kept.
4. `_copy(cur, rows)`: `COPY ... FROM STDIN` with `write_row` (values through psycopg, never
   string formatting); `_write_slot` checks the manifest, copies, and adds the manifest row.
5. `load_collected(root, day)`: slots → parse → copy, and returns
   `{"car_park_reading": n, "connector_reading": m}`. Each slot is written in one transaction
   with its `stg_collect_slot` row, and a slot already there is skipped, so a re-run writes
   nothing; the tables have `bigserial` keys, so §2.3.6's upsert cannot dedupe them. `day`
   loads only that SGT day's slots, for loading one day first.
6. CLI: `optev-db load-collected <path> [--day YYYY-MM-DD]` in `ingest/cli.py`, next to `migrate`.

`station` and `connector` rows and `ever_active` stay with `conform()` (#9), which reads these
tables.

**Manifest (issue #7).** I propose one ingest-internal table `stg_collect_slot (feed, slot_ts,
polled_ts, offset_s, rows_written, rows_skipped)` in `003_collect.sql`, one row per feed per
slot, so a gap shows as a missing slot. It is allowed by §3.2's `stg_` rule. Q3 covers dropping
it.

**The collector script.** Kept in the repo as the record of how the data was gathered, outside
the package (README section 7, `Miscellaneous/`), so it needs no tests and is not linted:

- `Miscellaneous/collector/poll_ev_data.py`: the script exactly as it ran, except that the LTA
  key is read from the environment only (the hard-coded fallback is removed). The key it
  carried should be rotated on DataMall.
- `Miscellaneous/collector/README.md`, opening with: **"This code was used to collect a week's
  worth of data."** Then: the window (7 Oct 2026 13:55 to 14 Oct 2026 10:56 SGT), the two
  endpoints, the 5-minute interval, poll counts (1,981 EV, 1,980 car park, one failed poll,
  no gap over 6 minutes), the output layout, that the data itself is not in git (12 GB, kept by
  Sushant) and is loaded with `optev-db load-collected` at 30-minute snapshots, and how to
  re-run it (`LTA_ACCOUNT_KEY` in the environment, `pip install requests`). It also says the
  EV CSVs were re-flattened afterwards by a separate step; during the run the script saved the
  raw `.dat` files, which is all the loader reads. (Confirmed by Sushant, 15 Oct 2026: the
  Desktop `poll_ev_data.py` is the version that ran.)
- `SystemCode/optev/ingest/CLAUDE.md` and the `collect.py` docstring point to that README.

**Tests, `tests/test_collect.py`** (hand-written mini payloads in the real shapes, `SYN-` ids;
no real data in git):
- `_slots`: nearest poll picked; a slot with no poll inside 150 s is reported missing.
- `_parse_car_parks`: `hdb:` ids, only `C`, per-car-park `provider_ts`, bad record skipped with
  a warning (caplog), never raises.
- `_parse_ev`: `"0"/"1"/""` mapping, unavailable kept, unknown status skipped.
- `load_collected` on a tiny temp folder built in the test (no DB: `_insert` patched).
- Integration, skipped unless `DATABASE_URL` is set: `optev.sample` readings round-trip
  through `_insert`; a second `load_collected` on the same folder writes 0.

## Verification

```
uv run ruff check . && uv run mypy optev && uv run pytest
uv run optev-db migrate
uv run optev-db load-collected "C:/Users/Sushant/Desktop/collected_data" --day 2026-10-08
uv run optev-db load-collected "C:/Users/Sushant/Desktop/collected_data"   # the rest
# per day: car_park_reading +96,336 · connector_reading +556,395 (8 Oct, 48 slots each)
```
Check: `SELECT feed, count(*) FROM stg_collect_slot GROUP BY feed` returns 330 for each feed.

## Open questions

Approved as proposed by Sushant, 15 Oct 2026. Where the spec made a proposal, it stands:

1. **Neon storage.** *Decided:* free plan, 1 GiB per branch; the week took 690 MB in total.
2. **Design PR.** *Decided:* agreed by Ghanashyam; `SYSTEM_DESIGN.md` 1.3 is in this branch.
3. **Manifest.** *Decided:* `stg_collect_slot` in `003_collect.sql`, as proposed.
4. **URA and mall car parks** were not collected. *Decided:* HDB only for the study; to be
   stated in the design PR.
5. **One branch, two issues.** *Decided:* #7 and #8 together on `sushant/7-collectors`.
6. **Issue text.** *Decided:* update #7 and #8 to say the data is a one-off week, once the
   design PR is agreed.

## Checkpoint · 15 Oct 2026

- **Works:** spec approved. `Miscellaneous/collector/poll_ev_data.py` is in the repo, identical to
  the script that ran except that the LTA key is read from the environment only. Its `README.md`
  states "This code was used to collect a week's worth of data." with the window, endpoints,
  poll counts and file layout. `.gitignore` now ignores `collected_data/`.
- **Not started:** `optev/ingest/collect.py`, `003_collect.sql`, `load-collected` CLI, tests,
  and the `ingest/CLAUDE.md` pointer. They wait for the design PR (Q2) and the Neon plan (Q1).
- **Checked on the real data:** every 30-minute slot has a poll within 101 s (330 EV, 329 car
  park).
- **To do outside code:** rotate the LTA DataMall key that was hard-coded in the laptop copy.
- **Next:** once Ghanashyam agrees the design change, write `collect.py` with tests first, then
  load into Neon.

## Checkpoint · 15 Oct 2026 (loaded)

- **Works:** `SYSTEM_DESIGN.md` 1.3 carries the agreed change. `003_collect.sql`, `collect.py`
  and `optev-db load-collected <path> [--day]` are built; ruff, mypy and pytest pass (40 tests,
  the live ones included, rolled back).
- **Loaded into Neon:** 330 slots per feed, 7 Oct 14:00 to 14 Oct 10:30 SGT, max offset 101 s,
  0 records skipped, 0 duplicate (connector, time) pairs. `connector_reading` 3,832,874 rows
  (577 MB); `car_park_reading` 662,310 rows (96 MB). Database 690 MB of the 1 GiB limit.
  Median EV staleness (`collected_ts − provider_ts`) 76 s.
- **Re-runnable:** loading 8 Oct again wrote 0 rows.
- **Decisions:** branch rebased onto `sushant/2-neon-postgis` (PR #51) because both change
  `cli.py`; this PR merges after #51. COPY instead of `executemany` for speed.
- **Next:** push and open the PR; update issues #7 and #8 wording; rotate the LTA key; #9
  `conform()` can now build `station`, `connector` and `ever_active` from these tables.
