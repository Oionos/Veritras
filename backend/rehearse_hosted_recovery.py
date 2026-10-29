"""Trusted-main private Neon recovery rehearsal; never production activation."""

import argparse
from datetime import datetime, timezone
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import time

from sqlalchemy.engine import make_url

from check_deployment_identity import configured_verification
from compare_recovery import checked_url, digest, summarize_differences
from environment_policy import environment, load_policy, policy_digest
from manage_rehearsal_resources import (
    ResourceError,
    epoch,
    from_environment,
    private_json,
)
from recovery_evidence import encrypt_files, key_bytes
from rehearse_recovery_restore import restore_checkpoint
from release_gate import assess, github

WORKFLOW = "Oionos/Veritras/.github/workflows/recovery-rehearsal.yml@refs/heads/main"


class RehearsalBlocked(Exception):
    pass


def console_summary(report):
    result = {"overall_result": report["overall_result"], "state": report["state"]}
    comparison = report.get("restore_comparison", {})
    if "difference_summary" in comparison:
        result["restore_difference_summary"] = comparison["difference_summary"]
    if report["state"] == "deployment_identity_not_verified":
        identity = report.get("deployment_identity", {})
        result["deployment_identity"] = {key: identity[key] for key in
                                         ("state", "rpc_http_status", "rpc_error_code") if key in identity}
    return result


def configuration(env):
    required = (
        "NEON_DATABASE_NAME",
        "NEON_DATABASE_ROLE",
        "REHEARSAL_RPO_SECONDS",
        "REHEARSAL_RTO_SECONDS",
        "POSTGRES_MAJOR",
    )
    if any(not env.get(name) for name in required):
        raise RehearsalBlocked("required_configuration_missing")
    if (
        env.get("GITHUB_REPOSITORY") != "Oionos/Veritras"
        or env.get("GITHUB_REF") != "refs/heads/main"
        or env.get("GITHUB_WORKFLOW_REF") != WORKFLOW
        or not re.fullmatch(r"[0-9a-f]{40}", env.get("GITHUB_SHA", ""))
    ):
        raise RehearsalBlocked("untrusted_workflow_context")
    result = {
        "source_database": env["NEON_DATABASE_NAME"],
        "role": env["NEON_DATABASE_ROLE"],
        "rpo": int(env["REHEARSAL_RPO_SECONDS"]),
        "rto": int(env["REHEARSAL_RTO_SECONDS"]),
        "pg_major": int(env["POSTGRES_MAJOR"]),
        "sha": env["GITHUB_SHA"],
        "batch_size": int(env.get("REHEARSAL_BATCH_SIZE", "1000")),
        "run_id": env.get("GITHUB_RUN_ID", ""),
        "attempt": env.get("GITHUB_RUN_ATTEMPT", ""),
        "environment": env.get("REHEARSAL_ENVIRONMENT"),
        "approved_digest": env.get("APPROVED_RECONCILIATION_DIGEST", ""),
        "target_block": env.get("REHEARSAL_TARGET_BLOCK", ""),
        "target_hash": env.get("REHEARSAL_TARGET_HASH", ""),
    }
    if (
        not 60 <= result["rpo"] <= 3600
        or not 60 <= result["rto"] <= 1200
        or result["pg_major"] not in {16, 17, 18}
        or not 1 <= result["batch_size"] <= 10000
        or result["environment"] not in {"production", "testing"}
        or not result["run_id"].isdigit()
        or int(result["run_id"]) < 1
        or not result["attempt"].isdigit()
        or int(result["attempt"]) < 1
        or any(
            not re.fullmatch(r"[a-zA-Z0-9_]{1,63}", result[name])
            for name in ("source_database", "role")
        )
        or result["approved_digest"]
        and not re.fullmatch(r"[0-9a-f]{64}", result["approved_digest"])
        or bool(result["target_block"]) != bool(result["target_hash"])
    ):
        raise RehearsalBlocked("invalid_rehearsal_configuration")
    if result["target_block"]:
        if not result["target_block"].isdigit() or not re.fullmatch(
            r"0x[0-9a-fA-F]{64}", result["target_hash"]
        ):
            raise RehearsalBlocked("invalid_reviewed_chain_target")
        result["target_block"] = int(result["target_block"])
    key_bytes(env.get("REHEARSAL_BACKUP_KEY"))
    return result


