"""Bounded Neon lifecycle for authenticated, expiring recovery branches only."""

import argparse
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler

NAME = re.compile(r"vr-recovery-(\d+)-(\d+)-(\d+)-(\d+)-([0-9a-f]{40})-([0-9a-f]{24})")


class ResourceError(Exception):
    """Fixed diagnostics only. Provider messages and connection URIs are private."""


def timestamp(epoch):
    return (
        datetime.fromtimestamp(epoch, timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def epoch(value):
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def private_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump(value, output, sort_keys=True, indent=2)
        output.write("\n")
    os.replace(temporary, path)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class NeonClient:
    def __init__(self, api_key):
        if not api_key:
            raise ResourceError("neon_credential_missing")
        self.api_key = api_key
        self.opener = build_opener(NoRedirect())

    def request(self, method, path, body=None, query=None):
        if not re.fullmatch(r"/projects/[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_/-]+)?", path):
            raise ResourceError("invalid_provider_path")
        url = "https://console.neon.tech/api/v2" + path
        if query:
            url += "?" + urlencode(query)
        request = Request(
            url,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": "Bearer " + self.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with self.opener.open(request, timeout=20) as response:
                payload = response.read(2_000_001)
                if len(payload) > 2_000_000:
                    raise ResourceError("provider_response_too_large")
                return json.loads(payload) if payload else {}
        except HTTPError as error:
            if error.code == 404:
                raise ResourceError("provider_not_found") from None
            raise ResourceError("provider_request_failed") from None
        except Exception:
            raise ResourceError("provider_request_failed") from None

    def wait(self, project, response, timeout=300):
        deadline = time.monotonic() + timeout
        for operation in response.get("operations", []):
            identifier = operation["id"]
            while True:
                item = self.request(
                    "GET", f"/projects/{project}/operations/{identifier}"
                )["operation"]
                if item["status"] in {"finished", "skipped"}:
                    break
                if (
                    item["status"] not in {"scheduling", "running"}
                    or time.monotonic() >= deadline
                ):
                    raise ResourceError("provider_operation_failed_or_timed_out")
                time.sleep(2)


class RecoveryResources:
    def __init__(
        self,
        client,
        *,
        project,
        source,
        environment,
        ownership_key,
        ledger,
        max_branches=20,
        clock=time.time,
    ):
        if (
            not re.fullmatch(r"[a-zA-Z0-9_-]+", project or "")
            or not re.fullmatch(r"br-[a-zA-Z0-9_-]+", source or "")
            or environment not in {"production", "testing"}
            or len(ownership_key) < 32
            or not 1 <= max_branches <= 100
        ):
            raise ResourceError("invalid_resource_configuration")
        self.client, self.project, self.source = client, project, source
        self.environment, self.key = environment, ownership_key.encode()
        self.ledger, self.clock, self.max_branches = Path(ledger), clock, max_branches

    def signature(self, payload):
        value = (
            f"Oionos/Veritras:{self.project}:{self.source}:{self.environment}:{payload}"
        )
        return hmac.new(self.key, value.encode(), hashlib.sha256).hexdigest()[:24]

    def owned_name(self, name):
        match = NAME.fullmatch(name or "")
        if not match:
            return False
        run, attempt, created, expires, sha, signature = match.groups()
        payload = f"{run}-{attempt}-{created}-{expires}-{sha}"
        return (
            int(run) > 0
            and int(attempt) > 0
            and 3600 <= int(expires) - int(created) <= 21600
            and hmac.compare_digest(self.signature(payload), signature)
        )

    def branches(self):
        result, cursor, seen = [], None, set()
        for _ in range(10):
            query = {"limit": 100}
            if cursor:
                query["cursor"] = cursor
            page = self.client.request(
                "GET", f"/projects/{self.project}/branches", query=query
            )
            result.extend(page["branches"])
            cursor = page.get("pagination", {}).get("next")
            if not cursor:
                return result
            if cursor in seen:
                break
            seen.add(cursor)
        raise ResourceError("branch_listing_incomplete")

    def verify_owned(self, branch, *, expected_name=None):
        if (
            branch.get("project_id") != self.project
            or branch.get("parent_id") != self.source
            or branch.get("id") == self.source
            or branch.get("default") is not False
            or branch.get("protected") is not False
            or not self.owned_name(branch.get("name"))
            or expected_name is not None
            and branch["name"] != expected_name
        ):
            raise ResourceError("resource_ownership_mismatch")
        match = NAME.fullmatch(branch["name"])
        created, expires = int(match[3]), int(match[4])
        if abs(epoch(branch["created_at"]) - created) > 900:
            raise ResourceError("resource_creation_time_mismatch")
        if branch.get("expires_at") and epoch(branch["expires_at"]) != expires:
            raise ResourceError("resource_expiration_changed")
        return expires

    def create(self, *, run_id, attempt, sha, ttl=7200, checkpoint_age=60, pg_major=17):
        if (
            not re.fullmatch(r"[0-9a-f]{40}", sha)
            or not str(run_id).isdigit()
            or not str(attempt).isdigit()
            or int(run_id) < 1
            or int(attempt) < 1
            or not 3600 <= ttl <= 21600
            or not 1 <= checkpoint_age <= 3600
            or pg_major not in {16, 17, 18}
            or self.ledger.exists()
        ):
            raise ResourceError("invalid_creation_request")
        project = self.client.request("GET", f"/projects/{self.project}")["project"]
        if (
            project.get("id") != self.project
            or project.get("pg_version") != pg_major
            or project.get("history_retention_seconds", 0) < checkpoint_age + 60
        ):
            raise ResourceError("project_version_or_retention_mismatch")
        source = self.client.request(
            "GET", f"/projects/{self.project}/branches/{self.source}"
        )["branch"]
        if source.get("id") != self.source or source.get("project_id") != self.project:
            raise ResourceError("source_branch_mismatch")
        if len(self.branches()) >= self.max_branches:
            raise ResourceError("rehearsal_branch_budget_exceeded")
        created = int(self.clock())
        payload = f"{run_id}-{attempt}-{created}-{created + ttl}-{sha}"
        name = "vr-recovery-" + payload + "-" + self.signature(payload)
        ledger = {
            "project": self.project,
            "source": self.source,
            "name": name,
            "environment": self.environment,
            "created": created,
            "expires": created + ttl,
            "checkpoint_time": timestamp(created - checkpoint_age),
            "branch_id": None,
        }
        private_json(
            self.ledger, ledger
        )  # Persist intent BEFORE non-idempotent creation.
        response = self.client.request(
            "POST",
            f"/projects/{self.project}/branches",
            body={
                "branch": {
                    "name": name,
                    "parent_id": self.source,
                    "parent_timestamp": ledger["checkpoint_time"],
                    "init_source": "parent-data",
                    "expires_at": timestamp(created + ttl),
                },
                "endpoints": [
                    {
                        "type": "read_write",
                        "autoscaling_limit_min_cu": 0.25,
                        "autoscaling_limit_max_cu": 0.5,
                        "suspend_timeout_seconds": 0,
                    }
                ],
            },
        )
        identifier = response["branch"]["id"]
        ledger["branch_id"] = identifier
        private_json(
            self.ledger, ledger
        )  # Never persist provider responses containing credentials.
        self.client.wait(self.project, response)
        branch = self.client.request(
            "GET", f"/projects/{self.project}/branches/{identifier}"
        )["branch"]
        if branch.get("id") != identifier:
            raise ResourceError("branch_identity_mismatch")
        self.verify_owned(branch, expected_name=name)
        if not branch.get("expires_at") or branch.get("current_state") != "ready":
            raise ResourceError("provider_expiration_or_branch_not_ready")
        if not re.fullmatch(r"[0-9a-fA-F]+/[0-9a-fA-F]+", branch.get("parent_lsn", "")):
            raise ResourceError("checkpoint_lsn_missing")
        endpoints = response.get("endpoints", [])
        matching = [
            item
            for item in endpoints
            if item.get("branch_id") == identifier and item.get("type") == "read_write"
        ]
        if len(matching) != 1:
            raise ResourceError("private_endpoint_mismatch")
        endpoint = self.client.request(
            "GET", f"/projects/{self.project}/endpoints/{matching[0]['id']}"
        )["endpoint"]
        if (
            endpoint.get("project_id") != self.project
            or endpoint.get("branch_id") != identifier
            or endpoint.get("autoscaling_limit_max_cu", 999) > 0.5
            or not re.fullmatch(r"[a-zA-Z0-9.-]+\.neon\.tech", endpoint.get("host", ""))
        ):
            raise ResourceError("private_endpoint_budget_or_host_mismatch")
        ledger.update(
            endpoint_id=endpoint["id"],
            host=endpoint["host"],
            parent_lsn=branch.get("parent_lsn"),
        )
        private_json(self.ledger, ledger)
        return ledger

    def verify_live_ownership(self, ledger):
        if (
            ledger.get("project") != self.project
            or ledger.get("source") != self.source
            or ledger.get("environment") != self.environment
        ):
            raise ResourceError("ledger_scope_mismatch")
        identifier = ledger["branch_id"]
        branch = self.client.request(
            "GET", f"/projects/{self.project}/branches/{identifier}"
        )["branch"]
        if branch.get("id") != identifier:
            raise ResourceError("branch_identity_mismatch")
        self.verify_owned(branch, expected_name=ledger["name"])
        endpoint = self.client.request(
            "GET", f"/projects/{self.project}/endpoints/{ledger['endpoint_id']}"
        )["endpoint"]
        if (
            endpoint.get("branch_id") != identifier
            or endpoint.get("project_id") != self.project
            or endpoint.get("host") != ledger["host"]
        ):
            raise ResourceError("endpoint_ownership_mismatch")

    def cleanup(self):
        if not self.ledger.exists():
            return {"state": "not_created", "deleted": 0}
        ledger = json.loads(self.ledger.read_text())
        if (
            ledger.get("project") != self.project
            or ledger.get("source") != self.source
            or ledger.get("environment") != self.environment
            or not self.owned_name(ledger.get("name"))
        ):
            raise ResourceError("ledger_scope_mismatch")
        if ledger.get("branch_id"):
            try:
                branch = self.client.request(
                    "GET", f"/projects/{self.project}/branches/{ledger['branch_id']}"
                )["branch"]
                matching = [branch]
            except ResourceError as error:
                if str(error) != "provider_not_found":
                    raise
                return {"state": "already_deleted", "deleted": 0}
        else:
            # Creation timeout: never repeat POST. Rediscover only the exact
            # authenticated intent name; expiration is the independent fallback.
            matching = [
                item for item in self.branches() if item.get("name") == ledger["name"]
            ]
            if not matching:
                raise ResourceError("creation_outcome_unconfirmed")
        if len(matching) != 1:
            raise ResourceError("ambiguous_cleanup_target")
        branch = matching[0]
        if ledger.get("branch_id") and branch.get("id") != ledger["branch_id"]:
            raise ResourceError("branch_identity_mismatch")
        self.verify_owned(branch, expected_name=ledger["name"])
        if not ledger.get("branch_id"):
            ledger["branch_id"] = branch["id"]
            private_json(self.ledger, ledger)
        try:
            response = self.client.request(
                "DELETE", f"/projects/{self.project}/branches/{branch['id']}"
            )
        except ResourceError as error:
            if str(error) != "provider_not_found":
                raise
            response = {}
        self.client.wait(self.project, response)
        try:
            self.client.request(
                "GET", f"/projects/{self.project}/branches/{branch['id']}"
            )
        except ResourceError as error:
            if str(error) == "provider_not_found":
                return {"state": "deleted", "deleted": 1}
            raise
        raise ResourceError("deletion_not_verified")

    def reap_expired(self):
        deleted = []
        for branch in self.branches():
            if not self.owned_name(branch.get("name")):
                continue
            expires = self.verify_owned(branch)
            if expires > self.clock():
                continue
            try:
                response = self.client.request(
                    "DELETE", f"/projects/{self.project}/branches/{branch['id']}"
                )
            except ResourceError as error:
                if str(error) != "provider_not_found":
                    raise
                response = {}
            self.client.wait(self.project, response)
            try:
                self.client.request(
                    "GET", f"/projects/{self.project}/branches/{branch['id']}"
                )
            except ResourceError as error:
                if str(error) == "provider_not_found":
                    deleted.append(branch["id"])
                    continue
                raise
            raise ResourceError("deletion_not_verified")
        return {"state": "completed", "deleted": len(deleted)}


def from_environment(ledger):
    return RecoveryResources(
        NeonClient(os.environ.get("NEON_API_KEY")),
        project=os.environ.get("NEON_PROJECT_ID", ""),
        source=os.environ.get("NEON_SOURCE_BRANCH_ID", ""),
        environment=os.environ.get("REHEARSAL_ENVIRONMENT", ""),
        ownership_key=os.environ.get("REHEARSAL_OWNERSHIP_KEY", ""),
        ledger=ledger,
        max_branches=int(os.environ.get("REHEARSAL_MAX_BRANCHES", "20")),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["cleanup", "reap-expired"])
    parser.add_argument("--ledger", type=Path, required=True)
    args = parser.parse_args()
    if args.operation == "cleanup" and not args.ledger.exists():
        print(json.dumps({"state": "not_created", "deleted": 0}))
        return 0
    try:
        manager = from_environment(args.ledger)
        result = (
            manager.cleanup() if args.operation == "cleanup" else manager.reap_expired()
        )
    except Exception:
        print(json.dumps({"state": "cleanup_failed", "manual_review_required": True}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
