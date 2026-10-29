import copy
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import rehearse_hosted_recovery as hosted
from environment_policy import environment
from recovery_evidence import decrypt_archive
from replay_private_restore import (
    ReplayBlocked,
    reconcile_private,
    replay_fixed,
    validate_private_target,
)

KEY = "ab" * 32
SHA = "a" * 40


def config():
    return {
        "source_database": "checkpoint",
        "role": "owner",
        "rpo": 120,
        "rto": 600,
        "pg_major": 17,
        "sha": SHA,
        "run_id": "12345678",
        "attempt": "1",
        "environment": "testing",
        "approved_digest": "",
        "target_block": "",
        "target_hash": "",
    }


def valid_env():
    return {
        "REHEARSAL_BACKUP_KEY": KEY,
        "NEON_API_KEY": "private-neon-token",
        "REHEARSAL_OWNERSHIP_KEY": "private-ownership-key-1234567890123456",
        "SEPOLIA_RPC_URL": "https://provider.example/private-rpc-token",
    }


class FakeResources:
    project = "project-test"

    def __init__(self, cleanup_failure=False):
        self.client = SimpleNamespace(request=self.request, wait=lambda *a: None)
        self.created = self.cleaned = 0
        self.verified = 0
        self.cleanup_failure = cleanup_failure
        self.provider_calls = []

    def request(self, method, path, **kwargs):
        self.provider_calls.append((method, path))
        if method == "POST" and path.endswith("/roles/owner/reset_password"):
            return {
                "role": {
                    "branch_id": "br-private",
                    "name": "owner",
                    "password": "private-password",
                }
            }
        if method == "GET" and path.endswith("/databases"):
            return {"databases": [{"name": "checkpoint", "owner_name": "owner"}]}
        return {}

    def create(self, **kwargs):
        self.created += 1
        return {
            "project": self.project,
            "source": "br-source",
            "branch_id": "br-private",
            "endpoint_id": "ep-private",
            "host": "ep-private.region.neon.tech",
            "checkpoint_time": "2027-01-15T07:59:00Z",
            "parent_lsn": "0/123ABC",
            "expires": 1800007200,
        }

    def verify_live_ownership(self, _):
        self.verified += 1

    def cleanup(self):
        self.cleaned += 1
        if self.cleanup_failure:
            raise RuntimeError("private-neon-token")
        return {
            "state": "deleted" if self.created else "not_created",
            "deleted": self.created,
        }


@pytest.fixture
def drill(tmp_path, monkeypatch):
    def connection(resources, ledger, database, role):
        resources.verify_live_ownership(ledger)
        return f"postgresql://owner:private-password@localhost/{database}", {
            "host": "localhost",
            "port": 5432,
            "database": database,
        }

    monkeypatch.setattr(hosted, "clone_connection", connection)

    def restore(manifest, source, target, private, **kwargs):
        (private / "checkpoint.dump").write_text("private-production-data")
        return {"matches": True}

    calls = []

    def phase(name, manifest, output, env, **kwargs):
        calls.append((name, copy.deepcopy(env), kwargs))
        common = {
            "passed": True,
            "target_block": 11936013,
            "target_hash": "0x" + "1" * 64,
            "schema_revision": "e93a107bd624",
        }
        if name == "reconcile":
            result = {
                **common,
                "state": "reviewed",
                "plan_digest": "c" * 64,
                "history_matches": 0,
                "identity_changes": 0,
                "applied": False,
            }
        elif name == "fixed":
            result = {
                **common,
                "snapshot_digest": "a" * 64,
                "journal_prefix_digest": "b" * 64,
            }
        else:
            result = {
                **common,
                "state": "current",
                "lag_blocks": 0,
                "journal_prefix_digest": "b" * 64,
                "api_reads": {"passed": True},
            }
        output.write_text(json.dumps(result))
        return result

    def execute(resources=None, configuration=None, **overrides):
        args = {
            "verify": lambda _: {"verified": True},
            "admission": lambda sha: {"commit": sha},
            "restore": restore,
            "phase": phase,
            "clock": lambda: 100.0,
            "wall_clock": lambda: 1800000000.0,
        }
        args.update(overrides)
        return hosted.execute(
            configuration or config(),
            resources or FakeResources(),
            valid_env(),
            tmp_path,
            **args,
        )

    return execute, calls, tmp_path, phase