def clone_connection(resources, ledger, database, role):
    resources.verify_live_ownership(ledger)
    payload = resources.client.request(
        "GET",
        f"/projects/{resources.project}/connection_uri",
        query={
            "branch_id": ledger["branch_id"],
            "endpoint_id": ledger["endpoint_id"],
            "database_name": database,
            "role_name": role,
            "pooled": "false",
        },
    )
    url = make_url(payload["uri"])
    if url.username != role:
        raise RehearsalBlocked("private_database_role_mismatch")
    url = url.update_query_dict(
        {"sslmode": "verify-full", "sslrootcert": "/etc/ssl/certs/ca-certificates.crt"}
    )
    expected = {"host": ledger["host"], "port": 5432, "database": database}
    return checked_url(url, expected).render_as_string(hide_password=False), expected


def verify_environment_protection(name, fetch=github):
    settings = fetch(f"/environments/{name}")
    reviewers = [
        rule
        for rule in settings.get("protection_rules", [])
        if rule.get("type") == "required_reviewers" and rule.get("reviewers")
    ]
    branch_policy = settings.get("deployment_branch_policy") or {}
    if settings.get("name") != name or not reviewers:
        raise RehearsalBlocked("environment_review_not_configured")
    if branch_policy.get("protected_branches") is True:
        return
    if branch_policy.get("custom_branch_policies") is not True:
        raise RehearsalBlocked("environment_branch_restriction_missing")
    rules = fetch(f"/environments/{name}/deployment-branch-policies")
    policies = rules.get("branch_policies", [])
    if (
        rules.get("total_count") != 1
        or len(policies) != 1
        or policies[0].get("name") != "main"
        or policies[0].get("type", "branch") != "branch"
    ):
        raise RehearsalBlocked("environment_branch_restriction_missing")


def launch_worker(
    phase, manifest, output, worker_env, *, remaining, target=None, approved=""
):
    command = [
        sys.executable,
        str(Path(__file__).with_name("replay_private_restore.py")),
        "--phase",
        phase,
        "--manifest",
        str(manifest),
        "--output",
        str(output),
        "--timeout",
        str(max(1, min(1200, int(remaining)))),
    ]
    if target:
        command += [
            "--target-block",
            str(target["target_block"]),
            "--target-hash",
            target["target_hash"],
        ]
    if approved:
        command += ["--approved-digest", approved]
    completed = subprocess.run(
        command,
        env=worker_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=max(1, remaining),
        check=False,
    )
    if not output.exists():
        raise RehearsalBlocked("private_worker_report_missing")
    result = json.loads(output.read_text())
    if completed.returncode and result.get("passed") is not False:
        raise RehearsalBlocked("private_worker_failed")
    return result


