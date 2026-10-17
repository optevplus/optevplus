# Collector

**This code was used to collect a week's worth of data.**

`poll_ev_data.py` is the script that collected OptEV+'s observed readings (issues #7, #8). It
ran unattended on Sushant's laptop and is kept here as the record of how the data was
gathered. It is not part of the `optev` package. The data is loaded into Postgres by
`optev-db load-collected` (spec `specs/002-collectors`).

## What was collected

| | |
|---|---|
| Window | 7 Oct 2026 13:55 to 14 Oct 2026 10:56 SGT |
| Interval | every 5 minutes |
| HDB car park availability | `https://api.data.gov.sg/v1/transport/carpark-availability` (no key): 1,980 polls, about 2,428 lot records each |
| EV charging points | LTA DataMall `EVCBatch`; the download link is followed in the same poll because it expires in minutes: 1,981 polls, 11,698 connectors each, including unavailable ones |
| Failures | one: the first car park poll (7 Oct 13:55, connection error). No gap over 6 minutes |

Every poll is saved raw, with the fetch time (`polled_at`, SGT):

```
collected_data/
  carpark_availability_raw_<date>.jsonl        one line per poll: {"polled_at", "data": <raw response>}
  ev_charging_points_meta_<date>.jsonl         one line per poll: the EVCBatch response with the link
  ev_charging_points_raw_<date>/<polled_at>.dat  the downloaded EV file, decompressed, unmodified
  carpark_availability_<date>.csv, ev_charging_points_<date>.csv   flattened copies
  heartbeat.log                                one line per cycle, plus every error
```

The provider's timestamps are inside the raw payloads: each car park's `update_datetime`, and
`LastUpdatedTime` in the EV file. The EV CSVs were re-flattened afterwards by a separate step;
the loader reads only the raw files.

**The data is not in git** (12 GB). Sushant holds it. It is loaded at 30-minute snapshots: the
poll nearest each :00 and :30 SGT, within 150 s. Every slot in the window has a poll within
101 s.

## Re-running it

```bash
pip install requests
export LTA_ACCOUNT_KEY=<your DataMall key>
python poll_ev_data.py
```

It writes `collected_data/` next to the script and never exits on its own. Run it from a copy
outside the repo so the output is never committed. The only change from the version that ran
is that the LTA key is read from the environment only; it was hard-coded before.
