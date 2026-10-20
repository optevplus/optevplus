"""`python -m optev.reasoning screen [--scenario ID] [--dry-run]`: screen every candidate site in
Postgres and print the funnel. Reads DATABASE_URL from the environment or `SystemCode/.env`."""

import argparse
import logging
import os
import sys
from pathlib import Path

from optev.reasoning.rules import screen_all

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m optev.reasoning")
    parser.add_argument("command", choices=["screen"])
    parser.add_argument("--scenario", default=None, help="scenario id; omit for the baseline")
    parser.add_argument("--dry-run", action="store_true", help="report the funnel, write nothing")
    args = parser.parse_args(argv)

    from dotenv import load_dotenv

    load_dotenv(ENV_FILE)  # never overrides a variable already set
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")
        return 1
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    funnel = screen_all(url, args.scenario, write=not args.dry_run)
    total = sum(funnel.values())
    print(f"screened {total} sites ({args.scenario or 'observed'})"
          f"{' - dry run, nothing written' if args.dry_run else ''}")
    for outcome, n in funnel.items():
        share = f"{n / total:6.1%}" if total else ""
        print(f"  {outcome.value:<12} {n:>6}  {share}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
