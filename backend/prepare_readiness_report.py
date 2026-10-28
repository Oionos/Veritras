"""Sanitized read-only identity/readiness evidence. Never authorizes activation."""

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
import re
from pathlib import Path

from check_deployment_identity import configured_verification
from check_health import fetch_json, probe
from environment_policy import load_policy, policy_digest


def scope_matches(body, expected):
    indexer = body.get("indexer", {})
    return (
        type(indexer.get("chain_id")) is int
        and indexer["chain_id"] == expected["chain_id"]
        and str(indexer.get("registry_address", "")).lower() == expected["registry"].lower()
        and str(indexer.get("tracker_address", "")).lower() == expected["tracker"].lower()
        and type(indexer.get("start_block")) is int
        and indexer["start_block"] == expected["start_block"]
    )


def fresh_chain_head(body):
    indexer = body.get("indexer", {})
    age, stale = indexer.get("head_age_seconds"), indexer.get("head_stale_after_seconds")
    return (indexer.get("cursor_storage") == "database"
            and all(type(value) in (int, float) and math.isfinite(value) for value in (age, stale))
            and 0 <= age < stale)


def build_report(name, candidate_sha, backend_sha, *, policy=None, fetch=fetch_json,
                 verify=configured_verification, now=None, release_sha=None):
    release_sha = release_sha or candidate_sha
    if any(not re.fullmatch(r"[0-9a-f]{40}", sha) for sha in (candidate_sha, backend_sha, release_sha)):
        raise ValueError("Full release SHAs required")
    policy = load_policy() if policy is None else policy
    expected = policy["environments"][name]
    now = now or datetime.now(timezone.utc)
    observed = {}
    responses = {}

    def capture(url, timeout):
        status, body = fetch(url, timeout)
        responses[url] = (status, body)
        if url.endswith("/health/ready"):
            observed.update(body)
        return status, body

    health = probe(expected["api_origin"], environment=name, chain_id=expected["chain_id"],
                   confirmations=expected["confirmations"], expected_commit=backend_sha,
                   expect_indexer=expected["indexer_mode"] == "enabled", fetch=capture)
    if health["state"] == "awaiting_deployment" and release_sha != backend_sha:
        # A frontend/docs-only release can legitimately serve either its branch
        # tip or the last backend-changing ancestor. Verify both health bodies
        # against one exact allowed SHA; never trust an arbitrary observed SHA.
        health = probe(expected["api_origin"], environment=name, chain_id=expected["chain_id"],
                       confirmations=expected["confirmations"], expected_commit=release_sha,
                       expect_indexer=expected["indexer_mode"] == "enabled",
                       fetch=lambda url, _: responses[url])
    identity = verify(expected)
    scope = scope_matches(observed, expected) if expected["start_block"] is not None else False
    zero_lag = expected["indexer_mode"] == "disabled" or health.get("lag_blocks") == 0
    fresh_head = expected["indexer_mode"] == "disabled" or fresh_chain_head(observed)
    passed = health["ready"] and identity["verified"] and scope and zero_lag and fresh_head
    return {
        "report_version": 1, "report_type": "read_only_readiness",
        "candidate_sha": candidate_sha, "release_sha": release_sha,
        "expected_backend_sha": backend_sha,
        "backend_sha": observed.get("release_commit") if health["ready"] else None,
        "policy_digest": policy_digest(policy), "environment": name,
        "observed_at": now.isoformat(), "expires_at": (now + timedelta(hours=24)).isoformat(),
        "health": health, "deployment_identity": identity,
        "runtime_scope_matches": scope, "zero_confirmed_target_lag": zero_lag,
        "fresh_chain_head": fresh_head,
        "overall_result": "pass" if passed else "blocked",
        "authorizes_activation": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=["production", "testing"], required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--backend-sha", required=True)
    parser.add_argument("--release-sha", help="Reviewed target branch tip; defaults to candidate SHA")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = build_report(args.environment, args.candidate_sha, args.backend_sha, release_sha=args.release_sha)
    except Exception:
        report = {"report_version": 1, "overall_result": "blocked",
                  "state": "invalid_configuration_or_evidence", "authorizes_activation": False}
    content = json.dumps(report, sort_keys=True, indent=2) + "\n"
    args.output.write_text(content)
    print(content, end="")
    return 0 if report["overall_result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
