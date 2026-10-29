import copy
import json
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from compare_recovery import (
    checked_url, compare, fingerprint, run_comparison, summarize_differences, validate_targets,
)


def target(database):
    return {"host": "localhost", "port": 5432, "database": database}


def manifest():
    return {"version": 1, "frozen": True, "source": target("checkpoint"), "target": target("restore")}


def test_public_difference_summary_emits_only_allowlisted_categories_and_counts():
    comparison = {
        "matches": False,
        "source": {"private-row": "private-password"},
        "differences": [
            {"section": "tables", "object": "private-schema.private-table"},
            {"section": "tables", "object": "private-schema.other-table"},
            {"section": "schema", "object": "columns", "value": "private-row"},
            {"section": "schema", "object": "indexes"},
            {"section": "schema", "object": "columns"},
            {"section": "sequence_state", "object": "private-sequence"},
            {"section": "effective_table_access"},
            {"section": "normalization"},
            {"section": "schema", "object": "private-category"},
            {"section": "private-section", "object": "private-object"},
            {"section": ["private-section"]},
            "private-unstructured-error",
        ],
    }
    before = copy.deepcopy(comparison)
    summary = summarize_differences(comparison)
    assert summary == {
        "available": True,
        "difference_count": 12,
        "sections": {"tables": 2, "schema": 4, "sequence_state": 1,
                     "effective_table_access": 1, "normalization": 1},
        "schema_categories": ["columns", "indexes"],
        "unclassified_count": 4,
    }
    assert "private" not in json.dumps(summary)
    assert comparison == before and comparison["matches"] is False


@pytest.mark.parametrize("differences", [None, "private-error", {"private": "value"}])
def test_invalid_difference_payload_never_enters_public_summary(differences):
    assert summarize_differences({"differences": differences}) == {"available": False}


def test_empty_difference_summary_and_legacy_report():
    assert summarize_differences({"matches": True, "differences": []}) == {
        "available": True, "difference_count": 0, "sections": {},
        "schema_categories": [], "unclassified_count": 0,
    }
    assert summarize_differences({"matches": False}) == {"available": False}


def test_only_explicit_distinct_postgres_targets_are_allowed():
    source = "postgresql://operator:synthetic@localhost/checkpoint"
    destination = "postgresql://operator:synthetic@localhost/restore"
    source_url, target_url = validate_targets(manifest(), source, destination)
    assert source_url.database == "checkpoint" and target_url.database == "restore"
    assert source_url.drivername == "postgresql+psycopg2"
    with pytest.raises(ValueError):
        validate_targets(manifest(), source, source)
    invalid = manifest()
    invalid["frozen"] = False
    with pytest.raises(ValueError):
        validate_targets(invalid, source, destination)


@pytest.mark.parametrize("url", [
    "sqlite:///restore.db", "postgresql://operator@other.example/restore",
    "postgresql://operator@localhost/production",
    "postgresql://operator@localhost/restore?host=production.example",
    "postgresql://operator@localhost/restore?options=-csearch_path=private",
    "postgresql://operator@localhost/restore?service=production",
])
def test_unsafe_connections_are_rejected_before_connecting(url):
    with pytest.raises(ValueError):
        checked_url(url, target("restore"))


def test_hosted_targets_require_verified_tls_and_direct_connection():
    expected = {"host": "ep-example.example", "port": 5432, "database": "restore"}
    with pytest.raises(ValueError):
        checked_url("postgresql://operator@ep-example.example/restore?sslmode=require", expected)
    assert checked_url("postgresql://operator@ep-example.example/restore?sslmode=verify-full", expected)
    expected["host"] = "ep-example-pooler.example"
    with pytest.raises(ValueError):
        checked_url("postgresql://operator@ep-example-pooler.example/restore?sslmode=verify-full", expected)


@pytest.fixture
def recovery_pair():
    value = os.environ.get("RECOVERY_TEST_DATABASE_URL")
    if not value:
        pytest.skip("Disposable PostgreSQL recovery databases are not configured")
    url = make_url(value)
    assert url.host in {"localhost", "127.0.0.1"} and url.database == "veritras_cicd_source"
    engines = [create_engine(url), create_engine(url.set(database="veritras_cicd_target"))]
    for engine in engines:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE public.recovery_items(id serial PRIMARY KEY, payload jsonb NOT NULL, amount numeric(12,2))"))
            connection.execute(text("INSERT INTO public.recovery_items(payload,amount) VALUES ('{\"sensitive\":\"private-note\"}',12.34)"))
    try:
        yield engines
    finally:
        for engine in engines:
            with engine.begin() as connection:
                connection.execute(text("DROP VIEW IF EXISTS public.recovery_view"))
                connection.execute(text("DROP TABLE IF EXISTS public.recovery_extra"))
                connection.execute(text("DROP TABLE public.recovery_items CASCADE"))
                connection.execute(text("DROP SEQUENCE IF EXISTS public.recovery_items_id_seq"))
            engine.dispose()


def snapshots(engines):
    return [fingerprint(engine, expected_database=engine.url.database) for engine in engines]


def test_intact_postgres_snapshot_matches_and_never_emits_rows(recovery_pair):
    source, restored = snapshots(recovery_pair)
    assert compare(source, restored)["matches"]
    assert source["tables"]["public.recovery_items"]["count"] == 1
    assert source["read_only"] is True
    assert "private-note" not in json.dumps(source)
    before = copy.deepcopy(source)
    assert fingerprint(recovery_pair[0], expected_database=recovery_pair[0].url.database) == before


@pytest.mark.parametrize("statement,section", [
    ("UPDATE public.recovery_items SET amount=99", "tables"),
    ("DELETE FROM public.recovery_items", "tables"),
    ("ALTER TABLE public.recovery_items ADD COLUMN changed text", "schema"),
    ("CREATE INDEX changed_index ON public.recovery_items(amount)", "schema"),
    ("ALTER TABLE public.recovery_items ADD CONSTRAINT positive_amount CHECK(amount>0)", "schema"),
    ("SELECT nextval('public.recovery_items_id_seq')", "sequence_state"),
    ("ALTER SEQUENCE public.recovery_items_id_seq OWNED BY NONE", "schema"),
    ("CREATE TABLE public.recovery_extra(id integer)", "tables"),
    ("CREATE VIEW public.recovery_view AS SELECT id FROM public.recovery_items", "schema"),
])
def test_postgres_comparison_detects_data_and_schema_changes(recovery_pair, statement, section):
    with recovery_pair[1].begin() as connection:
        connection.execute(text(statement))
    result = compare(*snapshots(recovery_pair))
    assert result["matches"] is False
    assert any(item["section"] == section for item in result["differences"])


def test_wrong_connected_database_is_rejected(recovery_pair):
    with pytest.raises(ValueError, match="Unexpected recovery connection"):
        fingerprint(recovery_pair[0], expected_database="production")


def test_full_comparison_uses_validated_targets(recovery_pair):
    source, destination = [engine.url for engine in recovery_pair]
    approved = {"version": 1, "frozen": True}
    for key, url in [("source", source), ("target", destination)]:
        approved[key] = {"host": url.host, "port": url.port or 5432, "database": url.database}
    result = run_comparison(approved, source.render_as_string(hide_password=False), destination.render_as_string(hide_password=False))
    assert result["matches"]
    assert result["authorizes_activation"] is False
    assert result["limitations"]
