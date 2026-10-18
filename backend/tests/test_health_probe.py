import copy
import json
import sys
import pytest
import check_health


def bodies(enabled=True):
    common = dict(environment="testing", chain_id=11155111, release_commit="a" * 40)
    live = dict(common, status="alive")
    indexer = dict(
        status="current" if enabled else "disabled",
        enabled=enabled,
        ready=enabled,
        confirmation_policy="depth",
        confirmations=12,
        chain_head=112,
        target_head=100,
        last_processed_block=100,
        lag_blocks=0,
        max_lag_blocks=0,
        success_age_seconds=1,
        stale_after_seconds=120,
    )
    return live, dict(common, status="ready", database="connected", indexer=indexer)


def run(live, ready, **kwargs):
    return check_health.probe(
        "https://test.invalid",
        environment="testing",
        fetch=lambda url, timeout: (
            200,
            copy.deepcopy(live if url.endswith("/live") else ready),
        ),
        **kwargs
    )


def test_current_and_disabled_policies():
    assert run(*bodies())["ready"]
    assert run(*bodies(False), expect_indexer=False)["ready"]
    assert not run(*bodies(False), expect_indexer=True)["ready"]


def test_requires_matching_release_and_environment():
    live, ready = bodies()
    assert run(live, ready, expected_commit="b" * 40)["state"] == "awaiting_deployment"
    live["chain_id"] = 31337
    assert run(live, ready)["state"] == "environment_mismatch"


@pytest.mark.parametrize(
    "field,value,state",
    [
        ("target_head", 112, "inconsistent_progress"),
        ("last_processed_block", 101, "inconsistent_progress"),
        ("lag_blocks", 10, "inconsistent_progress"),
        ("success_age_seconds", 120, "stale_progress"),
        ("success_age_seconds", float("nan"), "stale_progress"),
        ("confirmations", 0, "policy_mismatch"),
    ],
)
def test_rejects_inconsistent_current_claims(field, value, state):
    live, ready = bodies()
    ready["indexer"][field] = value
    assert run(live, ready)["state"] == state


def test_backfill_and_database_failure_are_not_ready():
    live, ready = bodies()
    ready["indexer"].update(status="catching_up", reason="backfill", ready=False)
    assert not run(live, ready)["ready"]
    ready["database"] = "timed_out"
    assert not run(live, ready)["ready"]


def test_transport_and_body_errors_never_print_private_content():
    def fail(*_):
        raise ConnectionError("https://user:private@rpc.invalid/secret-token")

    result = check_health.probe(
        "https://test.invalid", environment="testing", fetch=fail
    )
    assert result == {"ready": False, "state": "invalid_or_unavailable_response"}
    live, ready = bodies()
    ready["indexer"].update(last_error="private-token", reason="private-token")
    assert "private-token" not in json.dumps(run(live, ready))


@pytest.mark.parametrize(
    "url",
    [
        "https://user:password@example.test",
        "https://example.test?token=secret",
        "https://example.test/health",
        "file:///tmp/secret",
    ],
)
def test_monitor_rejects_credentialed_or_non_origin_urls(url):
    with pytest.raises(ValueError):
        check_health.validate_url(url)


def test_cli_single_check_and_failure_exit_codes(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_health.py",
            "--url",
            "https://test.invalid",
            "--environment",
            "testing",
        ],
    )
    monkeypatch.setattr(
        check_health, "probe", lambda *_, **__: dict(ready=True, state="current")
    )
    assert check_health.main() == 0
    monkeypatch.setattr(
        check_health, "probe", lambda *_, **__: dict(ready=False, state="degraded")
    )
    assert check_health.main() == 1
    assert len(capsys.readouterr().out.splitlines()) == 2


def test_cli_deadline_is_bounded(monkeypatch):
    clock = [0.0]
    calls = []
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_health.py",
            "--url",
            "https://test.invalid",
            "--environment",
            "testing",
            "--deadline",
            "3",
            "--interval",
            "2",
        ],
    )
    monkeypatch.setattr(
        check_health,
        "time",
        type(
            "Clock",
            (),
            dict(
                monotonic=staticmethod(lambda: clock[0]),
                sleep=staticmethod(
                    lambda delay: clock.__setitem__(0, clock[0] + delay)
                ),
            ),
        ),
    )

    def probe(*_, **kwargs):
        calls.append(kwargs["timeout"])
        clock[0] += 0.5
        return dict(ready=False, state="catching_up")

    monkeypatch.setattr(check_health, "probe", probe)
    assert check_health.main() == 1
    assert len(calls) == 2 and max(calls) <= 3 and clock[0] <= 3.5
