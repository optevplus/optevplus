"""python -m optev.graph {ping | schema | apply-schema | heartbeat | load | clear} [--sample]
python -m optev.graph ask <question_type> [name=value ...]
python -m optev.graph explain "<question in plain English>"

Reads NEO4J_URI, NEO4J_USER and NEO4J_PASSWORD from the environment or SystemCode/.env.
"""

import argparse
import json
import sys

from dotenv import load_dotenv

from .client import driver, heartbeat, ping
from .ddl import apply_schema, statements
from .load import clear_sample, load
from .schema import SAMPLE_LABEL


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m optev.graph")
    parser.add_argument(
        "command",
        choices=["ping", "schema", "apply-schema", "heartbeat", "load", "clear", "ask", "explain"],
    )
    parser.add_argument("--sample", action="store_true", help="load or clear optev.sample")
    parser.add_argument("question", nargs="*", help="ask: <question_type> [name=value ...]")
    args = parser.parse_args(argv)
    load_dotenv()

    if args.command == "clear" and not args.sample:
        print("clear only removes the sample: use clear --sample.", file=sys.stderr)
        return 2

    if args.command == "schema":
        print(";\n".join(statements()) + ";")
    elif args.command == "ping":
        print(ping())
    elif args.command == "heartbeat":
        heartbeat()
        print("ok")
    elif args.command == "load" and not args.sample:
        import os

        from .load import load_all

        url = os.environ.get("DATABASE_URL")
        if not url:
            print("DATABASE_URL is not set; use load --sample for the sample.", file=sys.stderr)
            return 1
        counts = load_all(url)
        for name, n in counts.items():
            print(f"{n:6d}  {name}")
    elif args.command == "load":
        from optev.sample import load as sample

        with driver() as d, d.session() as s:
            apply_schema(s)
            counts = load(sample(), s, extra_label=SAMPLE_LABEL)
        for name, n in counts.items():
            print(f"{n:5d}  {name}")
    elif args.command == "ask":
        from .retrieve import TEMPLATES, retrieve

        if not args.question or "=" in args.question[0]:
            print(f"ask needs a question type: {', '.join(TEMPLATES)}", file=sys.stderr)
            return 2
        params = dict(p.split("=", 1) for p in args.question[1:])
        rows = retrieve(args.question[0], **params)
        print(json.dumps(rows, indent=1, default=str) if rows else "no evidence")
    elif args.command == "explain":
        from .explain import classify, explain
        from .llm import LLMNotConfigured
        from .retrieve import retrieve

        question = " ".join(args.question)
        try:
            answer = explain(question)
        except LLMNotConfigured as err:
            found = classify(question)
            print(f"No model configured ({err}). Evidence only:")
            if found is None:
                print("out of scope")
                return 0
            rows = retrieve(found[0], **found[1])
            print(found[0], found[1])
            print(json.dumps(rows, indent=1, default=str) if rows else "no evidence")
            return 0
        print(("REFUSED: " if answer.refused else "") + answer.text)
        if answer.cited:
            print("cites:", ", ".join(answer.cited))
        if answer.problems:
            print("failed checks:", "; ".join(answer.problems))
    elif args.command == "clear":
        with driver() as d, d.session() as s:
            print(f"removed {clear_sample(s)} sample nodes")
    else:
        with driver() as d, d.session() as s:
            n = apply_schema(s)
        print(f"applied {n} statements and seeded the source classes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
