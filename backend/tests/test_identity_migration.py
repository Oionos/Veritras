import os
from datetime import datetime
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
import manage_schema


@pytest.fixture(params=["sqlite", "postgres"])
def migration_db(request, tmp_path, monkeypatch):
    if request.param == "postgres":
        url = os.environ.get("INDEXER_TEST_DATABASE_URL")
        if not url:
            pytest.skip("Dedicated PostgreSQL regression database not configured")
        parsed = make_url(url)
        assert parsed.database == "veritras_indexer_regression" and parsed.host in (
            "localhost",
            "127.0.0.1",
            "postgres",
        )
    else:
        url = f'sqlite:///{tmp_path / "identity.db"}'
    engine = sa.create_engine(url)
    monkeypatch.setattr(manage_schema, "engine", engine)
    config = Config("alembic.ini")
    config.attributes["configure_logger"] = False
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "f04d9c21a873")
    yield engine
    meta = sa.MetaData()
    meta.reflect(engine)
    meta.drop_all(engine)
    engine.dispose()


def test_migration_preserves_legacy_and_signed_creation_times(migration_db):
    engine = migration_db
    with engine.begin() as conn:
        meta = sa.MetaData()
        p = sa.Table("products", meta, autoload_with=conn)
        for index, source in enumerate([None, "signed_draft"]):
            conn.execute(
                p.insert().values(
                    product_id=f"PROD-{index}",
                    name="Legacy",
                    manufacturer_address="untrusted",
                    ownership_source=source,
                    registered_at=datetime(2026, 1, 1),
                    block_number=0,
                    tx_hash="0x",
                )
            )
    manage_schema.migrate(apply=True)
    manage_schema.require_current_schema()
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT registration_status,created_at,chain_registered_at,on_chain_product_id,owner_address FROM products ORDER BY product_id"
            )
        ).all()
        assert tuple(rows[0]) == ("legacy_unreconciled", None, None, None, None)
        assert (
            rows[1][0] == "draft" and rows[1][1] and rows[1][2:] == (None, None, None)
        )


def test_duplicate_lifecycle_aborts_before_any_schema_change(migration_db):
    engine = migration_db
    with engine.begin() as conn:
        meta = sa.MetaData()
        p = sa.Table("products", meta, autoload_with=conn)
        s = sa.Table("shipments", meta, autoload_with=conn)
        conn.execute(
            p.insert().values(
                product_id="PROD-1",
                name="Legacy",
                manufacturer_address="untrusted",
                registered_at=datetime.now(),
                block_number=0,
                tx_hash="0x",
            )
        )
        for i in (1, 2):
            conn.execute(
                s.insert().values(
                    shipment_id=f"SHIP-{i}",
                    product_id="PROD-1",
                    origin="A",
                    destination="B",
                    status="0",
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                    block_number=0,
                    tx_hash="0x",
                )
            )
    with pytest.raises(RuntimeError, match="Duplicate shipment"):
        manage_schema.migrate(apply=True)
    assert "on_chain_product_id" not in {
        c["name"] for c in sa.inspect(engine).get_columns("products")
    }
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT count(*) FROM shipments")).scalar_one() == 2
        assert (
            conn.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            == "f04d9c21a873"
        )
    with pytest.raises(RuntimeError, match="Schema release"):
        manage_schema.require_current_schema()


def test_postgres_export_rehearses_rolls_back_and_guards_source(
    migration_db, monkeypatch, tmp_path
):
    if migration_db.dialect.name != "postgresql":
        pytest.skip("PostgreSQL transaction and SQL export contract")
    import json
    import export_schema_release

    monkeypatch.setattr(export_schema_release, "engine", migration_db)
    output = tmp_path / "release.json"
    assert export_schema_release.export_release(output) > 20
    statements = json.loads(output.read_text())["statements"]
    with migration_db.connect() as conn:
        assert (
            conn.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            == "f04d9c21a873"
        )
    assert "on_chain_product_id" not in {
        c["name"] for c in sa.inspect(migration_db).get_columns("products")
    }
    with migration_db.begin() as conn:
        for statement in statements:
            conn.exec_driver_sql(statement)
    manage_schema.require_current_schema()
    # A replay must abort at the source revision guard, with no partial DDL.
    with pytest.raises(sa.exc.DBAPIError, match="Schema release source changed"):
        with migration_db.begin() as conn:
            for statement in statements:
                conn.exec_driver_sql(statement)
    manage_schema.require_current_schema()


def test_sla_upgrade_preserves_historical_shipments_as_unknown(migration_db):
    engine = migration_db
    config = Config("alembic.ini")
    config.attributes["configure_logger"] = False
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "b47e203fa951")
        conn.execute(
            sa.text(
                "INSERT INTO products (product_id,name,manufacturer_address,registered_at,block_number,tx_hash,registration_status) VALUES ('SLA-LEGACY','Legacy','untrusted','2026-01-01',0,'0x','legacy_unreconciled')"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO shipments (shipment_id,product_id,origin,destination,status,created_at,updated_at,block_number,tx_hash) VALUES ('SLA-SHIP','SLA-LEGACY','A','B','3','2026-01-01','2026-01-01',0,'0x')"
            )
        )
        command.upgrade(config, "c62a904df318")
        assert (
            conn.execute(
                sa.text("SELECT expected_arrival_at FROM shipments")
            ).scalar_one()
            is None
        )
        assert conn.execute(sa.text("SELECT count(*) FROM shipments")).scalar_one() == 1
        assert (
            conn.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            == "c62a904df318"
        )
