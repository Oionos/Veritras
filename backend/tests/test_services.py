"""Controlled shipment cohorts: canonical evidence, filters, SLA and safe exports."""

import csv
from datetime import datetime, timedelta, timezone
from io import StringIO

import pytest
from sqlalchemy import event as sql_event

from app.models.chain import ChainEvent, IndexedProduct
from app.models.product import Product
from app.models.shipment import Shipment, Checkpoint
from app.services.analytics import (
    get_kpi_summary,
    shipment_dataset,
    parse_filters,
    calculate_avg_transit_time,
    calculate_on_time_rate,
    detect_anomalies,
    get_bottleneck_locations,
)
from app.services.export import export_to_csv, export_to_pdf, safe_csv
from tests.test_indexer import (
    stack,
)  # Same guarded SQLite/PostgreSQL regression fixture.

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
OWNER = "0x1234567890123456789012345678901234567890"
REGISTRY, TRACKER = "0x" + "1" * 40, "0x" + "2" * 40


def record(
    db,
    i,
    hours=10,
    sla=12,
    departed=True,
    delivered=True,
    origin=" A ",
    destination="B",
    created=None,
):
    key = "0x" + format(i + 1, "064x")
    product = Product(
        product_id=f"PROD-{i}",
        name="Widget",
        manufacturer_address=OWNER,
        owner_address=OWNER,
        ownership_source="chain_event",
        registered_at=START,
        chain_registered_at=START,
        registration_status="indexed",
        on_chain_product_id=key,
        chain_id=11155111,
        registry_address=REGISTRY,
        tracker_address=TRACKER,
        block_number=1,
        tx_hash="0xregistered",
    )
    db.add(product)
    db.flush()
    db.add(
        IndexedProduct(
            scope="analytics",
            product_key=key,
            product_id=product.product_id,
            baseline={},
            status="3" if delivered else "1",
        )
    )
    s = Shipment(
        shipment_id=f"SHIP-{i}",
        product_id=product.product_id,
        origin=origin,
        destination=destination,
        status="3",
        created_at=created or START,
        expected_arrival_at=START + timedelta(hours=sla) if sla is not None else None,
        expected_arrival_recorded_at=(
            START - timedelta(hours=1) if sla is not None else None
        ),
    )
    db.add(s)
    db.flush()
    for n, (kind, status, timestamp) in enumerate(
        [
            ("CheckpointRecorded", "1", START) if departed else (None, None, None),
            (
                ("DeliveryCompleted", "3", START + timedelta(hours=hours))
                if delivered
                else (None, None, None)
            ),
        ]
    ):
        if kind:
            db.add(
                ChainEvent(
                    occurrence_id=f"{i}-{n}",
                    event_id=f"event-{i}-{n}",
                    scope="analytics",
                    chain_id=11155111,
                    contract_address=TRACKER,
                    transaction_hash=f"0xtx{i}{n}",
                    log_index=n,
                    transaction_index=0,
                    block_number=10 + i * 2 + n,
                    block_hash=f"0xblock{i}{n}",
                    event_type=kind,
                    product_key=key,
                    payload={
                        "timestamp": int(timestamp.timestamp()),
                        "status": status,
                        "location": origin,
                        "notes": "=malicious",
                    },
                    canonical=True,
                    processed_at=START,
                )
            )
    db.flush()
    return s


def controlled(db):
    record(db, 0, hours=10, sla=12)
    record(db, 1, hours=20, sla=12)
    record(db, 2, hours=30, sla=None)
    record(db, 3, delivered=False)
    record(db, 4, departed=False, delivered=False)
    record(
        db, 5, departed=False
    )  # Delivered but no departure: not a transit/SLA sample.
    db.commit()


