"""Export an exact PostgreSQL migration after rehearsing it on an isolated copy.

The transaction is rolled back. The exported SQL includes source-data guards and
locks; apply it as ONE transaction using the deployment database owner's SQL
channel. Only public product/indexing tables are fingerprinted, never sessions.
No database credentials are included. This is for data-dependent migrations;
Alembic --sql cannot safely reflect or validate their source records.
"""

import argparse
import json
from pathlib import Path
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from app.core.database import engine
from manage_schema import BASE_DIR

SOURCE_TABLES = (
    "products",
    "shipments",
    "checkpoints",
    "custody_transfers",
    "indexed_products",
    "indexer_cursors",
    "chain_events",
    "alembic_version",
)


def fingerprint_sql(table):
    # Names come exclusively from the fixed allowlist above.
    return f"SELECT md5(COALESCE(string_agg(to_jsonb(t)::text, E'\\n' ORDER BY to_jsonb(t)::text), '')) FROM {table} t"


def export_release(output):
    url = make_url(str(engine.url))
    if (
        engine.dialect.name != "postgresql"
        or not (
            url.database.endswith("_identity_rehearsal")
            or url.database == "veritras_indexer_regression"
        )
        or url.host not in ("localhost", "127.0.0.1", "postgres")
    ):
        raise RuntimeError(
            "Export requires a local isolated *_identity_rehearsal PostgreSQL copy"
        )
    statements = [
        "SET LOCAL lock_timeout = '5s'",
        "SELECT pg_advisory_xact_lock(864382024)",
        "SELECT pg_advisory_xact_lock(864382025)",
    ]
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            # Block business/journal writes during guard verification and DDL.
            statements.append(
                "LOCK TABLE "
                + ", ".join(SOURCE_TABLES)
                + " IN SHARE ROW EXCLUSIVE MODE"
            )
            for table in SOURCE_TABLES:
                digest = connection.execute(
                    sa.text(fingerprint_sql(table))
                ).scalar_one()
                statements.append(
                    f"DO $$ BEGIN IF ({fingerprint_sql(table)}) IS DISTINCT FROM '{digest}' THEN RAISE EXCEPTION 'Schema release source changed: {table}'; END IF; END $$"
                )

            def capture(conn, cursor, statement, parameters, context, executemany):
                if statement.lstrip().split(None, 1)[0].upper() in {
                    "ALTER",
                    "CREATE",
                    "INSERT",
                    "UPDATE",
                    "DELETE",
                    "DROP",
                }:
                    if executemany:
                        for values in parameters:
                            statements.append(
                                cursor.mogrify(statement, values).decode()
                            )
                    else:
                        statements.append(
                            cursor.mogrify(statement, parameters).decode()
                        )

            sa.event.listen(connection, "before_cursor_execute", capture)
            try:
                config = Config(str(BASE_DIR / "alembic.ini"))
                config.set_main_option("script_location", str(BASE_DIR / "alembic"))
                config.attributes.update(connection=connection, configure_logger=False)
                command.upgrade(config, "head")
            finally:
                sa.event.remove(connection, "before_cursor_execute", capture)
        finally:
            transaction.rollback()
    # JSON statements retain exact SQL boundaries (including DO blocks).
    Path(output).write_text(json.dumps({"statements": statements}, indent=2) + "\n")
    Path(output).chmod(0o600)
    return len(statements)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            {"statements": export_release(args.output), "rehearsal_rolled_back": True}
        )
    )
