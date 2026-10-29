import importlib.util
import io
import json
from pathlib import Path
import tarfile
from types import SimpleNamespace
import zipfile

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "inspect_recovery_evidence.py"
spec = importlib.util.spec_from_file_location("inspect_evidence", SCRIPT)
inspection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inspection)
KEY = "ab" * 32
SHA = "a" * 40
RUN_ID = "40649974176"


def source_run():
    return {"id": int(RUN_ID), "run_attempt": 2, "status": "completed", "event": "workflow_dispatch",
            "head_branch": "main", "path": inspection.SOURCE_WORKFLOW,
            "head_repository": {"full_name": inspection.REPOSITORY}, "head_sha": SHA}


@pytest.fixture
def evidence(tmp_path):
    expected = {"repository": inspection.REPOSITORY,
                "workflow_ref": inspection.REPOSITORY + "/" + inspection.SOURCE_WORKFLOW + "@refs/heads/main",
                "run_id": RUN_ID, "run_attempt": "1", "candidate_sha": SHA,
                "policy_digest": "b" * 64}
    comparison = {"matches": False, "source": {"private-row": "private-password"},
                  "differences": [{"section": "schema", "object": "columns"},
                                  {"section": "tables", "object": "private-table"}]}
    report = {**expected, "report_type": "hosted_recovery_rehearsal",
              "environment": "testing", "authorizes_activation": False,
              "restore_comparison": {"matches": False, "digest": inspection.digest(comparison)}}
    original = tmp_path / "restore-comparison.json"
    original.write_text(json.dumps(comparison))
    encrypted = tmp_path / "original.enc"
    from recovery_evidence import encrypt_files
    encrypt_files([("restore-comparison.json", original)], encrypted, KEY, expected)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    return report, encrypted, private, expected, comparison


def test_saved_comparison_is_authenticated_and_only_safe_categories_are_published(evidence):
    report, encrypted, private, expected, _ = evidence
    result = inspection.inspect_files(report, encrypted, private, KEY, expected)
    assert result["state"] == "inspected" and result["authorizes_activation"] is False
    assert result["original_comparison_matches"] is False
    assert result["restore_difference_summary"]["schema_categories"] == ["columns"]
    assert result["restore_difference_summary"]["sections"] == {"schema": 1, "tables": 1}
    assert "private" not in json.dumps(result)
    assert not (private / "authenticated.tar").exists()
    assert encrypted.exists()


@pytest.mark.parametrize("fault,state", [
    ("key", "archive_authentication_failed"),
    ("provenance", "archive_provenance_mismatch"),
    ("digest", "comparison_digest_mismatch"),
    ("environment", "source_report_identity_mismatch"),
    ("missing_comparison", "source_has_no_restore_comparison"),
])
def test_invalid_evidence_blocks_without_retaining_plaintext(evidence, fault, state):
    report, encrypted, private, expected, _ = evidence
    key = KEY
    if fault == "key":
        key = "cd" * 32
    if fault == "provenance":
        expected = {**expected, "policy_digest": "c" * 64}
        report = {**report, **expected}
    if fault == "digest":
        report["restore_comparison"]["digest"] = "0" * 64
    if fault == "environment":
        report["environment"] = "production"
    if fault == "missing_comparison":
        report.pop("restore_comparison")
    with pytest.raises(inspection.EvidenceBlocked, match=state):
        inspection.inspect_files(report, encrypted, private, key, expected)
    assert not (private / "authenticated.tar").exists()


@pytest.mark.parametrize("fault", ["symlink", "duplicate", "oversized", "missing"])
def test_tar_members_are_read_without_extracting_paths(evidence, monkeypatch, fault):
    report, encrypted, private, expected, comparison = evidence
    def decrypt(source, destination, key):
        with tarfile.open(destination, "w") as archive:
            count = 2 if fault == "duplicate" else 1
            for _ in range(count):
                info = tarfile.TarInfo("../outside" if fault == "missing" else "restore-comparison.json")
                data = json.dumps(comparison).encode()
                if fault == "symlink":
                    info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"
                    archive.addfile(info)
                else:
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))
        return expected
    monkeypatch.setattr(inspection, "decrypt_archive", decrypt)
    if fault == "oversized":
        monkeypatch.setattr(inspection, "MAX_REPORT", 8)
    with pytest.raises(inspection.EvidenceBlocked):
        inspection.inspect_files(report, encrypted, private, KEY, expected)
    assert not (private / "authenticated.tar").exists()
    assert not (private.parent / "outside").exists()