def assert_summary(db):
    result = get_kpi_summary(db)
    assert result["total_shipments"] == 6
    assert result["delivered_shipments"] == 4
    assert result["active_shipments"] == 2
    assert result["avg_transit_time_hours"] == 20
    assert result["transit_sample_size"] == 3
    assert result["incomplete_transit_shipments"] == 3
    assert result["sla_sample_size"] == 2
    assert result["unknown_sla_deliveries"] == 1
    assert result["incomplete_sla_deliveries"] == 1
    assert result["on_time_rate_percent"] == 50
    assert result["active_elapsed_sample_size"] == 1
    assert result["awaiting_departure_shipments"] == 1
    assert len(result["routes"]) == 1
    assert calculate_avg_transit_time(db) == 20
    assert calculate_on_time_rate(db) == 50


def test_controlled_cohort_both_dialects(stack):
    with stack.sessions() as db:
        controlled(db)
        assert_summary(db)
        rows = list(csv.DictReader(StringIO(export_to_csv(db))))
        assert len(rows) == 6
        assert sum(row["delivered"] == "True" for row in rows) == 4
        assert sum(row["sla_eligible"] == "True" for row in rows) == 2
        assert sum(row["on_time"] == "True" for row in rows) == 1
        assert (
            sum(int(r["event_count"]) for r in rows)
            == get_kpi_summary(db)["event_count"]
        )
        assert (
            len(list(csv.DictReader(StringIO(export_to_csv(db, report="events")))))
            == get_kpi_summary(db)["event_count"]
        )


def test_canonical_reorg_and_scope_are_authoritative(db_session):
    record(db_session, 0)
    db_session.commit()
    assert get_kpi_summary(db_session)["delivered_shipments"] == 1
    delivery = (
        db_session.query(ChainEvent).filter_by(event_type="DeliveryCompleted").one()
    )
    delivery.canonical = False
    db_session.commit()
    result = get_kpi_summary(db_session)
    assert result["delivered_shipments"] == 0
    assert result["avg_transit_time_hours"] is None
    assert result["on_time_rate_percent"] is None
    delivery.canonical = True
    delivery.contract_address = REGISTRY  # Wrong emitting contract is not proof.
    db_session.commit()
    assert get_kpi_summary(db_session)["delivered_shipments"] == 0
    delivery.contract_address = TRACKER
    delivery.chain_id = 1
    db_session.commit()
    assert get_kpi_summary(db_session)["delivered_shipments"] == 0
    delivery.chain_id = 11155111
    delivery.scope = "wrong"
    db_session.commit()
    assert get_kpi_summary(db_session)["delivered_shipments"] == 0


def test_products_legacy_checkpoints_and_status_do_not_invent_shipments(db_session):
    db_session.add(
        Product(
            product_id="DRAFT",
            name="Draft",
            manufacturer_address=OWNER,
            registered_at=START,
            block_number=0,
            tx_hash="0x",
        )
    )
    db_session.flush()
    db_session.add(
        Checkpoint(
            product_id="DRAFT",
            location="A",
            status="3",
            handler_address=OWNER,
            timestamp=START,
            block_number=1,
            tx_hash="untrusted",
        )
    )
    db_session.commit()
    assert get_kpi_summary(db_session)["total_shipments"] == 0
    db_session.add(
        Shipment(
            shipment_id="LEGACY",
            product_id="DRAFT",
            origin="A",
            destination="B",
            status="3",
        )
    )
    db_session.commit()
    result = get_kpi_summary(db_session)
    assert result["total_shipments"] == 1
    assert result["delivered_shipments"] == 0
    assert result["avg_transit_time_hours"] is None


def test_filters_full_end_day_routes_and_export_counts(client_fixture, db_session):
    record(db_session, 0, created=START)
    record(db_session, 1, created=START + timedelta(hours=23, minutes=59, seconds=59))
    record(db_session, 2, created=START + timedelta(days=1))
    record(db_session, 3, origin="Other")
    db_session.commit()
    params = "start_date=2026-01-01&end_date=2026-01-01&origin=a&destination=b"
    result = client_fixture.get("/analytics/kpis?" + params).json()
    assert result["total_shipments"] == 2
    assert result["filters"]["end_exclusive"] == "2026-01-02T00:00:00+00:00"
    assert result["trend"]["percent_change"] is None
    rows = list(
        csv.DictReader(
            StringIO(client_fixture.get("/analytics/export?format=csv&" + params).text)
        )
    )
    assert len(rows) == result["total_shipments"]
    assert {r["shipment_id"] for r in rows} == {"SHIP-0", "SHIP-1"}
    pdf = client_fixture.get("/analytics/export?format=pdf&" + params)
    assert pdf.content.startswith(b"%PDF")
    assert client_fixture.get("/analytics/anomalies?" + params).json() == []
    assert client_fixture.get("/analytics/bottlenecks?" + params).status_code == 200


