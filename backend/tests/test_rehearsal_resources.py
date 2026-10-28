import copy
import json

import pytest

from manage_rehearsal_resources import (
    NeonClient,
    RecoveryResources,
    ResourceError,
    timestamp,
)

NOW = 1800000000
KEY = "recovery-test-ownership-key-only-123456"
SHA = "a" * 40


class FakeNeon:
    def __init__(self):
        self.calls = []
        self.items = {
            "br-source": {
                "id": "br-source",
                "project_id": "project-test",
                "parent_id": None,
                "name": "production",
                "default": True,
                "protected": True,
            }
        }
        self.endpoint = {
            "id": "ep-private",
            "project_id": "project-test",
            "branch_id": "br-private",
            "type": "read_write",
            "host": "ep-private.region.neon.tech",
            "autoscaling_limit_max_cu": 0.5,
        }
        self.timeout_after_create = False
        self.ledger = None

    def request(self, method, path, body=None, query=None):
        self.calls.append((method, path, copy.deepcopy(body), query))
        if method == "GET" and path == "/projects/project-test":
            return {
                "project": {
                    "id": "project-test",
                    "pg_version": 17,
                    "history_retention_seconds": 86400,
                }
            }
        if method == "POST" and path.endswith("/branches"):
            assert json.loads(self.ledger.read_text())["branch_id"] is None
            self.items["br-private"] = {
                "id": "br-private",
                "project_id": "project-test",
                "parent_id": "br-source",
                "default": False,
                "protected": False,
                "current_state": "ready",
                "name": body["branch"]["name"],
                "expires_at": body["branch"]["expires_at"],
                "created_at": timestamp(NOW),
                "parent_lsn": "0/123ABC",
            }
            if self.timeout_after_create:
                raise ResourceError("provider_request_failed")
            return {
                "branch": copy.deepcopy(self.items["br-private"]),
                "endpoints": [copy.deepcopy(self.endpoint)],
            }
        if method == "GET" and "/endpoints/" in path:
            return {"endpoint": copy.deepcopy(self.endpoint)}
        if method == "GET" and path.endswith("/branches"):
            return {
                "branches": copy.deepcopy(list(self.items.values())),
                "pagination": {},
            }
        identifier = path.rsplit("/", 1)[-1]
        if method == "GET" and identifier in self.items:
            return {"branch": copy.deepcopy(self.items[identifier])}
        if method == "DELETE" and identifier in self.items:
            del self.items[identifier]
            return {}
        raise ResourceError("provider_not_found")

    def wait(self, *_):
        pass


@pytest.fixture
def resources(tmp_path):
    api = FakeNeon()
    manager = RecoveryResources(
        api,
        project="project-test",
        source="br-source",
        environment="production",
        ownership_key=KEY,
        ledger=tmp_path / "ledger.json",
        clock=lambda: NOW,
    )
    api.ledger = manager.ledger
    return manager, api


def create(manager):
    return manager.create(run_id="123456", attempt="1", sha=SHA)


def test_owned_checkpoint_has_expiry_budget_and_private_ledger(resources):
    manager, api = resources
    ledger = create(manager)
    assert ledger["branch_id"] == "br-private"
    assert manager.owned_name(ledger["name"])
    assert ledger["checkpoint_time"] == timestamp(NOW - 60)
    assert manager.ledger.stat().st_mode & 0o777 == 0o600
    request = next(call[2] for call in api.calls if call[0] == "POST")
    assert request["branch"]["expires_at"] == timestamp(NOW + 7200)
    assert request["branch"]["parent_id"] == "br-source"
    assert request["endpoints"][0]["autoscaling_limit_max_cu"] == 0.5
    manager.verify_live_ownership(ledger)
    assert manager.cleanup() == {"state": "deleted", "deleted": 1}
    assert manager.cleanup()["state"] == "already_deleted"
    assert "br-source" in api.items