def test_complete_rehearsal_has_two_restarts_encrypted_evidence_and_no_production_secrets(
    drill,
):
    execute, calls, directory, _ = drill
    resources = FakeResources()
    report = execute(resources)
    assert report["overall_result"] == "pass"
    assert report["authorizes_activation"] is False
    assert report["restart_checks"]["restarts"] == 2
    assert report["RPO"]["passed"] and report["RTO"]["passed"]
    assert resources.cleaned == 1 and resources.verified >= 5
    assert report["clone_credentials_rotated"] is True
    assert (
        "POST",
        "/projects/project-test/branches/br-private/roles/owner/reset_password",
    ) in resources.provider_calls
    assert not any(
        "/branches/br-source/roles/" in path for _, path in resources.provider_calls
    )
    assert [name for name, _, _ in calls] == [
        "reconcile",
        "fixed",
        "fixed",
        "fixed",
        "live",
    ]
    assert calls[0][1]["INDEXER_ENABLED"] == "false"
    assert all(env["INDEXER_ENABLED"] == "true" for _, env, _ in calls[1:])
    for _, env, _ in calls:
        assert not {
            "NEON_API_KEY",
            "REHEARSAL_BACKUP_KEY",
            "REHEARSAL_OWNERSHIP_KEY",
        } & set(env)
        assert env["DATABASE_URL"].endswith("veritras_restore_12345678_1")
    serialized = json.dumps(report)
    assert all(
        value not in serialized
        for value in (
            "private-production-data",
            "private-password",
            "private-neon-token",
            "private-rpc-token",
        )
    )
    assert (
        b"private-production-data"
        not in (directory / "recovery-evidence.enc").read_bytes()
    )
    assert (
        decrypt_archive(
            directory / "recovery-evidence.enc", directory / "archive.tar", KEY
        )["candidate_sha"]
        == SHA
    )


def test_unverified_identity_never_creates_resources(drill):
    execute, calls, _, _ = drill
    resources = FakeResources()
    report = execute(
        resources,
        verify=lambda _: {"verified": False, "state": "deployment_evidence_missing"},
    )
    assert report["overall_result"] == "blocked" and resources.created == 0
    assert not calls and resources.cleaned == 1


def test_failed_comparison_reports_safe_categories_and_stops_before_replay(drill):
    execute, calls, directory, _ = drill
    resources = FakeResources()
    comparison = {
        "matches": False,
        "differences": [
            {"section": "schema", "object": "constraints"},
            {"section": "tables", "object": "private-schema.private-table"},
        ],
        "source": {"private-row": "private-password"},
    }
    report = execute(resources, restore=lambda *args, **kwargs: comparison)
    assert report["overall_result"] == "blocked"
    assert report["state"] == "restore_comparison_failed"
    assert report["authorizes_activation"] is False
    assert report["restore_comparison"]["matches"] is False
    assert report["restore_comparison"]["difference_summary"] == {
        "available": True, "difference_count": 2,
        "sections": {"schema": 1, "tables": 1},
        "schema_categories": ["constraints"], "unclassified_count": 0,
    }
    assert not calls and resources.cleaned == 1
    assert report["cleanup"]["state"] == "deleted"
    assert report["archive"]["state"] == "encrypted"
    assert json.loads((directory / "private/restore-comparison.json").read_text()) == comparison
    serialized = json.dumps(report)
    assert "private-schema" not in serialized
    assert "private-row" not in serialized
    assert "private-password" not in serialized
    assert hosted.console_summary(report) == {
        "overall_result": "blocked", "state": "restore_comparison_failed",
        "restore_difference_summary": report["restore_comparison"]["difference_summary"],
    }


def test_console_summary_preserves_preflight_output_and_excludes_other_report_fields():
    report = {"overall_result": "blocked", "state": "required_configuration_missing",
              "private_extra": "private-password"}
    assert hosted.console_summary(report) == {
        "overall_result": "blocked", "state": "required_configuration_missing",
    }


