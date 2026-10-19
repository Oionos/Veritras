"""Fail-closed production admission against the exact main-push CI runs.

Uses only GitHub's public API. No provider token or application secret is needed.
The policy is mirrored in frontend because hosts build separate repository roots.
"""

import json
import os
import hashlib
import re
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

POLICY = json.loads(Path(__file__).with_name("release_policy.json").read_text())
ATTESTATION = Path(__file__).with_name(".release-admission.json")
TOKEN_FILE = Path("/etc/secrets/github-release-token")


class ReleaseRejected(RuntimeError):
    pass


class ReleasePending(RuntimeError):
    pass


def github(path):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Veritras-release-gate",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token := os.environ.get("GITHUB_RELEASE_TOKEN"):
        headers["Authorization"] = "Bearer " + token
    request = Request(
        "https://api.github.com/repos/" + POLICY["repository"] + path,
        headers=headers,
    )
    try:
        with urlopen(request, timeout=10) as response:
            return json.load(response)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
        # Provider errors may contain URLs/headers. Never print response bodies.
        code = f" (HTTP {error.code})" if isinstance(error, HTTPError) else ""
        raise ReleasePending(
            "GitHub unavailable: " + type(error).__name__ + code
        ) from None


def assess(commit, fetch=github):
    if not re.fullmatch(r"[0-9a-f]{40}", commit or ""):
        raise ReleaseRejected("A full production Git commit is required")
    data = fetch(
        "/actions/runs?"
        + urlencode(
            {
                "head_sha": commit,
                "event": "push",
                "branch": POLICY["branch"],
                "per_page": 100,
            }
        )
    )
    if not isinstance(data, dict) or not isinstance(data.get("workflow_runs"), list):
        raise ReleaseRejected("Invalid GitHub workflow response")
    evidence = []
    for workflow in POLICY["workflows"]:
        candidates = [
            r
            for r in data["workflow_runs"]
            if r.get("head_sha") == commit
            and r.get("path") == workflow["path"]
            and r.get("event") == "push"
            and r.get("head_branch") == POLICY["branch"]
            and r.get("head_repository", {}).get("full_name", "").lower()
            == POLICY["repository"].lower()
        ]
        if not candidates:
            raise ReleasePending(
                "Required main-push workflow is missing: " + workflow["path"]
            )
        run = max(candidates, key=lambda r: (r.get("id", 0), r.get("run_attempt", 0)))
        if (
            not isinstance(run.get("id"), int)
            or not isinstance(run.get("run_attempt"), int)
            or run["run_attempt"] < 1
        ):
            raise ReleaseRejected("Invalid workflow identity")
        if run.get("status") != "completed":
            raise ReleasePending("Waiting for " + workflow["path"])
        if run.get("conclusion") != "success":
            raise ReleaseRejected("Required workflow failed: " + workflow["path"])
        jobs = fetch(
            f"/actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page=100"
        )
        if (
            not isinstance(jobs, dict)
            or not isinstance(jobs.get("jobs"), list)
            or jobs.get("total_count", 0) > 100
        ):
            raise ReleaseRejected("Invalid or truncated job response")
        for name in workflow["jobs"]:
            matching = [j for j in jobs["jobs"] if j.get("name") == name]
            if (
                len(matching) != 1
                or matching[0].get("status") != "completed"
                or matching[0].get("conclusion") != "success"
                or matching[0].get("head_sha") != commit
            ):
                raise ReleaseRejected(
                    "Required job did not succeed on this commit: " + name
                )
        evidence.append(
            {
                "workflow": workflow["path"],
                "run_id": run["id"],
                "attempt": run["run_attempt"],
            }
        )
    return {
        "commit": commit,
        "repository": POLICY["repository"],
        "branch": POLICY["branch"],
        "workflows": evidence,
    }


def wait_for_release(
    commit,
    *,
    deadline=780,
    interval=60,
    fetch=github,
    clock=time.monotonic,
    pause=time.sleep,
):
    end = clock() + deadline
    while True:
        try:
            return assess(commit, fetch)
        except ReleasePending as error:
            remaining = end - clock()
            if remaining <= 0:
                raise ReleaseRejected(
                    "Release checks unavailable before deadline"
                ) from None
            print(str(error), flush=True)
            pause(min(interval, remaining))


def production_commit(environ):
    if (
        environ.get("ENVIRONMENT", "").lower() == "production"
        or environ.get("RENDER_GIT_BRANCH") == "main"
    ):
        if environ.get("ENVIRONMENT", "").lower() != "production":
            raise ReleaseRejected(
                "Main API deployments require production configuration"
            )
        if environ.get("RENDER_GIT_BRANCH") not in (None, "main"):
            raise ReleaseRejected("Production API must deploy the main branch")
        commit = environ.get("RENDER_GIT_COMMIT", "")
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise ReleaseRejected("A full production Git commit is required")
        return commit


def admit_production(environ):
    if commit := production_commit(environ):
        evidence = wait_for_release(commit)
        print(json.dumps({"release_gate": "passed", **evidence}), flush=True)
        return evidence


def policy_digest():
    return hashlib.sha256(json.dumps(POLICY, sort_keys=True).encode()).hexdigest()


def build_production(environ):
    # Always discard a copied/stale proof before checking this build's commit.
    ATTESTATION.unlink(missing_ok=True)
    if production_commit(environ) is None:
        return
    previous_token = os.environ.get("GITHUB_RELEASE_TOKEN")
    try:
        if TOKEN_FILE.is_file():
            token = TOKEN_FILE.read_text().strip()
            if not token or len(token) > 8192:
                raise ReleaseRejected("Invalid GitHub release credential file")
            os.environ["GITHUB_RELEASE_TOKEN"] = token
        evidence = admit_production(environ)
        ATTESTATION.write_text(
            json.dumps({**evidence, "policy_digest": policy_digest()}) + "\n"
        )
        ATTESTATION.chmod(0o600)
    finally:
        if previous_token is None:
            os.environ.pop("GITHUB_RELEASE_TOKEN", None)
        else:
            os.environ["GITHUB_RELEASE_TOKEN"] = previous_token


def verify_production_build(environ):
    """Validate the built artifact locally; cold starts never depend on GitHub."""
    if (commit := production_commit(environ)) is None:
        return
    try:
        evidence = json.loads(ATTESTATION.read_text())
        workflows = evidence["workflows"]
        valid = (
            evidence["commit"] == commit
            and evidence["repository"] == POLICY["repository"]
            and evidence["branch"] == POLICY["branch"]
            and evidence["policy_digest"] == policy_digest()
            and len(workflows) == len(POLICY["workflows"])
            and {w["workflow"] for w in workflows}
            == {w["path"] for w in POLICY["workflows"]}
            and all(
                type(w["run_id"]) is int
                and w["run_id"] > 0
                and type(w["attempt"]) is int
                and w["attempt"] > 0
                for w in workflows
            )
        )
    except (OSError, ValueError, KeyError, TypeError):
        valid = False
    if not valid:
        raise ReleaseRejected("Missing or incompatible production build admission")
    print(json.dumps({"release_gate": "admitted_build", **evidence}), flush=True)