@pytest.mark.parametrize("change", [
    {"head_branch": "feature"}, {"event": "pull_request"},
    {"path": ".github/workflows/untrusted.yml"},
    {"head_repository": {"full_name": "fork/Veritras"}},
    {"head_sha": "not-a-sha"}, {"run_attempt": 0}, {"id": 1},
    {"status": "in_progress"},
])
def test_source_run_requires_the_original_main_recovery_workflow(change):
    with pytest.raises(inspection.EvidenceBlocked, match="untrusted_source_run"):
        inspection.source_identity(RUN_ID, "1", {**source_run(), **change})
    assert inspection.source_identity(RUN_ID, "1", source_run()) == SHA


def test_complete_source_inspection_downloads_only_bound_artifacts(evidence, monkeypatch):
    report, encrypted, private, expected, _ = evidence
    artifacts = [{"id": index, "name": f"recovery-{kind}-testing-{RUN_ID}-1",
                  "expired": False, "size_in_bytes": 1024,
                  "workflow_run": {"id": int(RUN_ID), "head_sha": SHA}}
                 for index, kind in enumerate(("report", "encrypted"), 1)]
    def fetch(path):
        return source_run() if path.endswith(RUN_ID) else {"total_count": 2, "artifacts": artifacts}
    def download(identity, destination):
        with zipfile.ZipFile(destination, "w") as archive:
            if identity == 1:
                archive.writestr("recovery-report.json", json.dumps(report))
            else:
                archive.write(encrypted, "recovery-evidence.enc")
    monkeypatch.setattr(inspection, "trusted_policy", lambda _: expected["policy_digest"])
    monkeypatch.setenv("REHEARSAL_BACKUP_KEY", KEY)
    result = inspection.inspect_source(RUN_ID, "1", private, fetch=fetch, download=download)
    assert result["state"] == "inspected" and "private" not in json.dumps(result)


def test_invalid_run_id_stops_before_api_calls(tmp_path):
    with pytest.raises(inspection.EvidenceBlocked, match="invalid_source_run"):
        inspection.inspect_source("../other", "1", tmp_path, fetch=lambda _: pytest.fail("API must not run"))


def test_archive_key_is_not_given_to_download_process(tmp_path, monkeypatch):
    monkeypatch.setenv("REHEARSAL_BACKUP_KEY", KEY)
    monkeypatch.setenv("GITHUB_RELEASE_TOKEN", "synthetic-github-token")
    def run(command, **kwargs):
        assert "REHEARSAL_BACKUP_KEY" not in kwargs["env"]
        assert kwargs["env"]["GH_TOKEN"] == "synthetic-github-token"
        assert KEY not in " ".join(command) and "synthetic-github-token" not in " ".join(command)
        kwargs["stdout"].write(b"synthetic-zip")
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(inspection.subprocess, "run", run)
    destination = tmp_path / "download.zip"
    inspection.download_zip(123, destination)
    assert destination.stat().st_mode & 0o777 == 0o600


def test_zip_paths_and_extra_members_are_rejected(tmp_path):
    source = tmp_path / "bad.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("../recovery-report.json", "private-value")
    with pytest.raises(inspection.EvidenceBlocked, match="unexpected_artifact_contents"):
        inspection.unpack_file(source, "recovery-report.json", tmp_path / "output", 1024)
    assert not (tmp_path / "output").exists()


def test_untrusted_cli_context_blocks_before_any_evidence_access(tmp_path, monkeypatch, capsys):
    output = tmp_path / "summary.json"
    monkeypatch.setattr(inspection.sys, "argv", ["inspect", "--output", str(output)])
    monkeypatch.setenv("GITHUB_REF", "refs/heads/feature")
    monkeypatch.setattr(inspection, "inspect_source", lambda *a, **kw: pytest.fail("Must not inspect"))
    assert inspection.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["state"] == "untrusted_diagnostic_workflow"
    assert result["authorizes_activation"] is False
    assert output.stat().st_mode & 0o777 == 0o600


def test_cli_never_overwrites_a_previous_report(tmp_path, monkeypatch, capsys):
    output = tmp_path / "summary.json"
    output.write_text("retain")
    monkeypatch.setattr(inspection.sys, "argv", ["inspect", "--output", str(output)])
    monkeypatch.setenv("GITHUB_REF", "refs/heads/feature")
    assert inspection.main() == 2
    assert output.read_text() == "retain"
    assert json.loads(capsys.readouterr().out)["state"] == "report_write_failed"