def test_wrong_rotation_scope_blocks_sql_connections_and_still_cleans(drill):
    execute, calls, _, _ = drill
    resources = FakeResources()
    request = resources.request

    def wrong_scope(method, path, **kwargs):
        result = request(method, path, **kwargs)
        if path.endswith("/reset_password"):
            result["role"]["branch_id"] = "br-source"
        return result

    resources.client.request = wrong_scope
    report = execute(resources)
    assert report["overall_result"] == "blocked"
    assert report["state"] == "private_credential_rotation_failed"
    assert not calls and resources.cleaned == 1
    assert not any("/connection_uri" in path for _, path in resources.provider_calls)


def test_queue_and_approval_time_count_toward_recovery_objective(drill):
    execute, _, _, _ = drill
    selected = {**config(), "triggered_at": 1799999970.0}
    report = execute(configuration=selected)
    assert report["RTO"]["seconds"] == 30
    assert report["RTO"]["includes_queue_setup_and_approval"]


def test_expired_recovery_window_stops_before_resource_creation(drill):
    execute, calls, _, _ = drill
    resources = FakeResources()
    report = execute(
        resources, configuration={**config(), "triggered_at": 1799999399.0}
    )
    assert report["state"] == "recovery_time_objective_exceeded_before_start"
    assert (
        report["overall_result"] == "blocked" and resources.created == 0 and not calls
    )


def test_declaring_an_environment_does_not_prove_review_protection():
    settings = {
        "name": "recovery-testing",
        "protection_rules": [],
        "deployment_branch_policy": {"protected_branches": True},
    }
    with pytest.raises(hosted.RehearsalBlocked, match="environment_review"):
        hosted.verify_environment_protection("recovery-testing", lambda _: settings)
    settings["protection_rules"] = [
        {"type": "required_reviewers", "reviewers": [{"type": "User"}]}
    ]
    hosted.verify_environment_protection("recovery-testing", lambda _: settings)
    settings["deployment_branch_policy"] = None
    with pytest.raises(hosted.RehearsalBlocked, match="branch_restriction"):
        hosted.verify_environment_protection("recovery-testing", lambda _: settings)


def test_fixed_replay_retries_bounded_failures_without_echoing_provider_errors():
    import time

    calls = []
    worker = SimpleNamespace(
        w3=SimpleNamespace(eth=SimpleNamespace(block_number=120)),
        _header=lambda _: "0xhash",
        last_processed_block=100,
    )

    def poll():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("private-provider-token")
        worker.last_processed_block = 108

    worker.poll_once = poll
    replay_fixed(worker, 108, "0xhash", 12, time.monotonic() + 2)
    assert len(calls) == 3


def test_reconciliation_review_stops_before_private_backfill_and_still_cleans(drill):
    execute, calls, _, phase = drill
    resources = FakeResources()

    def review(*args, **kwargs):
        result = phase(*args, **kwargs)
        return {**result, "passed": False, "state": "reconciliation_review_required"}

    report = execute(resources, phase=review)
    assert report["overall_result"] == "blocked"
    assert [name for name, _, _ in calls] == ["reconcile"]
    assert report["archive"]["state"] == "encrypted" and resources.cleaned == 1


@pytest.mark.parametrize("failure", ["restart", "cleanup", "encryption", "interrupt"])
def test_failure_never_passes_and_cleanup_is_attempted(drill, monkeypatch, failure):
    execute, calls, _, phase = drill
    resources = FakeResources(cleanup_failure=failure == "cleanup")
    if failure == "encryption":
        monkeypatch.setattr(
            hosted,
            "encrypt_files",
            lambda *a: (_ for _ in ()).throw(RuntimeError("secret")),
        )

    def changed(name, *args, **kwargs):
        if failure == "interrupt":
            raise KeyboardInterrupt()
        result = phase(name, *args, **kwargs)
        if failure == "restart" and name == "fixed" and len(calls) == 3:
            result["snapshot_digest"] = "different"
        return result

    report = execute(resources, phase=changed)
    assert report["overall_result"] == "blocked" and resources.cleaned == 1
    assert "private-neon-token" not in json.dumps(report)


