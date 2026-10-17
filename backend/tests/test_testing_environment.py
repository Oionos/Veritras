from unittest.mock import MagicMock

import pytest

from app.core.config import Settings, settings
from app.services.indexer import EventIndexer, load_abi


@pytest.mark.parametrize("scheme", ["postgres", "postgresql"])
def test_postgres_url_uses_the_installed_driver(scheme):
    config = Settings(_env_file=None, database_url=f"{scheme}://user:password@postgres/testing")
    assert config.database_url.startswith("postgresql+psycopg2://")


def test_testing_rejects_live_contracts():
    with pytest.raises(ValueError, match="separate contract"):
        Settings(_env_file=None, environment="testing", jwt_secret_key="x" * 64,
                 product_registry_contract="0x1F76018532D619194f6628ADc186e3c86FcB5AaA")


def test_testing_requires_explicit_auth_secret():
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(_env_file=None, environment="testing", jwt_secret_key="dev-secret-change-in-production")


def test_bundled_abis_load():
    for name in ["ProductRegistry", "ShipmentTracker"]:
        assert any(entry["type"] == "event" for entry in load_abi(name))


def test_indexer_retries_startup_without_exposing_rpc_secret(monkeypatch, tmp_path):
    import app.services.indexer as module

    indexer = EventIndexer(rpc_url="https://secret.invalid/api-key")
    attempts = []

    def connect():
        attempts.append(True)
        if len(attempts) == 1:
            raise ConnectionError("https://secret.invalid/api-key")
        indexer.w3 = MagicMock()
        indexer.w3.eth.block_number = 0
        indexer.product_registry = MagicMock()
        indexer.shipment_tracker = MagicMock()

    monkeypatch.setattr(indexer, "_connect", connect)
    monkeypatch.setattr(module, "INDEXER_STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(settings, "indexer_start_block", 0)

    def wait(_):
        if len(attempts) > 1:
            indexer._stop_event.set()
        else:
            assert indexer.last_error == "ConnectionError"
        return False

    monkeypatch.setattr(indexer._stop_event, "wait", wait)
    indexer._run()
    assert len(attempts) == 2
    assert indexer.last_error is None
    assert indexer.last_processed_block == 0
    assert indexer.last_success_at


def test_readiness_reports_stopped_indexer(client_fixture, monkeypatch):
    import app.main as module
    stopped = MagicMock()
    stopped.health.return_value = {"status": "stopped", "last_error": "ConnectionError"}
    monkeypatch.setattr(module, "indexer", stopped)
    monkeypatch.setattr(settings, "indexer_enabled", True)
    response = client_fixture.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["indexer"]["status"] == "stopped"
    assert client_fixture.get("/health/live").status_code == 200
