import json
import os
import re
import subprocess
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

import rehearse_recovery_restore as restore


def approved():
    return {"version": 1, "frozen": True,
            "source": {"host": "localhost", "port": 5432, "database": "checkpoint"},
            "target": {"host": "localhost", "port": 5432, "database": "veritras_restore_unit_test"}}


def test_child_environment_does_not_redirect_database_or_expose_urls(monkeypatch):
    monkeypatch.setenv("PGSERVICE", "production")
    monkeypatch.setenv("PGOPTIONS", "unsafe")
    monkeypatch.setenv("SOURCE_DATABASE_URL", "private-source")
    monkeypatch.setenv("NEON_API_KEY", "not-needed-by-postgres")
    url = make_url("postgresql://operator:synthetic@localhost/restore")
    env = restore.pg_environment(url, read_only=True)
    assert env["PGDATABASE"] == "restore"
    assert env["PGPASSWORD"] == "synthetic"
    assert env["PGOPTIONS"] == "-c default_transaction_read_only=on"
    assert "PGSERVICE" not in env and "SOURCE_DATABASE_URL" not in env
    assert "NEON_API_KEY" not in env


def test_restore_is_atomic_and_credentials_are_not_cli_arguments(monkeypatch, tmp_path):
    manifest = approved()
    monkeypatch.setattr(restore.shutil, "which", lambda name: name)
    monkeypatch.setattr(restore, "create_engine", lambda *a, **kw: SimpleNamespace(dispose=lambda: None))
    monkeypatch.setattr(restore, "require_empty_target", lambda _: None)
    monkeypatch.setattr(restore, "run_comparison", lambda *args: {"matches": True})
    commands = []

    def run(command, **kwargs):
        commands.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    result = restore.restore_checkpoint(manifest,
        "postgresql://operator:synthetic@localhost/checkpoint",
        "postgresql://operator:synthetic@localhost/veritras_restore_unit_test", tmp_path, run=run)
    assert result["restore_completed"]
    assert len(commands) == 2
    assert commands[0][1]["env"]["PGOPTIONS"].endswith("=on")
    assert "--single-transaction" in commands[1][0]
    assert "--exit-on-error" in commands[1][0]
    assert not any("synthetic" in argument or "--clean" in argument for command, _ in commands for argument in command)
    backup = next(tmp_path.glob("recovery-*/checkpoint.dump"))
    assert backup.stat().st_mode & 0o777 == 0o600
    assert backup.parent.stat().st_mode & 0o777 == 0o700


def test_failed_dump_never_runs_restore_and_sanitizes_client_errors(monkeypatch, tmp_path):
    monkeypatch.setattr(restore.shutil, "which", lambda name: name)
    monkeypatch.setattr(restore, "create_engine", lambda *a, **kw: SimpleNamespace(dispose=lambda: None))
    monkeypatch.setattr(restore, "require_empty_target", lambda _: None)
    commands = []

    def fail(command, **kwargs):
        commands.append(command)
        raise RuntimeError("private-password-and-row")

    with pytest.raises(RuntimeError, match="private artifacts retained") as error:
        restore.restore_checkpoint(approved(), "postgresql://operator@localhost/checkpoint",
            "postgresql://operator@localhost/veritras_restore_unit_test", tmp_path, run=fail)
    assert len(commands) == 1
    assert "private-password" not in str(error.value)


def test_existing_output_stops_cli_before_restore(monkeypatch, tmp_path, capsys):
    output = tmp_path / "report.json"
    output.write_text("retain")
    monkeypatch.setattr("sys.argv", ["restore", "--manifest", "unused.json",
        "--artifact-directory", str(tmp_path), "--output", str(output)])
    monkeypatch.setattr(restore, "restore_checkpoint", lambda *a, **k: pytest.fail("Must not run"))
    assert restore.main() == 2
    assert output.read_text() == "retain"
    assert json.loads(capsys.readouterr().out)["state"] == "report_write_failed"


