"""Shared test setup.

The graph live tests need NEO4J_* in the environment. Only those are copied from
SystemCode/.env: loading the whole file would also set DATABASE_URL and switch on the Neon
live tests, which run only when asked (`uv run --env-file .env pytest`).
"""

import os
from pathlib import Path

from dotenv import dotenv_values

for key, value in dotenv_values(Path(__file__).resolve().parents[1] / ".env").items():
    if key.startswith("NEO4J_") and value:
        os.environ.setdefault(key, value)
