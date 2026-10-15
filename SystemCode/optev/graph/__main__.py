"""python -m optev.graph {ping | schema | apply-schema | heartbeat}

Reads NEO4J_URI, NEO4J_USER and NEO4J_PASSWORD from the environment or SystemCode/.env.
"""

import argparse
import sys

from dotenv import load_dotenv

from .client import driver, heartbeat, ping
from .ddl import apply_schema, statements


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m optev.graph")
    parser.add_argument("command", choices=["ping", "schema", "apply-schema", "heartbeat"])
    args = parser.parse_args(argv)
    load_dotenv()

    if args.command == "schema":
        print(";\n".join(statements()) + ";")
    elif args.command == "ping":
        print(ping())
    elif args.command == "heartbeat":
        heartbeat()
        print("ok")
    else:
        with driver() as d, d.session() as s:
            n = apply_schema(s)
        print(f"applied {n} statements and seeded the source classes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
