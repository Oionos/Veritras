from fastapi.testclient import TestClient
from sqlalchemy import inspect
from unittest.mock import MagicMock

from app.main import app
import app.main as main_module

client = TestClient(app)


def test_database_schema_matches_models(db_session):
    """Verify that all expected model tables exist in the database."""
    inspector = inspect(db_session.bind)
    table_names = set(inspector.get_table_names())
    expected = {"products", "checkpoints", "custody_transfers", "shipments"}
    assert expected.issubset(table_names), f"Missing tables: {expected - table_names}"


def test_health_check_degraded(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "indexer_enabled", True)
    monkeypatch.setattr(main_module, "indexer", None)
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "database": "connected",
        "web3": "disconnected",
    }


def test_health_check_ok_without_unnecessary_rpc(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "indexer_enabled", False)
    mock_w3 = MagicMock()
    monkeypatch.setattr(main_module, "w3", mock_w3)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "connected",
        "web3": "not_required",
    }
    mock_w3.is_connected.assert_not_called()
