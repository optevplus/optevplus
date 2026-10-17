"""Small CLI for stage 1. `optev-db migrate`, `optev-db conform`."""

import os
import pathlib
import sys

MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "migrations"


def migrate() -> int:
    import psycopg

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")
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


def conform() -> int:
    import logging

    from optev.ingest.conform import conform as run

    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")
        return 1
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    for table, n in run().items():
        print(f"{table}: {n}")
    return 0


def main() -> int:
    verbs = {"migrate": migrate, "conform": conform}
    if len(sys.argv) < 2 or sys.argv[1] not in verbs:
        print("usage: optev-db migrate | conform")
        return 2
    return verbs[sys.argv[1]]()


if __name__ == "__main__":
    raise SystemExit(main())
