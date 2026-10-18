import copy
import io
import json
from pathlib import Path

import pytest
import release_gate as gate
from urllib.error import HTTPError

SHA = "a" * 40


@pytest.mark.parametrize("token", [None, "synthetic-read-only-token"])
def test_github_uses_optional_server_only_credential(monkeypatch, token):
    if token is None:
        monkeypatch.delenv("GITHUB_RELEASE_TOKEN", raising=False)
    else:
        monkeypatch.setenv("GITHUB_RELEASE_TOKEN", token)

    def request(req, timeout):
        assert req.full_url.startswith("https://api.github.com/repos/Oionos/Veritras/")
        assert req.get_header("Authorization") == ("Bearer " + token if token else None)
        assert timeout == 10
        return io.BytesIO(b'{"workflow_runs": []}')

    monkeypatch.setattr(gate, "urlopen", request)
    assert gate.github("/actions/runs") == {"workflow_runs": []}


def test_github_http_error_reports_status_without_credentials(monkeypatch):
    monkeypatch.setenv("GITHUB_RELEASE_TOKEN", "synthetic-private-token")

    def unavailable(*args, **kwargs):
        raise HTTPError(
            "https://api.github.com", 403, "synthetic-private-token", {}, None
        )

    monkeypatch.setattr(gate, "urlopen", unavailable)
    with pytest.raises(gate.ReleasePending) as error:
        gate.github("/actions/runs")
    assert str(error.value) == "GitHub unavailable: HTTPError (HTTP 403)"


def fixture_data():
    runs = []
    jobs = {}
    for i, workflow in enumerate(gate.POLICY["workflows"], 1):
        runs.append(
            dict(
                id=i,
                run_attempt=1,
                head_sha=SHA,
                path=workflow["path"],
                event="push",
                head_branch="main",
                head_repository={"full_name": "Oionos/Veritras"},
                status="completed",
                conclusion="success",
            )
        )
        jobs[i] = {
            "total_count": len(workflow["jobs"]),
            "jobs": [
                dict(name=n, status="completed", conclusion="success", head_sha=SHA)
                for n in workflow["jobs"]
            ],
        }

    def fetch(path):
        if path.startswith("/actions/runs?"):
            return {"workflow_runs": runs}
        return jobs[int(path.split("/")[3])]

    return runs, jobs, fetch


def test_release_policy_copies_and_branch_check_payload_agree():
    root = Path(__file__).resolve().parents[2]
    assert gate.POLICY == json.loads(
        (root / "frontend/release_policy.json").read_text()
    )
    protection = json.loads((root / "release/protect-main.json").read_text())
    names = [n for w in gate.POLICY["workflows"] for n in w["jobs"]]
    assert protection["required_status_checks"] == {
        "strict": True,
        "checks": [{"context": n, "app_id": 15368} for n in names],
    }
    assert protection["enforce_admins"] is True
    assert (
        protection["allow_force_pushes"] is False
        and protection["allow_deletions"] is False
    )
    for w in gate.POLICY["workflows"]:
        workflow = (root / w["path"]).read_text()
        for name in w["jobs"]:
            assert "name: " + name in workflow
    assert ".github/workflows/hosted-health.yml" not in [
        w["path"] for w in gate.POLICY["workflows"]
    ]


def test_exact_successful_main_commit_is_admitted():
    runs, jobs, fetch = fixture_data()
    result = gate.assess(SHA, fetch)
    assert result["commit"] == SHA
    assert len(result["workflows"]) == 2


def test_readiness_observes_ci_without_becoming_a_release_prerequisite():
    root = Path(__file__).resolve().parents[2]
    health = (root / ".github/workflows/hosted-health.yml").read_text()
    assert "workflow_run:" in health and "workflows: [CI]" in health
    assert "github.event.workflow_run.event == 'push'" in health
    assert (
        "github.event.workflow_run.head_repository.full_name == github.repository"
        in health
    )
    assert "git log -1 --format=%H HEAD -- backend" in health
    entrypoint = (root / "backend/start_api.py").read_text()
    assert entrypoint.index("admit_production(os.environ)") < entrypoint.index(
        "require_current_schema()"
    )
    build = (root / "frontend/build-vercel.mjs").read_text()
    assert build.index("await waitForRelease(") < build.index("spawnSync('npm'")
    assert build.index("await waitForApi(") < build.index("spawnSync('npm'")


@pytest.mark.parametrize(
    "field,value",
    [
        ("head_sha", "b" * 40),
        ("event", "pull_request"),
        ("head_branch", "testing"),
        ("path", "evil.yml"),
        ("head_repository", {"full_name": "attacker/Veritras"}),
    ],
)
def test_untrusted_workflows_do_not_qualify(field, value):
    runs, jobs, fetch = fixture_data()
    runs[0][field] = value
    with pytest.raises(gate.ReleasePending):
        gate.assess(SHA, fetch)


@pytest.mark.parametrize(
    "conclusion", ["failure", "cancelled", "neutral", "skipped", "timed_out", None]
)
def test_non_successful_workflow_is_rejected(conclusion):
    runs, jobs, fetch = fixture_data()
    runs[0]["conclusion"] = conclusion
    with pytest.raises(gate.ReleaseRejected):
        gate.assess(SHA, fetch)


@pytest.mark.parametrize(
    "mode",
    ["missing", "duplicate", "wrong_sha", "skipped", "failed", "pending", "truncated"],
)
def test_every_required_job_must_really_succeed(mode):
    runs, jobs, fetch = fixture_data()
    job = jobs[1]["jobs"][0]
    if mode == "missing":
        jobs[1]["jobs"].pop(0)
    elif mode == "duplicate":
        jobs[1]["jobs"].append(copy.copy(job))
    elif mode == "wrong_sha":
        job["head_sha"] = "b" * 40
    elif mode == "skipped":
        job["conclusion"] = "skipped"
    elif mode == "failed":
        job["conclusion"] = "failure"
    elif mode == "pending":
        job["status"] = "queued"
    else:
        jobs[1]["total_count"] = 101
    with pytest.raises(gate.ReleaseRejected):
        gate.assess(SHA, fetch)


def test_latest_attempt_cannot_be_hidden_by_old_success():
    runs, jobs, fetch = fixture_data()
    latest = dict(runs[0], id=3, run_attempt=2, conclusion="failure")
    runs.append(latest)
    with pytest.raises(gate.ReleaseRejected):
        gate.assess(SHA, fetch)


def test_bounded_pending_and_api_failures_never_admit():
    now = [0]

    def pause(seconds):
        now[0] += seconds

    def unavailable(_):
        raise gate.ReleasePending("Unavailable")

    with pytest.raises(gate.ReleaseRejected, match="deadline"):
        gate.wait_for_release(
            SHA,
            deadline=3,
            interval=1,
            fetch=unavailable,
            clock=lambda: now[0],
            pause=pause,
        )
    assert now[0] == 3


def test_pending_can_become_a_real_success():
    runs, jobs, fetch = fixture_data()
    runs[0]["status"] = "in_progress"

    def pause(_):
        runs[0]["status"] = "completed"

    assert gate.wait_for_release(SHA, fetch=fetch, pause=pause)["commit"] == SHA


def test_production_entrypoint_requires_commit_and_main():
    gate.admit_production({"ENVIRONMENT": "testing"})
    with pytest.raises(gate.ReleaseRejected):
        gate.admit_production({"ENVIRONMENT": "production"})
    with pytest.raises(gate.ReleaseRejected):
        gate.admit_production(
            {"ENVIRONMENT": "production", "RENDER_GIT_BRANCH": "testing"}
        )
