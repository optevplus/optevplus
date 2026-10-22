"""Small CLI: `optev-db migrate`, `optev-db load-collected <path> [--day YYYY-MM-DD]`,
`optev-db load-static`, `optev-db conform` and `optev-db coverage`."""

import logging
import os
import pathlib
import sys
from datetime import date

MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "migrations"
USAGE = ("usage: optev-db migrate | optev-db load-collected <path> [--day YYYY-MM-DD]"
         " | optev-db load-static | optev-db conform | optev-db coverage")


def _database_url() -> str | None:
    from dotenv import load_dotenv

    load_dotenv(MIGRATIONS.parent / ".env")  # never overrides a variable already set
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")
    return url


def migrate() -> int:
    import psycopg

    url = _database_url()
    if not url:
        return 1
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        for path in sorted(MIGRATIONS.glob("*.sql")):
            cur.execute(path.read_text(encoding="utf-8"))
            print(f"applied {path.name}")
        cur.execute("SELECT postgis_version()")
        row = cur.fetchone()
        print(f"postgis {row[0] if row else 'unknown'}")
        conn.commit()
    return 0


def load_collected(args: list[str]) -> int:
    from optev.ingest.collect import load_collected as load

    if len(args) not in (1, 3) or (len(args) == 3 and args[1] != "--day"):
        print(USAGE)
        return 2
    root = pathlib.Path(args[0])
    if not root.is_dir():
        print(f"not a folder: {root}")
        return 2
    try:
        day = date.fromisoformat(args[2]) if len(args) == 3 else None
    except ValueError:
        print(f"not a date: {args[2]}")
        return 2
    if not _database_url():
        return 1
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for table, n in load(root, day).items():
        print(f"{table} +{n}")
    return 0


def load_static() -> int:
    from optev.ingest.static import load_static as load

    if not _database_url():
        return 1
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # it logs every pre-signed link
    for source, n in load().items():
        print(f"{source}: {n}")
    return 0


def conform() -> int:
    from optev.ingest.conform import conform as run

    if not _database_url():
        return 1
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for table, n in run().items():
        print(f"{table}: {n}")
    return 0


def coverage() -> int:
    """Measure the collected week and write one coverage_report run."""
    import psycopg

    from optev.ingest.coverage import collected_window, measure, write

    url = _database_url()
    if not url:
        return 1
    with psycopg.connect(url) as conn:
        start, end = collected_window(conn)
        metrics, skipped = measure(conn, start, end)
        run_at = write(conn, metrics)
    print(f"coverage_report run {run_at:%Y-%m-%d %H:%M:%S} for {start} to {end}")
    for name, (value, detail) in metrics.items():
        print(f"  {name:30s} {value:10.4f}  {detail}")
    if skipped:
        print("  not measured yet (inputs not loaded): " + ", ".join(skipped))
    return 0


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "migrate":
        return migrate()
    if len(sys.argv) >= 2 and sys.argv[1] == "load-collected":
        return load_collected(sys.argv[2:])
    if len(sys.argv) == 2 and sys.argv[1] == "load-static":
        return load_static()
    if len(sys.argv) == 2 and sys.argv[1] == "conform":
        return conform()
    if len(sys.argv) >= 2 and sys.argv[1] == "coverage":
        return coverage()
    print(USAGE)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
