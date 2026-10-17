"""`optev-db migrate`. The live test touches the shared Neon database, so it runs only when
DATABASE_URL is in the environment itself (`uv run --env-file .env pytest`), not merely in .env."""

import os
import re

import pytest

from optev.ingest import cli


def test_usage_error_without_the_migrate_command(monkeypatch):
    monkeypatch.setattr("sys.argv", ["optev-db"])
    assert cli.main() == 2
    monkeypatch.setattr("sys.argv", ["optev-db", "upgrade"])
    assert cli.main() == 2


def test_migrate_without_a_database_url(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(cli, "MIGRATIONS", tmp_path / "migrations")  # no .env beside it
    assert cli.migrate() == 1
    assert "DATABASE_URL is not set" in capsys.readouterr().out


def test_migrate_reads_database_url_from_env_file(monkeypatch, tmp_path):
    import psycopg

    class Connected(Exception):
        pass

    def fake_connect(url: str) -> None:
        raise Connected(url)

    monkeypatch.setenv("DATABASE_URL", "")  # registered, so the .env value is undone after
    monkeypatch.delenv("DATABASE_URL")
    (tmp_path / ".env").write_text("DATABASE_URL=postgresql://from-env-file/x\n")
    monkeypatch.setattr(cli, "MIGRATIONS", tmp_path / "migrations")
    monkeypatch.setattr(psycopg, "connect", fake_connect)
    with pytest.raises(Connected, match="from-env-file"):
        cli.migrate()


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not in environment")
def test_migrate_twice_creates_every_table_and_postgis(capsys):
    import psycopg

    assert cli.migrate() == 0
    assert cli.migrate() == 0  # re-runnable, SYSTEM_DESIGN.md §2.3.6
    sql = "\n".join(p.read_text(encoding="utf-8") for p in cli.MIGRATIONS.glob("*.sql"))
    declared = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", sql))
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        ).fetchall()
        version = conn.execute("SELECT postgis_version()").fetchone()
    assert declared <= {r[0] for r in rows}
    assert version is not None and version[0]
    assert capsys.readouterr().out.count("postgis ") == 2
