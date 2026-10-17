import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from app.core.config import settings

import manage_schema


def test_fresh_migration_and_repeat_are_safe(tmp_path, monkeypatch):
    # Supplied connections must also tolerate URL-encoded credential characters.
    monkeypatch.setattr(settings, "database_url", "postgresql+psycopg2://example:encoded%40placeholder@unused.example/db")
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    monkeypatch.setattr(manage_schema, "engine", engine)
    manage_schema.migrate(apply=True)
    manage_schema.migrate(apply=True)
    assert "auth_challenges" in sa.inspect(engine).get_table_names()
    assert "owner_address" in {c["name"] for c in sa.inspect(engine).get_columns("products")}
    engine.dispose()


def test_legacy_adoption_checks_schema_and_preserves_unowned_records(tmp_path, monkeypatch):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    monkeypatch.setattr(manage_schema, "engine", engine)
    config = Config("alembic.ini")
    config.attributes["configure_logger"] = False
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, manage_schema.BASELINE)
        conn.execute(sa.text("DELETE FROM alembic_version"))
        conn.execute(sa.text("INSERT INTO products (id,product_id,name,manufacturer_address,registered_at,block_number,tx_hash) VALUES (1,'LEGACY','Existing','untrusted','2026-01-01',0,'0x')"))
    report = manage_schema.migrate()
    assert report["legacy"] and report["baseline_differences"] == []
    with pytest.raises(RuntimeError, match="requires review"):
        manage_schema.migrate(apply=True)
    manage_schema.migrate(apply=True, adopt_legacy=True)
    with engine.connect() as conn:
        row = conn.execute(sa.text("SELECT name,owner_address,ownership_source FROM products")).one()
        assert tuple(row) == ("Existing", None, None)
    engine.dispose()


def test_legacy_schema_mismatch_blocks_adoption(tmp_path, monkeypatch):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'mismatch.db'}")
    monkeypatch.setattr(manage_schema, "engine", engine)
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE products (id INTEGER PRIMARY KEY)"))
    with pytest.raises(RuntimeError, match="mismatches"):
        manage_schema.migrate(apply=True, adopt_legacy=True)
    assert "auth_challenges" not in sa.inspect(engine).get_table_names()
    engine.dispose()


def test_history_identity_migration_preserves_legacy_rows_and_enforces_uniqueness(tmp_path, monkeypatch):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'history.db'}")
    monkeypatch.setattr(manage_schema, 'engine', engine)
    config = Config('alembic.ini')
    config.attributes['configure_logger'] = False
    with engine.begin() as conn:
        config.attributes['connection'] = conn
        command.upgrade(config, 'b19e8a6c4f20')
        conn.execute(sa.text("INSERT INTO products (id,product_id,name,manufacturer_address,registered_at,block_number,tx_hash) VALUES (1,'LEGACY','Existing','untrusted','2026-01-01',1,'0xabc')"))
        for row_id in (1, 2):
            conn.execute(sa.text("INSERT INTO checkpoints (id,product_id,location,status,handler_address,timestamp,block_number,tx_hash) VALUES (:id,'LEGACY','Factory','0','untrusted','2026-01-01',1,'0xabc')"), {'id': row_id})
    manage_schema.migrate(apply=True)
    with engine.connect() as conn:
        assert conn.execute(sa.text('SELECT count(*) FROM checkpoints')).scalar_one() == 2
        assert conn.execute(sa.text('SELECT count(*) FROM checkpoints WHERE source_event_id IS NULL')).scalar_one() == 2
    with engine.begin() as conn:
        conn.execute(sa.text("UPDATE checkpoints SET source_event_id='specific-log' WHERE id=1"))
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as conn:
            conn.execute(sa.text("UPDATE checkpoints SET source_event_id='specific-log' WHERE id=2"))
    engine.dispose()
