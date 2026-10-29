"""Inspect authenticated saved testing evidence; no RPC or database operations."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from compare_recovery import digest, summarize_differences
from environment_policy import policy_digest
from recovery_evidence import decrypt_archive
from rehearse_hosted_recovery import verify_environment_protection
from release_gate import github

REPOSITORY = "Oionos/Veritras"
SOURCE_WORKFLOW = ".github/workflows/recovery-rehearsal.yml"
WORKFLOW = REPOSITORY + "/.github/workflows/recovery-evidence-diagnostics.yml@refs/heads/main"
MAX_ARCHIVE = 512 * 1024 * 1024
MAX_REPORT = 4 * 1024 * 1024


class EvidenceBlocked(Exception):
    pass


def source_identity(run_id, attempt, run):
    if (
        not re.fullmatch(r"[1-9][0-9]{0,19}", run_id)
        or not re.fullmatch(r"[1-9][0-9]{0,5}", attempt)
        or run.get("id") != int(run_id)
        or type(run.get("run_attempt")) is not int
        or run["run_attempt"] < int(attempt)
        or run.get("status") != "completed"
        or run.get("event") != "workflow_dispatch"
        or run.get("head_branch") != "main"
        or run.get("path") != SOURCE_WORKFLOW
        or run.get("head_repository", {}).get("full_name") != REPOSITORY
        or not re.fullmatch(r"[0-9a-f]{40}", run.get("head_sha", ""))
    ):
        raise EvidenceBlocked("untrusted_source_run")
    return run["head_sha"]


def trusted_policy(sha):
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", sha, "HEAD"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
    ).returncode:
        raise EvidenceBlocked("source_commit_not_in_main_history")
    encoded = subprocess.check_output(
        ["git", "show", sha + ":release/environment-policy.json"],
        stderr=subprocess.DEVNULL, timeout=10,
    )
    return policy_digest(json.loads(encoded))


def download_zip(artifact_id, destination):
    # gh follows GitHub's authenticated artifact redirect. Only its GitHub token
    # enters the child environment; the archive key stays in this process.
    env = {name: value for name, value in os.environ.items()
           if name != "REHEARSAL_BACKUP_KEY"}
    env["GH_TOKEN"] = os.environ["GITHUB_RELEASE_TOKEN"]
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as output:
        result = subprocess.run(
            ["gh", "api", f"repos/{REPOSITORY}/actions/artifacts/{artifact_id}/zip"],
            env=env, stdout=output, stderr=subprocess.DEVNULL, timeout=120,
        )
    if result.returncode or destination.stat().st_size > MAX_ARCHIVE:
        raise EvidenceBlocked("artifact_download_failed")


def unpack_file(archive, name, destination, limit):
    with zipfile.ZipFile(archive) as zipped:
        entries = zipped.infolist()
        if (len(entries) != 1 or entries[0].filename != name
                or entries[0].is_dir() or entries[0].file_size > limit):
            raise EvidenceBlocked("unexpected_artifact_contents")
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as output, zipped.open(entries[0]) as source:
            shutil.copyfileobj(source, output, length=1024 * 1024)


def inspect_files(report, encrypted, directory, key, expected):
    if (
        report.get("report_type") != "hosted_recovery_rehearsal"
        or report.get("environment") != "testing"
        or report.get("authorizes_activation") is not False
        or any(report.get(name) != value for name, value in expected.items())
    ):
        raise EvidenceBlocked("source_report_identity_mismatch")
    declared = report.get("restore_comparison", {})
    if type(declared.get("matches")) is not bool:
        raise EvidenceBlocked("source_has_no_restore_comparison")
    plaintext = directory / "authenticated.tar"
    try:
        try:
            metadata = decrypt_archive(encrypted, plaintext, key)
        except Exception:
            raise EvidenceBlocked("archive_authentication_failed") from None
        if metadata != expected:
            raise EvidenceBlocked("archive_provenance_mismatch")
        comparison, found = None, False
        with tarfile.open(plaintext, mode="r|") as archive:
            for index, member in enumerate(archive):
                if index >= 10000:
                    raise EvidenceBlocked("archive_inventory_exceeded")
                if member.name != "restore-comparison.json":
                    continue
                if found or not member.isfile() or member.size > MAX_REPORT:
                    raise EvidenceBlocked("invalid_comparison_member")
                found = True
                with archive.extractfile(member) as source:
                    comparison = json.load(source)
        if not found or not isinstance(comparison, dict):
            raise EvidenceBlocked("comparison_member_missing")
        if (digest(comparison) != declared.get("digest")
                or type(comparison.get("matches")) is not bool
                or comparison["matches"] != declared["matches"]):
            raise EvidenceBlocked("comparison_digest_mismatch")
        return {
            "report_type": "recovery_evidence_diagnostics",
            "state": "inspected",
            "source_run_id": expected["run_id"],
            "source_attempt": expected["run_attempt"],
            "candidate_sha": expected["candidate_sha"],
            "original_comparison_matches": comparison["matches"],
            "restore_difference_summary": summarize_differences(comparison),
            "authorizes_activation": False,
        }
    finally:
        plaintext.unlink(missing_ok=True)


def inspect_source(run_id, attempt, directory, *, fetch=github, download=download_zip):
    # Validate inputs before constructing any API path.
    if not re.fullmatch(r"[1-9][0-9]{0,19}", run_id) or not re.fullmatch(r"[1-9][0-9]{0,5}", attempt):
        raise EvidenceBlocked("invalid_source_run")
    run = fetch(f"/actions/runs/{run_id}")
    sha = source_identity(run_id, attempt, run)
    expected = {
        "repository": REPOSITORY,
        "workflow_ref": REPOSITORY + "/" + SOURCE_WORKFLOW + "@refs/heads/main",
        "run_id": run_id, "run_attempt": attempt, "candidate_sha": sha,
        "policy_digest": trusted_policy(sha),
    }
    inventory = fetch(f"/actions/runs/{run_id}/artifacts?per_page=100")
    artifacts = inventory.get("artifacts", [])
    if inventory.get("total_count") != len(artifacts):
        raise EvidenceBlocked("artifact_inventory_incomplete")
    paths = {}
    for kind, member, limit in (
        ("report", "recovery-report.json", MAX_REPORT),
        ("encrypted", "recovery-evidence.enc", MAX_ARCHIVE),
    ):
        name = f"recovery-{kind}-testing-{run_id}-{attempt}"
        matches = [item for item in artifacts if item.get("name") == name]
        if (len(matches) != 1 or matches[0].get("expired") is not False
                or type(matches[0].get("id")) is not int
                or matches[0]["id"] < 1
                or type(matches[0].get("size_in_bytes")) is not int
                or not 0 < matches[0]["size_in_bytes"] <= MAX_ARCHIVE
                or matches[0].get("workflow_run", {}).get("id") != int(run_id)
                or matches[0].get("workflow_run", {}).get("head_sha") != sha):
            raise EvidenceBlocked("source_artifact_unavailable")
        zipped = directory / (kind + ".zip")
        download(matches[0]["id"], zipped)
        paths[kind] = directory / member
        unpack_file(zipped, member, paths[kind], limit)
    report = json.loads(paths["report"].read_text())
    return inspect_files(report, paths["encrypted"], directory,
                         os.environ.get("REHEARSAL_BACKUP_KEY"), expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if (os.environ.get("GITHUB_REPOSITORY") != REPOSITORY
                or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
                or os.environ.get("GITHUB_REF") != "refs/heads/main"
                or os.environ.get("GITHUB_WORKFLOW_REF") != WORKFLOW
                or subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
                != os.environ.get("GITHUB_SHA")):
            raise EvidenceBlocked("untrusted_diagnostic_workflow")
        verify_environment_protection("recovery-testing")
        with tempfile.TemporaryDirectory(prefix="recovery-inspection-", dir=os.environ["RUNNER_TEMP"]) as private:
            result = inspect_source(os.environ.get("SOURCE_RUN_ID", ""),
                                    os.environ.get("SOURCE_ATTEMPT", ""), Path(private))
    except EvidenceBlocked as error:
        result = {"report_type": "recovery_evidence_diagnostics", "state": str(error),
                  "authorizes_activation": False}
    except Exception:
        result = {"report_type": "recovery_evidence_diagnostics", "state": "inspection_unavailable",
                  "authorizes_activation": False}
    try:
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError:
        print(json.dumps({"state": "report_write_failed", "authorizes_activation": False}))
        return 2
    with os.fdopen(fd, "w") as output:
        json.dump(result, output, sort_keys=True, indent=2)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["state"] == "inspected" else 1


if __name__ == "__main__":
    raise SystemExit(main())
