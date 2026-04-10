"""Apply all SQL migration files in order."""
import os
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


def run_migrations(database_url: str) -> None:
    migrations_dir = Path(__file__).parent
    sql_files = sorted(migrations_dir.glob("*.sql"))

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS _migrations (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        for sql_file in sql_files:
            already_applied = conn.execute(
                "SELECT 1 FROM _migrations WHERE filename = %s",
                (sql_file.name,)
            ).fetchone()

            if already_applied:
                print(f"  [skip] {sql_file.name} (already applied)")
                continue

            print(f"  [apply] {sql_file.name}")
            sql = sql_file.read_text()
            conn.execute(sql)
            conn.execute(
                "INSERT INTO _migrations (filename) VALUES (%s)",
                (sql_file.name,)
            )
            print(f"  [done] {sql_file.name}")


if __name__ == "__main__":
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)
    run_migrations(db_url)
    print("Migrations complete.")