@pytest.mark.parametrize(
    "params",
    [
        "start_date=not-date",
        "end_date=2026-02-30",
        "start_date=2026-02-02&end_date=2026-02-01",
        "end_date=9999-12-31",
    ],
)
@pytest.mark.parametrize(
    "path", ["kpis", "export", "anomalies", "bottlenecks", "daily-volume"]
)
def test_invalid_dates_are_422(client_fixture, path, params):
    assert client_fixture.get(f"/analytics/{path}?{params}").status_code == 422


@pytest.mark.parametrize(
    "value",
    [
        '=HYPERLINK("bad")',
        "+SUM(1,2)",
        "-1+2",
        "@SUM(1)",
        " \t=1",
        "\n=1",
        "\r=1",
        "\ttext",
        "\u00a0=1",
        "\ufeff=1",
    ],
)
def test_formula_neutralization(value):
    assert safe_csv(value) == "'" + value
    assert safe_csv("ordinary text") == "ordinary text"


def test_real_exports_escape_text_and_keep_empty_headers(db_session):
    assert export_to_csv(db_session).startswith("shipment_id,product_id,")
    shipment = record(db_session, 0, origin="=SUM(1,2)")
    shipment.notes = "<script>&" + "x" * 2000
    db_session.commit()
    rows = list(csv.DictReader(StringIO(export_to_csv(db_session))))
    assert rows[0]["origin"] == "'=SUM(1,2)"
    events = list(csv.DictReader(StringIO(export_to_csv(db_session, report="events"))))
    assert events[0]["notes"] == "'=malicious"
    assert events[0]["event_id"] == "event-0-0"
    assert export_to_pdf(db_session).startswith(b"%PDF")


def test_anomalies_require_ten_same_route_completed_samples(db_session):
    for i in range(9):
        record(db_session, i, hours=10 if i < 8 else 100)
    record(db_session, 9, hours=10, origin="Other")
    db_session.commit()
    assert detect_anomalies(db_session, 1.5) == []
    record(db_session, 10, hours=10)
    db_session.commit()
    anomalies = detect_anomalies(db_session, 2)
    assert len(anomalies) == 1
    assert anomalies[0].sample_size == 10
    assert anomalies[0].origin == "a"
    assert anomalies[0].product_id == "PROD-8"
    assert (
        get_bottleneck_locations(db_session) == []
    )  # Delivery event is not an invented checkpoint.


def test_expected_arrival_permissions_timezone_and_lock(client_fixture, db_session):
    s = record(db_session, 0, departed=False, delivered=False, sla=None)
    db_session.commit()
    url = "/shipments/" + s.shipment_id
    assert (
        client_fixture.put(
            url, json={"expected_arrival_at": "2026-01-02T00:00:00"}
        ).status_code
        == 422
    )
    assert (
        client_fixture.put(
            url, json={"departed_at": "2026-01-01T00:00:00Z"}
        ).status_code
        == 422
    )
    response = client_fixture.put(
        url, json={"expected_arrival_at": "2026-01-02T08:00:00+08:00"}
    )
    assert response.status_code == 200
    assert response.json()["expected_arrival_at"].startswith("2026-01-02T00:00:00")
    p = record(db_session, 1)
    db_session.commit()
    assert (
        client_fixture.put(
            "/shipments/" + p.shipment_id, json={"expected_arrival_at": None}
        ).status_code
        == 409
    )
    response = client_fixture.get("/shipments/")
    assert response.status_code == 200
    item = next(
        i for i in response.json()["items"] if i["shipment_id"] == p.shipment_id
    )
    assert item["departed_at"] is not None and item["delivered_at"] is not None
    db_session.query(Shipment).filter_by(id=p.id).delete()
    db_session.commit()
    response = client_fixture.post(
        "/shipments/",
        json={
            "product_id": p.product_id,
            "origin": "A",
            "destination": "B",
            "expected_arrival_at": "2027-01-01T00:00:00Z",
        },
    )
    assert response.status_code == 409


