"""Read-only prerequisite for production DDL; does not apply any migration.

Run after protected merge and successful exact-main CI, while coordinating the
replacement image rollout. Rehearsal and a retained backup remain mandatory.
"""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from check_health import fetch_json, validate_url
from release_gate import assess


def preflight(
    *,
    candidate,
    current,
    origin,
    sql_file,
    fetch=fetch_json,
    admission=assess,
    now=None
):
    if any(
        not re.fullmatch(r"[0-9a-f]{40}", value or "") for value in (candidate, current)
    ):
        raise ValueError("Full current and candidate commits are required")
    if candidate == current:
        raise ValueError("Candidate must differ from current deployed API")
    proof = admission(candidate)  # Exact main-push workflow + all required jobs.
    if proof.get("commit") != candidate:
        raise ValueError("Candidate admission mismatch")
    live_code, live = fetch(origin + "/health/live", 15)
    ready_code, ready = fetch(origin + "/health/ready", 15)
    if (
        live_code != 200
        or ready_code != 200
        or live.get("status") != "alive"
        or ready.get("status") != "ready"
        or ready.get("database") != "connected"
        or any(
            body.get("release_commit") != current
            or body.get("environment") != "production"
            for body in (live, ready)
        )
    ):
        raise ValueError(
            "The current production API must already be awake, ready and on the expected commit"
        )
    source = Path(sql_file).read_bytes()
    if not source:
        raise ValueError("Reviewed SQL file is empty")
    now = now or datetime.now(timezone.utc)
    return dict(
        approved_for_coordination=True,
        not_authorization_to_apply=True,
        candidate=candidate,
        current=current,
        sql_sha256=hashlib.sha256(source).hexdigest(),
        checked_at=now.isoformat(),
        expires_at=(now + timedelta(minutes=2)).isoformat(),
        workflow_evidence=proof["workflows"],
        next_step="Confirm replacement build has passed admission; apply rehearsed additive DDL immediately with rollout. Recheck if delayed. Never bypass schema admission or downgrade.",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--current", required=True)
    parser.add_argument("--url", required=True, type=validate_url)
    parser.add_argument("--sql-file", required=True)
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                preflight(
                    candidate=args.candidate,
                    current=args.current,
                    origin=args.url,
                    sql_file=args.sql_file,
                ),
                sort_keys=True,
            )
        )
    except Exception as error:
        # Provider errors may contain URLs or credentials. Type only.
        print(
            json.dumps(
                {"approved_for_coordination": False, "reason": type(error).__name__}
            )
        )
        raise SystemExit(1)