@pytest.mark.parametrize(
    "field,value",
    [
        ("project_id", "other-project"),
        ("parent_id", "br-other"),
        ("default", True),
        ("protected", True),
        ("name", "production"),
        ("created_at", timestamp(NOW - 1000)),
        ("expires_at", timestamp(NOW + 9999)),
    ],
)
def test_cleanup_refuses_changed_or_protected_resources(resources, field, value):
    manager, api = resources
    create(manager)
    api.items["br-private"][field] = value
    with pytest.raises(ResourceError):
        manager.cleanup()
    assert not any(call[0] == "DELETE" for call in api.calls)
    assert "br-source" in api.items


def test_creation_timeout_rediscovers_exact_intent_without_repeating_post(resources):
    manager, api = resources
    api.timeout_after_create = True
    with pytest.raises(ResourceError):
        create(manager)
    assert manager.cleanup()["state"] == "deleted"
    assert len([call for call in api.calls if call[0] == "POST"]) == 1
    assert "br-source" in api.items


def test_reaper_only_removes_authenticated_expired_resources(resources):
    manager, api = resources
    ledger = create(manager)
    api.items["br-unowned"] = {
        **api.items["br-private"],
        "id": "br-unowned",
        "name": "vr-recovery-forged",
    }
    assert manager.reap_expired()["deleted"] == 0
    manager.clock = lambda: NOW + 7201
    assert manager.reap_expired()["deleted"] == 1
    assert set(api.items) == {"br-source", "br-unowned"}
    wrong = RecoveryResources(
        api,
        project="project-test",
        source="br-source",
        environment="production",
        ownership_key="another-ownership-key-123456789012345",
        ledger=manager.ledger,
    )
    assert not wrong.owned_name(ledger["name"])


def test_branch_limit_fails_before_creation(resources):
    manager, api = resources
    manager.max_branches = 1
    with pytest.raises(ResourceError, match="budget"):
        create(manager)
    assert not manager.ledger.exists()
    assert not any(call[0] == "POST" for call in api.calls)


def test_missing_expiry_is_failure_and_known_branch_still_cleans(resources):
    manager, api = resources
    original = api.request

    def request(method, path, **kwargs):
        result = original(method, path, **kwargs)
        if method == "GET" and path.endswith("/br-private"):
            result["branch"].pop("expires_at", None)
        return result

    api.request = request
    with pytest.raises(ResourceError, match="expiration"):
        create(manager)
    assert manager.cleanup()["state"] == "deleted"


def test_wrong_endpoint_and_modified_ledger_are_rejected(resources):
    manager, api = resources
    ledger = create(manager)
    api.endpoint["branch_id"] = "br-source"
    with pytest.raises(ResourceError, match="endpoint"):
        manager.verify_live_ownership(ledger)
    ledger["source"] = "br-other"
    manager.ledger.write_text(json.dumps(ledger))
    with pytest.raises(ResourceError, match="ledger"):
        manager.cleanup()
    assert not any(call[0] == "DELETE" for call in api.calls)


@pytest.mark.parametrize("status", ["failed", "cancelled", "running"])
def test_provider_operation_failures_and_deadlines_are_bounded(status):
    client = NeonClient("synthetic-private-key")
    client.request = lambda *args, **kwargs: {"operation": {"status": status}}
    with pytest.raises(ResourceError, match="operation_failed_or_timed_out"):
        client.wait("project-test", {"operations": [{"id": "operation-id"}]}, timeout=0)


def test_paginated_listing_cannot_silently_truncate_cleanup_scope(resources):
    manager, api = resources
    original = api.request

    def request(method, path, **kwargs):
        if path.endswith("/branches"):
            return {"branches": [], "pagination": {"next": "repeated-cursor"}}
        return original(method, path, **kwargs)

    api.request = request
    with pytest.raises(ResourceError, match="listing_incomplete"):
        manager.reap_expired()
    assert not any(call[0] == "DELETE" for call in api.calls)
