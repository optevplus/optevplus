"""Small CLI so day-one verification has something to run. `optev-db migrate`."""

import os
import pathlib
import sys

MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "migrations"


def migrate() -> int:
    import psycopg
    from dotenv import load_dotenv

    load_dotenv(MIGRATIONS.parent / ".env")  # never overrides a variable already set
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


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] != "migrate":
        print("usage: optev-db migrate")
        return 2
    return migrate()


if __name__ == "__main__":
    raise SystemExit(main())