def test_configuration_requires_trusted_main_explicit_objectives_and_strong_archive_key():
    env = {
        **valid_env(),
        "NEON_DATABASE_NAME": "neondb",
        "NEON_DATABASE_ROLE": "owner",
        "REHEARSAL_RPO_SECONDS": "120",
        "REHEARSAL_RTO_SECONDS": "600",
        "POSTGRES_MAJOR": "17",
        "GITHUB_REPOSITORY": "Oionos/Veritras",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": SHA,
        "GITHUB_WORKFLOW_REF": hosted.WORKFLOW,
        "REHEARSAL_ENVIRONMENT": "testing",
    }
    env.update(GITHUB_RUN_ID="12345678", GITHUB_RUN_ATTEMPT="1")
    assert hosted.configuration(env)["pg_major"] == 17
    for change in (
        {"GITHUB_REF": "refs/pull/1/merge"},
        {"REHEARSAL_RTO_SECONDS": ""},
        {"REHEARSAL_BACKUP_KEY": "weak"},
        {"REHEARSAL_TARGET_BLOCK": "10"},
    ):
        with pytest.raises((ValueError, ReplayBlocked, hosted.RehearsalBlocked)):
            hosted.configuration({**env, **change})


def test_dependent_reconciliation_preview_rolls_back_without_exact_digest(
    tmp_path, monkeypatch
):
    import manage_identity
    import manage_indexer

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE private_changes(id integer primary key, identity_applied integer default 0)"
            )
        )
    sessions = sessionmaker(bind=engine)

    def history(worker, db, events, apply=False):
        if apply:
            db.execute(text("INSERT INTO private_changes(id) VALUES (1)"))
        return {"matched_rows": 1, "conflicts": [], "applied": apply}

    def identity(worker, db, events, apply=False):
        assert (
            db.execute(text("SELECT count(*) FROM private_changes")).scalar_one() == 1
        )
        if apply:
            db.execute(text("UPDATE private_changes SET identity_applied=1"))
        return {
            "changes": [{"product_id": "private-product-id"}],
            "conflicts": [],
            "applied": apply,
        }

    monkeypatch.setattr(manage_indexer, "reconcile", history)
    monkeypatch.setattr(manage_identity, "reconcile", identity)
    worker = SimpleNamespace(_lock=lambda _: None, _header=lambda _: "0xhash")
    kwargs = {
        "context": {"target_block": 10, "target_hash": "0xhash", "candidate_sha": SHA},
        "plan_path": tmp_path / "private-plan.json",
    }
    result = reconcile_private(worker, sessions, [], approved_digest="", **kwargs)
    assert not result["passed"] and result["state"] == "reconciliation_review_required"
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM private_changes")
            ).scalar_one()
            == 0
        )
    accepted = reconcile_private(
        worker, sessions, [], approved_digest=result["plan_digest"], **kwargs
    )
    assert accepted["passed"] and accepted["applied"]
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT identity_applied FROM private_changes")
            ).scalar_one()
            == 1
        )
    engine.dispose()


def test_private_worker_refuses_unsafe_targets_and_wrong_scope():
    expected = environment("testing")
    manifest = {
        "target": {
            "host": "localhost",
            "port": 5432,
            "database": "veritras_restore_test_run",
        },
        "private_rehearsal": True,
        "environment": "testing",
        "branch_id": "br-private",
    }
    env = {
        "DATABASE_URL": "postgresql://operator@localhost/veritras_restore_test_run",
        "ENVIRONMENT": "testing",
        "CHAIN_ID": str(expected["chain_id"]),
        "PRODUCT_REGISTRY_CONTRACT": expected["registry"],
        "SHIPMENT_TRACKER_CONTRACT": expected["tracker"],
        "INDEXER_START_BLOCK": str(expected["start_block"]),
        "INDEXER_CONFIRMATIONS": str(expected["confirmations"]),
    }
    assert validate_private_target(manifest, env) == expected
    for change in (
        {"RENDER": "true"},
        {"DATABASE_URL": "postgresql://operator@localhost/production"},
        {"CHAIN_ID": "31337"},
    ):
        with pytest.raises((ValueError, ReplayBlocked)):
            validate_private_target(manifest, {**env, **change})