def execute(
    config,
    resources,
    env,
    directory,
    *,
    verify=configured_verification,
    admission=assess,
    restore=restore_checkpoint,
    phase=launch_worker,
    clock=time.monotonic,
    wall_clock=time.time,
):
    directory = Path(directory)
    private = directory / "private"
    private.mkdir(mode=0o700)
    started, observed_wall = clock(), wall_clock()
    started_wall = config.get("triggered_at", observed_wall)
    elapsed_before = max(0, observed_wall - started_wall)
    deadline = started + config["rto"] - elapsed_before
    report = {
        "report_version": 1,
        "report_type": "hosted_recovery_rehearsal",
        "repository": "Oionos/Veritras",
        "workflow_ref": WORKFLOW,
        "run_id": config["run_id"],
        "run_attempt": config["attempt"],
        "candidate_sha": config["sha"],
        "environment": config["environment"],
        "policy_digest": policy_digest(load_policy()),
        "authorizes_activation": False,
        "overall_result": "blocked",
        "state": "preflight",
        "cleanup": {"state": "not_created"},
    }
    try:
        report["stage"] = "admission"
        if elapsed_before >= config["rto"]:
            raise RehearsalBlocked("recovery_time_objective_exceeded_before_start")
        evidence = admission(config["sha"])
        if evidence.get("commit") != config["sha"]:
            raise RehearsalBlocked("candidate_admission_mismatch")
        report["admission"] = evidence
        report["stage"] = "deployment_identity"
        expected = environment(config["environment"])
        identity = verify(expected)
        report["deployment_identity"] = identity
        if not identity["verified"]:
            raise RehearsalBlocked("deployment_identity_not_verified")
        report["stage"] = "checkpoint"
        ledger = resources.create(
            run_id=config["run_id"],
            attempt=config["attempt"],
            sha=config["sha"],
            checkpoint_age=max(60, int(wall_clock() - started_wall) + 60),
            pg_major=config["pg_major"],
        )
        report["resource"] = {
            key: ledger[key]
            for key in (
                "project",
                "source",
                "branch_id",
                "endpoint_id",
                "checkpoint_time",
                "parent_lsn",
                "expires",
            )
        }
        rpo = max(0, started_wall - epoch(ledger["checkpoint_time"]))
        if rpo > config["rpo"]:
            raise RehearsalBlocked("recovery_point_objective_exceeded")
        report["RPO"] = {
            "seconds": rpo,
            "objective_seconds": config["rpo"],
            "passed": True,
        }
        resources.verify_live_ownership(ledger)
        databases = resources.client.request(
            "GET",
            f"/projects/{resources.project}/branches/{ledger['branch_id']}/databases",
        )["databases"]
        matching = [
            item for item in databases if item.get("name") == config["source_database"]
        ]
        if len(matching) != 1 or matching[0].get("owner_name") != config["role"]:
            raise RehearsalBlocked("checkpoint_database_identity_mismatch")
        # Child branches can inherit parent role passwords. Rotate only the
        # authenticated disposable branch before opening any SQL connections.
        resources.verify_live_ownership(ledger)
        rotated = resources.client.request(
            "POST",
            f"/projects/{resources.project}/branches/{ledger['branch_id']}/roles/{config['role']}/reset_password",
        )
        role = rotated.get("role", {})
        if (
            role.get("branch_id") != ledger["branch_id"]
            or role.get("name") != config["role"]
            or not isinstance(role.get("password"), str)
            or not role["password"]
        ):
            raise RehearsalBlocked("private_credential_rotation_failed")
        resources.client.wait(resources.project, rotated)
        private_password = role["password"]
        source_url, source_target = clone_connection(
            resources, ledger, config["source_database"], config["role"]
        )
        if not hmac.compare_digest(
            (make_url(source_url).password or "").encode(), private_password.encode()
        ):
            raise RehearsalBlocked("private_credential_rotation_failed")
        database = f"veritras_restore_{config['run_id']}_{config['attempt']}"
        response = resources.client.request(
            "POST",
            f"/projects/{resources.project}/branches/{ledger['branch_id']}/databases",
            body={"database": {"name": database, "owner_name": config["role"]}},
        )
        resources.client.wait(resources.project, response)
        target_url, target = clone_connection(
            resources, ledger, database, config["role"]
        )
        if not hmac.compare_digest(
            (make_url(target_url).password or "").encode(), private_password.encode()
        ):
            raise RehearsalBlocked("private_credential_rotation_failed")
        report["clone_credentials_rotated"] = True
        manifest = {
            "version": 1,
            "frozen": True,
            "source": source_target,
            "target": target,
        }
        report["stage"] = "restore"
        comparison = restore(
            manifest,
            source_url,
            target_url,
            private,
            timeout=max(1, min(600, int(deadline - clock()))),
        )
        private_json(private / "restore-comparison.json", comparison)
        report["restore_comparison"] = {
            "matches": comparison["matches"],
            "digest": digest(comparison),
            "difference_summary": summarize_differences(comparison),
        }
        if not comparison["matches"]:
            raise RehearsalBlocked("restore_comparison_failed")
        worker_manifest = {
            "private_rehearsal": True,
            "branch_id": ledger["branch_id"],
            "environment": config["environment"],
            "target": target,
            "candidate_sha": config["sha"],
        }
        manifest_path = private / "worker-target.json"
        private_json(manifest_path, worker_manifest)
        excluded = {
            "NEON_API_KEY",
            "REHEARSAL_OWNERSHIP_KEY",
            "REHEARSAL_BACKUP_KEY",
            "RENDER_API_KEY",
            "GITHUB_TOKEN",
            "GITHUB_RELEASE_TOKEN",
            "GH_TOKEN",
            "SOURCE_DATABASE_URL",
            "TARGET_DATABASE_URL",
        }
        worker_env = {
            key: value
            for key, value in env.items()
            if key not in excluded and not key.startswith("RENDER")
        }
        worker_env.update(
            DATABASE_URL=target_url,
            ENVIRONMENT=config["environment"],
            CHAIN_ID=str(expected["chain_id"]),
            PRODUCT_REGISTRY_CONTRACT=expected["registry"],
            SHIPMENT_TRACKER_CONTRACT=expected["tracker"],
            INDEXER_START_BLOCK=str(expected["start_block"]),
            INDEXER_CONFIRMATIONS=str(expected["confirmations"]),
            INDEXER_ENABLED="false",
            INDEXER_BATCH_SIZE=str(config.get("batch_size", 1000)),
            INDEXER_MAX_LAG_BLOCKS="0",
            INDEXER_POLL_INTERVAL="1",
            INDEXER_HEAD_STALE_AFTER="300",
            JWT_SECRET_KEY=secrets.token_urlsafe(48),
            CORS_ORIGINS="https://private-rehearsal.invalid",
            SIWE_ORIGINS="https://private-rehearsal.invalid",
        )

        def run_phase(name, filename, target=None, approved=""):
            resources.verify_live_ownership(
                ledger
            )  # Recheck before every mutating process.
            remaining = deadline - clock()
            if remaining <= 0:
                raise RehearsalBlocked("recovery_time_objective_exceeded")
            return phase(
                name,
                manifest_path,
                private / filename,
                worker_env,
                remaining=remaining,
                target=target,
                approved=approved,
            )

        requested = (
            {
                "target_block": config["target_block"],
                "target_hash": config["target_hash"],
            }
            if config["target_block"] != ""
            else None
        )
        report["stage"] = "reconciliation"
        reconciliation = run_phase(
            "reconcile",
            "reconciliation-result.json",
            requested,
            config["approved_digest"],
        )
        report["reconciliation"] = reconciliation
        if not reconciliation["passed"]:
            raise RehearsalBlocked("private_reconciliation_not_accepted")
        revision = reconciliation.get("schema_revision")
        if not isinstance(revision, str) or not re.fullmatch(
            r"[a-zA-Z0-9_]{1,64}", revision
        ):
            raise RehearsalBlocked("schema_evidence_missing")
        report["schema_revision"] = revision
        fixed_target = {
            key: reconciliation[key] for key in ("target_block", "target_hash")
        }
        worker_env["INDEXER_ENABLED"] = "true"
        report["stage"] = "restart_checks"
        restarts = [
            run_phase("fixed", f"replay-{index}.json", fixed_target)
            for index in range(3)
        ]
        if (
            any(not item["passed"] for item in restarts)
            or len({item["snapshot_digest"] for item in restarts}) != 1
            or len({item["journal_prefix_digest"] for item in restarts}) != 1
        ):
            raise RehearsalBlocked("restart_conservation_failed")
        report["restart_checks"] = {
            "passed": True,
            "processes": 3,
            "restarts": 2,
            "fixed_target": fixed_target,
            "snapshot_digest": restarts[0]["snapshot_digest"],
        }
        report["stage"] = "live_readiness"
        live = run_phase("live", "live-readiness.json", fixed_target)
        report["live_readiness"] = live
        if (
            not live["passed"]
            or live["journal_prefix_digest"] != restarts[0]["journal_prefix_digest"]
        ):
            raise RehearsalBlocked("live_readiness_or_history_failed")
        elapsed = elapsed_before + clock() - started
        report["RTO"] = {
            "seconds": elapsed,
            "objective_seconds": config["rto"],
            "passed": elapsed <= config["rto"],
            "includes_queue_setup_and_approval": "triggered_at" in config,
        }
        if elapsed > config["rto"]:
            raise RehearsalBlocked("recovery_time_objective_exceeded")
        report["state"] = "rehearsal_completed"
        report["overall_result"] = "pass"
    except (RehearsalBlocked, ResourceError) as error:
        report["state"] = str(error)
    except BaseException:
        report["state"] = "rehearsal_failed_or_interrupted"
    finally:
        try:
            if resources.ledger.exists():
                intent = json.loads(resources.ledger.read_text())
                report["resource_intent"] = {
                    key: intent.get(key)
                    for key in (
                        "project",
                        "source",
                        "name",
                        "branch_id",
                        "created",
                        "expires",
                        "checkpoint_time",
                    )
                }
        except (AttributeError, OSError, ValueError):
            pass
        # Encryption and cleanup are independent: either can fail without
        # suppressing the other. Never mark a failed cleanup as a successful drill.
        try:
            files = [
                (str(path.relative_to(private)), path)
                for path in private.rglob("*")
                if path.is_file()
            ]
            if files:
                encrypt_files(
                    files,
                    directory / "recovery-evidence.enc",
                    env["REHEARSAL_BACKUP_KEY"],
                    {
                        key: report[key]
                        for key in (
                            "repository",
                            "workflow_ref",
                            "run_id",
                            "run_attempt",
                            "candidate_sha",
                            "policy_digest",
                        )
                    },
                )
                report["archive"] = {
                    "state": "encrypted",
                    "format": "AES-256-GCM",
                    "plaintext_uploaded": False,
                }
            else:
                report["archive"] = {"state": "not_created"}
        except BaseException:
            report["archive"] = {
                "state": "encryption_failed",
                "plaintext_uploaded": False,
            }
            report["overall_result"] = "blocked"
        try:
            report["cleanup"] = resources.cleanup()
        except BaseException:
            report["cleanup"] = {
                "state": "cleanup_failed",
                "manual_review_required": True,
            }
            report["overall_result"] = "blocked"
        report["observed_at"] = datetime.now(timezone.utc).isoformat()
        report["expires_at"] = datetime.fromtimestamp(
            started_wall + 86400, timezone.utc
        ).isoformat()
        private_json(directory / "recovery-report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    args = parser.parse_args()
    args.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if any(args.directory.iterdir()):
        raise SystemExit("Fresh private rehearsal directory required")
    try:
        config = configuration(os.environ)
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        dirty = subprocess.run(
            ["git", "diff", "--quiet", "HEAD"], check=False
        ).returncode
        untracked = subprocess.check_output(
            ["git", "ls-files", "--others", "--exclude-standard"], text=True
        ).strip()
        if head != config["sha"] or dirty or untracked:
            raise RehearsalBlocked("checkout_commit_mismatch")
        run = github(f"/actions/runs/{config['run_id']}")
        if (
            run.get("head_sha") != config["sha"]
            or run.get("event") != "workflow_dispatch"
            or run.get("head_branch") != "main"
            or str(run.get("run_attempt")) != config["attempt"]
            or run.get("path") != ".github/workflows/recovery-rehearsal.yml"
            or run.get("head_repository", {}).get("full_name") != "Oionos/Veritras"
        ):
            raise RehearsalBlocked("workflow_origin_mismatch")
        config["triggered_at"] = epoch(run["created_at"])
        verify_environment_protection("recovery-" + config["environment"])
        resources = from_environment(args.directory / "resource-ledger.json")

        def interrupted(*_):
            raise RehearsalBlocked("rehearsal_interrupted")

        signal.signal(signal.SIGTERM, interrupted)
        report = execute(config, resources, os.environ, args.directory)
    except RehearsalBlocked as error:
        report = {
            "overall_result": "blocked",
            "state": str(error),
            "authorizes_activation": False,
        }
        private_json(args.directory / "recovery-report.json", report)
    except Exception:
        report = {
            "overall_result": "blocked",
            "state": "preflight_configuration_failed",
            "authorizes_activation": False,
        }
        private_json(args.directory / "recovery-report.json", report)
    print(json.dumps(console_summary(report)))
    return 0 if report["overall_result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
