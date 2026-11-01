"""Apply db/schema.sql to the database at INGEST_DATABASE_URL.

Usage:
    python -m db.init_db
"""
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
ANNOTATIONS_PATH = Path(__file__).parent / "annotations.sql"


def main() -> None:
    database_url = os.environ["INGEST_DATABASE_URL"]
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8") + "\n" + ANNOTATIONS_PATH.read_text(encoding="utf-8")

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(schema_sql)
        conn.commit()

    print("Schema applied successfully.")


if __name__ == "__main__":
    main()