def test_real_dump_restore_on_disposable_postgres(tmp_path, monkeypatch):
    from app.core.database import Base
    value = os.environ.get("RECOVERY_TEST_DATABASE_URL")
    container = os.environ.get("RECOVERY_CLIENT_CONTAINER")
    have_clients = all(restore.shutil.which(name) for name in ("pg_dump", "pg_restore"))
    if not value or not (container or have_clients):
        pytest.skip("Disposable recovery database and PostgreSQL clients required")
    run = subprocess.run
    if container:
        # CI uses the service's own client version, independent of the runner's
        # preinstalled PostgreSQL version. Only disposable CI transport differs;
        # the real dump, atomic restore and comparison still execute.
        assert re.fullmatch(r"[a-zA-Z0-9_-]+", container)
        monkeypatch.setattr(restore.shutil, "which", lambda name: name)

        def run(command, **kwargs):
            environment = kwargs["env"]
            prefix = ["docker", "--host=unix:///var/run/docker.sock", "exec", "-i",
                      "--env", "PGHOST=127.0.0.1", "--env", "PGPORT=5432"]
            for name in ("PGDATABASE", "PGUSER", "PGPASSWORD", "PGOPTIONS"):
                if name in environment:
                    prefix.extend(["--env", name])
            if command[0] == "pg_dump":
                output_path = next(arg.removeprefix("--file=") for arg in command if arg.startswith("--file="))
                arguments = [arg for arg in command if not arg.startswith("--file=")]
                with open(output_path, "wb") as output:
                    return subprocess.run(prefix + [container] + arguments, env=environment,
                        stdout=output, stderr=subprocess.DEVNULL, timeout=kwargs["timeout"], check=False)
            with open(command[-1], "rb") as backup:
                return subprocess.run(prefix + [container] + command[:-1], env=environment,
                    stdin=backup, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=kwargs["timeout"], check=False)
    source = make_url(value)
    assert source.host in {"localhost", "127.0.0.1"} and source.database == "veritras_cicd_source"
    target = source.set(database="veritras_restore_cicd_regression")
    source_engine, target_engine = create_engine(source), create_engine(target)
    manifest = {"version": 1, "frozen": True}
    for name, url in (("source", source), ("target", target)):
        manifest[name] = {"host": url.host, "port": url.port or 5432, "database": url.database}
    try:
        # Exercise the full application CHECK patterns as well as real rows.
        # pg_dump redistributes varchar[] -> text[] casts in IN predicates.
        Base.metadata.create_all(source_engine)
        with source_engine.begin() as connection:
            connection.execute(text("CREATE TABLE public.restore_sample(id serial PRIMARY KEY, secret_note text NOT NULL, status varchar(32) NOT NULL DEFAULT 'draft', CONSTRAINT ck_restore_status CHECK(status IN ('draft','indexed')))"))
            connection.execute(text("INSERT INTO public.restore_sample(secret_note) VALUES ('do-not-publish')"))
        result = restore.restore_checkpoint(manifest, source.render_as_string(hide_password=False),
            target.render_as_string(hide_password=False), tmp_path, run=run)
        assert result["restore_completed"] and result["matches"]
        assert "do-not-publish" not in json.dumps(result)
        with target_engine.begin() as connection:
            connection.execute(text("ALTER TABLE public.restore_sample DROP CONSTRAINT ck_restore_status"))
            connection.execute(text("ALTER TABLE public.restore_sample ADD CONSTRAINT ck_restore_status CHECK(status IN ('draft','indexed','replaced'))"))
        changed = restore.run_comparison(manifest, source.render_as_string(hide_password=False), target.render_as_string(hide_password=False))
        assert changed["matches"] is False
        assert {"section": "schema", "object": "constraints"} in changed["differences"]
        with pytest.raises(ValueError, match="empty rehearsal"):
            restore.restore_checkpoint(manifest, source.render_as_string(hide_password=False),
                target.render_as_string(hide_password=False), tmp_path, run=run)
    finally:
        for engine in (source_engine, target_engine):
            Base.metadata.drop_all(engine)
            with engine.begin() as connection:
                connection.execute(text("DROP TABLE IF EXISTS public.restore_sample"))
            engine.dispose()
