"""
1-week real-time data collector: HDB Carpark Availability (data.gov.sg)
+ LTA DataMall EV Charging Points.

Design choices, on purpose:
- Every poll saves the FULL raw JSON response to a dated .jsonl file, in
  addition to a best-effort flattened CSV. If a field name in the live API
  turns out slightly different from what's assumed below, you still keep
  every byte of real data and can re-parse it afterwards - nothing is lost.
- The script never exits on its own. Any error (network blip, API hiccup,
  wifi drop) is caught, logged, and it just waits and tries again on the
  next cycle. It is meant to run untouched for 7 days.
- A heartbeat line is written every cycle so you can glance at one file
  each evening and see it is still alive, instead of finding out on day 7.

Before running:
  pip install requests
  Set the LTA_ACCOUNT_KEY environment variable to your DataMall key.
"""

import os
import io
import csv
import gzip
import json
import time
import traceback
from datetime import datetime, timezone, timedelta

import requests

# ---------------------------------------------------------------- CONFIG ---

LTA_ACCOUNT_KEY = os.environ["LTA_ACCOUNT_KEY"]  # never hard-code the key

POLL_INTERVAL_SECONDS = 5 * 60          # 5 minutes - adjust after checking the
                                         # LTA DataMall guide's stated refresh rate
CARPARK_URL = "https://api.data.gov.sg/v1/transport/carpark-availability"

# "EVChargingPoints" (singular, per-postal-code lookup) is NOT what we want -
# it needs a specific postal code and isn't an island-wide dump. The dataset
# that returns every charger in Singapore in one go is the BATCH variant,
# whose actual DataMall code is EVCBatch. It doesn't return records directly:
# it returns a short-lived (~15 min) download link to a data file, which we
# then fetch separately.
EV_CHARGING_URL = "https://datamall2.mytransport.sg/ltaodataservice/EVCBatch"

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "collected_data")
os.makedirs(OUT_DIR, exist_ok=True)

SGT = timezone(timedelta(hours=8))


def now_sgt_str():
    return datetime.now(SGT).strftime("%Y-%m-%dT%H:%M:%S")


def today_str():
    return datetime.now(SGT).strftime("%Y-%m-%d")


def append_jsonl(filename_prefix, payload):
    path = os.path.join(OUT_DIR, f"{filename_prefix}_{today_str()}.jsonl")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def append_csv_rows(filename_prefix, fieldnames, rows):
    if not rows:
        return
    path = os.path.join(OUT_DIR, f"{filename_prefix}_{today_str()}.csv")
    write_header = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)


def log_heartbeat(message):
    path = os.path.join(OUT_DIR, "heartbeat.log")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{now_sgt_str()}  {message}\n")


# ------------------------------------------------------------- POLL CALLS ---

def poll_carpark_availability(polled_at):
    resp = requests.get(CARPARK_URL, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    append_jsonl("carpark_availability_raw", {"polled_at": polled_at, "data": data})

    rows = []
    try:
        for item in data.get("items", []):
            update_dt = item.get("timestamp")
            for cp in item.get("carpark_data", []):
                carpark_number = cp.get("carpark_number")
                for info in cp.get("carpark_info", []):
                    rows.append({
                        "polled_at": polled_at,
                        "carpark_number": carpark_number,
                        "lot_type": info.get("lot_type"),
                        "total_lots": info.get("total_lots"),
                        "lots_available": info.get("lots_available"),
                        "update_datetime": update_dt,
                    })
    except Exception:
        log_heartbeat(f"WARN carpark_availability flatten failed (raw JSON still saved): {traceback.format_exc().splitlines()[-1]}")

    append_csv_rows(
        "carpark_availability",
        ["polled_at", "carpark_number", "lot_type", "total_lots", "lots_available", "update_datetime"],
        rows,
    )
    return len(rows)


def poll_ev_charging_points(polled_at):
    headers = {"AccountKey": LTA_ACCOUNT_KEY, "accept": "application/json"}

    # Step 1: ask DataMall for the batch dataset - this returns metadata
    # containing a temporary download Link, not the actual records.
    resp = requests.get(EV_CHARGING_URL, headers=headers, timeout=30)
    resp.raise_for_status()
    meta = resp.json()
    append_jsonl("ev_charging_points_meta", {"polled_at": polled_at, "data": meta})

    values = meta.get("value", [])
    if not values or "Link" not in values[0]:
        log_heartbeat(f"WARN ev_charging_points: no download Link in response - {meta}")
        return 0
    link = values[0]["Link"]

    # Step 2: follow the link immediately (it expires in ~15 minutes) and
    # download the actual data file.
    file_resp = requests.get(link, timeout=60)
    file_resp.raise_for_status()
    raw_bytes = file_resp.content

    # The file is usually gzip-compressed; fall back to raw bytes if not.
    try:
        content = gzip.decompress(raw_bytes)
    except OSError:
        content = raw_bytes

    # Always keep the decompressed raw file too, exactly as downloaded -
    # a safety net in case the parsing below doesn't match its real shape.
    safe_ts = polled_at.replace(":", "-")
    raw_dir = os.path.join(OUT_DIR, f"ev_charging_points_raw_{today_str()}")
    os.makedirs(raw_dir, exist_ok=True)
    with open(os.path.join(raw_dir, f"{safe_ts}.dat"), "wb") as f:
        f.write(content)

    text = content.decode("utf-8", errors="replace")
    stripped = text.strip()

    rows = []
    try:
        if stripped.startswith("{") or stripped.startswith("["):
            parsed = json.loads(text)
            records = parsed if isinstance(parsed, list) else parsed.get("value", parsed.get("data", []))
        else:
            records = list(csv.DictReader(io.StringIO(text)))
        for rec in records:
            row = {"polled_at": polled_at}
            row.update(rec)
            rows.append(row)
    except Exception:
        log_heartbeat(f"WARN ev_charging_points parse failed (raw file still saved): {traceback.format_exc().splitlines()[-1]}")

    if rows:
        # union of all keys seen, so new/unexpected fields don't get dropped
        fieldnames = sorted({k for r in rows for k in r.keys()})
        append_csv_rows("ev_charging_points", fieldnames, rows)

    return len(rows)


# ------------------------------------------------------------------ MAIN ---

def main_loop():
    log_heartbeat("=== collector started ===")
    while True:
        cycle_start = time.time()
        polled_at = now_sgt_str()
        try:
            n_carpark = poll_carpark_availability(polled_at)
        except Exception:
            n_carpark = None
            log_heartbeat(f"ERROR carpark_availability poll failed: {traceback.format_exc().splitlines()[-1]}")

        try:
            n_ev = poll_ev_charging_points(polled_at)
        except Exception:
            n_ev = None
            log_heartbeat(f"ERROR ev_charging_points poll failed: {traceback.format_exc().splitlines()[-1]}")

        log_heartbeat(f"OK cycle done - carpark_rows={n_carpark} ev_records={n_ev}")

        elapsed = time.time() - cycle_start
        time.sleep(max(0, POLL_INTERVAL_SECONDS - elapsed))


if __name__ == "__main__":
    while True:
        try:
            main_loop()
        except Exception:
            # main_loop already catches per-poll errors; this is a last-resort
            # net so an unexpected crash never actually ends the collection.
            log_heartbeat(f"FATAL main_loop crashed, restarting in 30s: {traceback.format_exc().splitlines()[-1]}")
            time.sleep(30)
