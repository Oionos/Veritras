"""Storage regression uses a new, explicitly owned schema per PG test."""

import os
import uuid
import threading
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from alembic import command
from alembic.config import Config
from app.core.database import Base
from app.models.exception import ShipmentException, ExceptionEvaluation
from app.services.exceptions import evaluate, writer_lock
from app.services.indexer import IndexerBusy
from tests.test_exceptions import seed, HEALTH, START


@pytest.fixture(params=["sqlite", "postgres"])
def storage(request, tmp_path):
    admin = None
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
        # Never reflect or remove tables from a pre-existing schema.
        schema = "exception_test_" + uuid.uuid4().hex
        admin = sa.create_engine(url)
        with admin.begin() as conn:
            conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        url = parsed.update_query_dict({"options": f"-csearch_path={schema}"})
    else:
        url = f'sqlite:///{tmp_path / "exceptions.db"}'
    engine = sa.create_engine(url)
    try:
        yield engine, sessionmaker(engine, autoflush=False)
    finally:
        engine.dispose()
        if admin:
            # This random schema was created above by this fixture only.
            with admin.begin() as conn:
                conn.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()


def test_additive_migration_preserves_data_and_matches_metadata(storage):
    engine, sessions = storage
    config = Config("alembic.ini")
    config.attributes["configure_logger"] = False
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "c62a904df318")
    with sessions() as db:
        seed(db)
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "head")
    with sessions() as db:
        assert db.execute(sa.text("SELECT count(*) FROM shipments")).scalar() == 1
        assert db.execute(sa.text("SELECT count(*) FROM chain_events")).scalar() == 2
        assert db.query(ShipmentException).count() == 0
        assert (
            db.execute(sa.text("SELECT version_num FROM alembic_version")).scalar()
            == "e93a107bd624"
        )
        db.rollback()
        assert evaluate(db, lambda: HEALTH, now=START + timedelta(hours=25)) is None
    inspector = sa.inspect(engine)
    for table in ("exception_policies", "exception_evaluations", "shipment_exceptions"):
        assert {c["name"] for c in inspector.get_columns(table)} == set(
            Base.metadata.tables[table].columns.keys()
        )
    assert any(
        i["name"] == "uq_shipment_exception_open" and i["unique"]
        for i in inspector.get_indexes("shipment_exceptions")
    )


def test_restart_reuses_episode_and_acknowledgement(storage):
    engine, sessions = storage
    Base.metadata.create_all(engine)
    with sessions() as db:
        seed(db)
        evaluate(db, lambda: HEALTH, now=START + timedelta(hours=25))
        row = db.query(ShipmentException).first()
        identity = row.id
        row.acknowledged_at = START
        row.acknowledged_by = "0x" + "1" * 40
        db.commit()
    with sessions() as db:
        evaluate(db, lambda: HEALTH, now=START + timedelta(hours=26))
        assert db.query(ShipmentException).count() == 2
        assert db.get(ShipmentException, identity).acknowledged_at is not None


def test_interrupted_commit_rolls_back_entire_assessment(storage):
    engine, sessions = storage
    Base.metadata.create_all(engine)
    with sessions() as db:
        seed(db)
    with sessions() as db:

        def fail(session):
            raise RuntimeError("simulated interruption")

        sa.event.listen(db, "before_commit", fail)
        with pytest.raises(RuntimeError):
            evaluate(db, lambda: HEALTH, now=START + timedelta(hours=25))
    with sessions() as db:
        assert db.query(ShipmentException).count() == 0
        assert db.query(ExceptionEvaluation).count() == 0
        db.rollback()
        evaluate(db, lambda: HEALTH, now=START + timedelta(hours=25))
        assert db.query(ShipmentException).count() == 2


def test_concurrent_evaluators_deduplicate(storage):
    engine, sessions = storage
    Base.metadata.create_all(engine)
    with sessions() as db:
        seed(db)
    barrier = threading.Barrier(2)

    def task(_):
        first = True

        def health():
            nonlocal first
            if first:
                first = False
                barrier.wait(timeout=5)
            return HEALTH

        with sessions() as db:
            try:
                return evaluate(db, health, now=START + timedelta(hours=25))
            except IndexerBusy:
                return "busy"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(task, range(2)))
    assert None in results and set(results) <= {None, "busy"}
    with sessions() as db:
        assert db.query(ShipmentException).count() == 2


def test_indexer_lock_blocks_exception_writer(storage):
    engine, sessions = storage
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL advisory lock behavior")
    Base.metadata.create_all(engine)
    with sessions() as db:
        seed(db)
    with sessions() as owner, sessions() as contender:
        writer_lock(owner)
        with pytest.raises(IndexerBusy):
            evaluate(contender, lambda: HEALTH, now=START + timedelta(hours=25))
        owner.rollback()
        assert (
            evaluate(contender, lambda: HEALTH, now=START + timedelta(hours=25)) is None
        )