def test_one_journal_query_no_per_shipment_loads(db_session):
    for i in range(12):
        record(db_session, i)
    db_session.commit()
    statements = []

    def observe(*args):
        statements.append(args[2])

    sql_event.listen(db_session.bind, "before_cursor_execute", observe)
    try:
        rows = shipment_dataset(db_session)
        assert len(rows) == 12
        assert len(statements) == 1
    finally:
        sql_event.remove(db_session.bind, "before_cursor_execute", observe)


def test_checkpoint_intervals_are_not_dwell_claims(db_session):
    record(db_session, 0, delivered=False)
    previous = db_session.query(ChainEvent).one()
    values = {c.name: getattr(previous, c.name) for c in ChainEvent.__table__.columns}
    values.update(
        occurrence_id="next",
        event_id="next",
        block_number=12,
        log_index=1,
        payload={
            "timestamp": int((START + timedelta(hours=36)).timestamp()),
            "location": "Next",
            "status": "2",
        },
    )
    db_session.add(ChainEvent(**values))
    db_session.commit()
    assert get_bottleneck_locations(db_session) == [
        {"location": "a", "avg_interval_hours": 36, "incident_count": 1}
    ]


def test_equal_period_trend_zero_baseline_and_underflow(db_session):
    record(db_session, 0, created=START)
    record(db_session, 1, created=START - timedelta(days=1))
    record(db_session, 2, created=START)
    db_session.commit()
    trend = get_kpi_summary(db_session, parse_filters("2026-01-01", "2026-01-01"))[
        "trend"
    ]
    assert trend["current_count"] == 2 and trend["previous_count"] == 1
    assert trend["percent_change"] == 100
    assert (
        get_kpi_summary(db_session, parse_filters("0001-01-01", "0001-01-02"))["trend"]
        is None
    )


def test_pdf_uses_same_counts_and_evidence_as_api(db_session, monkeypatch):
    from app.services import export
    from reportlab.platypus import Paragraph

    controlled(db_session)
    text = []
    monkeypatch.setattr(
        export.SimpleDocTemplate,
        "build",
        lambda self, story: text.extend(
            p.getPlainText() for p in story if isinstance(p, Paragraph)
        ),
    )
    export_to_pdf(db_session)
    report = "\n".join(text)
    assert "Total Shipments: 6" in report and "Delivered: 4" in report
    assert "Completed transit samples: 3" in report and "SLA samples: 2" in report
    assert "event-0-1" in report and "0xtx01" in report


def test_sla_write_requires_owner(client_fixture, db_session):
    from app.core.auth import create_access_token

    record(db_session, 0, departed=False, delivered=False)
    db_session.commit()
    response = client_fixture.put(
        "/shipments/SHIP-0",
        json={"expected_arrival_at": "2027-01-01T00:00:00Z"},
        headers={"Authorization": "Bearer " + create_access_token("0x" + "9" * 40)},
    )
    assert response.status_code == 403


def test_lagged_indexing_cannot_accept_a_retrospective_sla(db_session):
    shipment = record(db_session, 0)
    shipment.expected_arrival_recorded_at = START + timedelta(minutes=1)
    db_session.commit()
    result = get_kpi_summary(db_session)
    assert result["delivered_shipments"] == 1
    assert result["sla_sample_size"] == 0
    assert result["on_time_rate_percent"] is None
    assert result["late_sla_deliveries"] == 1
    shipment.expected_arrival_recorded_at = None
    db_session.commit()
    assert get_kpi_summary(db_session)["sla_sample_size"] == 0
