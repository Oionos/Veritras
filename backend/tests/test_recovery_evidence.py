import tarfile

import pytest

from recovery_evidence import decrypt_archive, encrypt_files
from pg_client import command

KEY = "ab" * 32


def test_streaming_archive_round_trip_is_private_authenticated_and_not_plaintext(
    tmp_path,
):
    source, encrypted, output = [
        tmp_path / name for name in ("checkpoint.dump", "evidence.enc", "output.tar")
    ]
    source.write_bytes(b"private-production-data" * 100000)
    encrypt_files(
        [("backup/checkpoint.dump", source)],
        encrypted,
        KEY,
        {"run_id": "123", "sha": "a" * 40},
    )
    assert encrypted.stat().st_mode & 0o777 == 0o600
    assert b"private-production-data" not in encrypted.read_bytes()
    assert decrypt_archive(encrypted, output, KEY)["run_id"] == "123"
    assert output.stat().st_mode & 0o777 == 0o600
    with tarfile.open(output) as archive:
        assert archive.getnames() == ["backup/checkpoint.dump"]
        assert (
            archive.extractfile("backup/checkpoint.dump").read() == source.read_bytes()
        )
    with pytest.raises(ValueError):
        decrypt_archive(encrypted, output, KEY)


@pytest.mark.parametrize("fault", ["key", "body", "header", "tag", "truncated"])
def test_bad_archive_never_publishes_plaintext(tmp_path, fault):
    source, encrypted, output = [
        tmp_path / name for name in ("data", "evidence.enc", "output.tar")
    ]
    source.write_bytes(b"do-not-publish")
    encrypt_files([("data", source)], encrypted, KEY, {"run_id": "123"})
    data = bytearray(encrypted.read_bytes())
    if fault in {"body", "header", "tag"}:
        index = {"body": len(data) // 2, "header": 15, "tag": len(data) - 1}[fault]
        data[index] ^= 1
        encrypted.write_bytes(data)
    if fault == "truncated":
        encrypted.write_bytes(data[:10])
    with pytest.raises(Exception):
        decrypt_archive(encrypted, output, "cd" * 32 if fault == "key" else KEY)
    assert not output.exists()
    assert not list(tmp_path.glob(".recovery-decrypt-*"))


def test_archive_rejects_unsafe_names_and_invalid_keys(tmp_path):
    source = tmp_path / "source"
    source.write_text("secret")
    for name in ("../outside", "/absolute"):
        with pytest.raises(ValueError):
            encrypt_files([(name, source)], tmp_path / "invalid.enc", KEY, {})
        assert not (tmp_path / "invalid.enc").exists()
    with pytest.raises(ValueError):
        encrypt_files([("source", source)], tmp_path / "invalid.enc", "weak", {})


def test_matching_pg_client_uses_scoped_mounts_and_secret_names_only(tmp_path):
    tmp_path.chmod(0o700)
    env = {
        "PG_CLIENT_IMAGE": "postgres:17-bookworm",
        "PGPASSWORD": "private-password",
        "PGHOST": "ep-private.region.neon.tech",
        "PGSSLROOTCERT": "/etc/ssl/certs/ca-certificates.crt",
    }
    result = command(
        "pg_dump", ["--format=custom", f"--file={tmp_path}/checkpoint.dump"], env
    )
    assert "private-password" not in " ".join(result)
    assert "--network" not in result
    assert "PGPASSWORD" in result
    assert result[-3] == "pg_dump"
    result = command(
        "pg_restore", ["--single-transaction", str(tmp_path / "checkpoint.dump")], env
    )
    assert any(
        str(tmp_path) in value and value.endswith(",readonly") for value in result
    )
    with pytest.raises(ValueError):
        command(
            "pg_dump",
            [f"--file={tmp_path}/checkpoint.dump"],
            {**env, "PG_CLIENT_IMAGE": "untrusted/image"},
        )
