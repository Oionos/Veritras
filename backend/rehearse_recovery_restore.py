"""Restore a private checkpoint into an explicitly allowed, empty rehearsal DB.

Does not create databases or provider resources. Never cleans/overwrites a target.
The caller must establish provider ownership and freeze the checkpoint first.
"""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from compare_recovery import run_comparison, validate_targets


def pg_environment(url, *, read_only):
    # Inherited PGSERVICE/PGOPTIONS must not redirect the selected target or
    # execute unexpected session configuration. Preserve network/CA settings.
    unrelated_secrets = {
        "SOURCE_DATABASE_URL",
        "TARGET_DATABASE_URL",
        "DATABASE_URL",
        "SEPOLIA_RPC_URL",
        "NEON_API_KEY",
        "RENDER_API_KEY",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "GITHUB_RELEASE_TOKEN",
        "JWT_SECRET_KEY",
    }
    unrelated_secrets.update({"REHEARSAL_BACKUP_KEY", "REHEARSAL_OWNERSHIP_KEY"})
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("PG") and key not in unrelated_secrets
    }
    env.update(
        PGHOST=url.host,
        PGPORT=str(url.port or 5432),
        PGDATABASE=url.database,
        PGUSER=url.username,
        PGPASSWORD=url.password or "",
        PGCONNECT_TIMEOUT="10",
    )
    if "PG_CLIENT_IMAGE" in os.environ:
        env["PG_CLIENT_IMAGE"] = os.environ["PG_CLIENT_IMAGE"]
    for query, variable in (
        ("sslmode", "PGSSLMODE"),
        ("sslrootcert", "PGSSLROOTCERT"),
        ("channel_binding", "PGCHANNELBINDING"),
    ):
        if query in url.query:
            env[variable] = url.query[query]
    if read_only:
        env["PGOPTIONS"] = "-c default_transaction_read_only=on"
    return env


def require_empty_target(engine):
    with engine.connect() as connection:
        with connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text("SET LOCAL statement_timeout='10s'"))
            if (
                connection.execute(text("SELECT current_database()")).scalar_one()
                != engine.url.database
            ):
                raise ValueError("Unexpected recovery target database")
            count = connection.execute(
                text(
                    """SELECT count(*) FROM pg_class c
                JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname NOT LIKE 'pg\\_%' ESCAPE '\\'
                AND n.nspname <> 'information_schema'"""
                )
            ).scalar_one()
            routines = connection.execute(
                text(
                    """SELECT count(*) FROM pg_proc p
                JOIN pg_namespace n ON n.oid=p.pronamespace
                WHERE n.nspname NOT LIKE 'pg\\_%' ESCAPE '\\'
                AND n.nspname <> 'information_schema'"""
                )
            ).scalar_one()
            extensions = connection.execute(
                text("SELECT count(*) FROM pg_extension WHERE extname<>'plpgsql'")
            ).scalar_one()
            if count or routines or extensions:
                raise ValueError("Restore requires an empty rehearsal database")


def restore_checkpoint(
    manifest,
    source_url,
    target_url,
    artifact_parent,
    *,
    timeout=600,
    run=subprocess.run,
):
    source, target = validate_targets(manifest, source_url, target_url)
    if (
        not re.fullmatch(r"veritras_restore_[a-z0-9_]{8,64}", target.database)
        or type(timeout) is not int
        or not 1 <= timeout <= 3600
    ):
        raise ValueError("Invalid disposable restore target or timeout")
    binaries = [shutil.which(name) for name in ("pg_dump", "pg_restore")]
    if not all(binaries):
        raise ValueError("Compatible PostgreSQL client binaries required")
    engine = create_engine(target, poolclass=NullPool, hide_parameters=True)
    try:
        require_empty_target(engine)
    finally:
        engine.dispose()
    # New private directory per attempt. Failed dumps are retained for inspection;
    # no retry reuses a partially restored target and no artifact is uploaded here.
    directory = Path(tempfile.mkdtemp(prefix="recovery-", dir=artifact_parent))
    backup = directory / "checkpoint.dump"
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    commands = [
        (
            [
                binaries[0],
                "--format=custom",
                "--no-owner",
                "--no-acl",
                f"--file={backup}",
            ],
            source,
            True,
        ),
        (
            [
                binaries[1],
                "--dbname=" + target.database,
                "--no-owner",
                "--no-acl",
                "--exit-on-error",
                "--single-transaction",
                str(backup),
            ],
            target,
            False,
        ),
    ]
    for command, url, read_only in commands:
        # Provider/client messages may contain credentialed URLs or private row
        # contents. Never print stdout/stderr or include them in raised errors.
        try:
            completed = run(
                command,
                env=pg_environment(url, read_only=read_only),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError("Recovery client failed")
        except Exception:
            raise RuntimeError(
                "Recovery client failed; private artifacts retained"
            ) from None
    report = run_comparison(manifest, source_url, target_url)
    report["restore_completed"] = True
    report["backup_retained_privately"] = True
    report["application_role_validation"] = "separate_check_required"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--artifact-directory", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    try:
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError:
        print(json.dumps({"matches": False, "state": "report_write_failed"}))
        return 2
    try:
        report = restore_checkpoint(
            json.loads(args.manifest.read_text()),
            os.environ["SOURCE_DATABASE_URL"],
            os.environ["TARGET_DATABASE_URL"],
            args.artifact_directory,
            timeout=args.timeout,
        )
    except Exception:
        report = {
            "matches": False,
            "state": "restore_failed",
            "authorizes_activation": False,
        }
    with os.fdopen(fd, "w") as output:
        json.dump(report, output, sort_keys=True, indent=2)
        output.write("\n")
    print(
        json.dumps(
            {"matches": report["matches"], "state": report.get("state", "compared")}
        )
    )
    return 0 if report["matches"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
