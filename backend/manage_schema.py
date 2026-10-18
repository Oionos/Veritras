"""Inspect migration state and explicitly adopt a matching legacy schema.

The default is read-only. --apply upgrades a versioned or empty database.
--adopt-legacy additionally permits stamping a legacy schema, after checking all
baseline columns, nullability, primary keys, foreign keys and unique identities.
Never infer ownership from old manufacturer values.
"""

import argparse
import json
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core.database import engine

BASELINE = "d8ac2ee32ec4"
BASE_DIR = Path(__file__).resolve().parent
# These are the original migration's columns, not today's model metadata.
LEGACY = {
    "products": {
        "id": (sa.Integer, False),
        "product_id": (sa.String, False),
        "name": (sa.String, False),
        "description": (sa.String, True),
        "metadata_uri": (sa.String, True),
        "manufacturer_address": (sa.String, False),
        "registered_at": (sa.DateTime, False),
        "block_number": (sa.BigInteger, False),
        "tx_hash": (sa.String, False),
    },
    "checkpoints": {
        "id": (sa.Integer, False),
        "product_id": (sa.String, False),
        "location": (sa.String, False),
        "status": (sa.String, False),
        "handler_address": (sa.String, False),
        "notes": (sa.String, True),
        "timestamp": (sa.DateTime, False),
        "block_number": (sa.BigInteger, False),
        "tx_hash": (sa.String, False),
    },
    "custody_transfers": {
        "id": (sa.Integer, False),
        "product_id": (sa.String, False),
        "from_address": (sa.String, False),
        "to_address": (sa.String, False),
        "timestamp": (sa.DateTime, False),
        "block_number": (sa.BigInteger, False),
        "tx_hash": (sa.String, False),
    },
    "shipments": {
        "id": (sa.Integer, False),
        "shipment_id": (sa.String, False),
        "product_id": (sa.String, False),
        "origin": (sa.String, False),
        "destination": (sa.String, False),
        "status": (sa.String, False),
        "notes": (sa.String, True),
        "created_at": (sa.DateTime, False),
        "updated_at": (sa.DateTime, False),
        "block_number": (sa.BigInteger, False),
        "tx_hash": (sa.String, False),
    },
}


def legacy_differences(inspector) -> list[str]:
    differences = []
    tables = set(inspector.get_table_names()) - {"alembic_version"}
    if tables != set(LEGACY):
        return ["Legacy tables do not match the initial migration"]
    for table, expected in LEGACY.items():
        columns = {column["name"]: column for column in inspector.get_columns(table)}
        if set(columns) != set(expected):
            differences.append(f"{table}: columns differ from baseline")
            continue
        for name, (kind, nullable) in expected.items():
            actual = columns[name]
            if (
                not isinstance(actual["type"], kind)
                or actual["nullable"] != nullable
                or (kind is sa.String and actual["type"].length is not None)
                or (kind is sa.DateTime and actual["type"].timezone)
            ):
                differences.append(f"{table}.{name}: type or nullability differs")
        if inspector.get_pk_constraint(table)["constrained_columns"] != ["id"]:
            differences.append(f"{table}: primary key differs")
        foreign_keys = {
            (
                tuple(key["constrained_columns"]),
                key["referred_table"],
                tuple(key["referred_columns"]),
            )
            for key in inspector.get_foreign_keys(table)
        }
        expected_foreign_keys = (
            set()
            if table == "products"
            else {(("product_id",), "products", ("product_id",))}
        )
        if foreign_keys != expected_foreign_keys:
            differences.append(f"{table}: foreign keys differ")
        indexes = inspector.get_indexes(table)
        constraints = inspector.get_unique_constraints(table)
        unique_columns = {
            tuple(item["column_names"]) for item in indexes if item["unique"]
        }
        unique_columns.update(tuple(item["column_names"]) for item in constraints)
        identity = (
            "product_id"
            if table == "products"
            else "shipment_id" if table == "shipments" else None
        )
        if identity and (identity,) not in unique_columns:
            differences.append(f"{table}: unique public identity is missing")
    return differences


def migrate(*, apply=False, adopt_legacy=False):
    with engine.begin() as connection:
        if apply and connection.dialect.name == "postgresql":
            connection.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
            connection.execute(sa.text("SELECT pg_advisory_xact_lock(864382024)"))
            connection.execute(sa.text("SELECT pg_advisory_xact_lock(864382025)"))
        inspector = sa.inspect(connection)
        tables = set(inspector.get_table_names())
        revisions = (
            list(
                connection.execute(
                    sa.text("SELECT version_num FROM alembic_version")
                ).scalars()
            )
            if "alembic_version" in tables
            else []
        )
        legacy = bool(tables - {"alembic_version"}) and not revisions
        differences = legacy_differences(inspector) if legacy else []
        report = {
            "revisions": revisions,
            "legacy": legacy,
            "baseline_differences": differences,
        }
        print(json.dumps(report), flush=True)
        if not apply:
            return report
        if legacy and (not adopt_legacy or differences):
            raise RuntimeError(
                "Legacy schema requires review and --adopt-legacy; mismatches must be reconciled first"
            )
        config = Config(str(BASE_DIR / "alembic.ini"))
        config.attributes["configure_logger"] = False
        config.set_main_option("script_location", str(BASE_DIR / "alembic"))
        config.attributes["connection"] = connection
        if legacy:
            command.stamp(config, BASELINE)
        command.upgrade(config, "head")
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--adopt-legacy", action="store_true")
    args = parser.parse_args()
    migrate(apply=args.apply, adopt_legacy=args.adopt_legacy)


def require_current_schema():
    """Fail before serving requests if the explicit schema release is missing."""
    config = Config(str(BASE_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BASE_DIR / "alembic"))
    expected = set(ScriptDirectory.from_config(config).get_heads())
    with engine.connect() as connection:
        if not sa.inspect(connection).has_table("alembic_version"):
            raise RuntimeError(
                "Run the explicit manage_schema.py --apply release stage before starting the API"
            )
        actual = set(
            connection.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalars()
        )
    if actual != expected:
        raise RuntimeError(
            "Schema release is not current; run manage_schema.py --apply before starting the API"
        )
