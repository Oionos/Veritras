import json
from types import SimpleNamespace

import pytest

import check_reconciliation_rpc as probe
from check_deployment_identity import rpc_failure
from environment_policy import environment


def fake_web3(policy, fail=None):
    calls = []
    def event(name):
        def logs(**kwargs):
            calls.append((name, kwargs))
            if fail:
                raise fail
            return [{"blockNumber": kwargs["from_block"], "private_extra": "private-row-data"}]
        return lambda: SimpleNamespace(get_logs=logs)
    events = SimpleNamespace(**{name: event(name) for _, _, names in probe.SOURCES for name in names})
    w3 = SimpleNamespace(
        eth=SimpleNamespace(
            block_number=policy["start_block"] + 2000,
            get_block=lambda number: {"hash": b"canonical"},
            contract=lambda **kwargs: SimpleNamespace(events=events),
        ),
        to_checksum_address=lambda address: address,
    )
    return w3, calls


def inspect(w3, policy=None, **kwargs):
    return probe.inspect_history(policy or environment("testing"), w3,
                                 verify=lambda *args: {"verified": True}, **kwargs)


def test_historical_probe_reads_five_events_in_first_bounded_batch_without_exposing_logs():
    policy = environment("testing")
    w3, calls = fake_web3(policy)
    report = inspect(w3)
    assert report["overall_result"] == "pass"
    assert report["full_recovery_verified"] is False and report["authorizes_activation"] is False
    assert len(calls) == 5 and set(report["event_counts"].values()) == {1}
    assert all(bounds == {"from_block": policy["start_block"] + 1,
                          "to_block": policy["start_block"] + 1000} for _, bounds in calls)
    assert "private-row-data" not in json.dumps(report)


def test_probe_requires_identity_before_historical_reads():
    result = probe.inspect_history(environment("testing"), object(),
                                  verify=lambda *args: {"verified": False, "state": "chain_mismatch"})
    assert result["overall_result"] == "blocked"
    assert result["deployment_identity"]["state"] == "chain_mismatch"


def test_probe_exposes_failed_event_method_and_safe_http_category_only():
    error = RuntimeError("https://provider.example/private-api-key")
    error.response = SimpleNamespace(status_code=429)
    w3, calls = fake_web3(environment("testing"), error)
    report = inspect(w3)
    assert report["overall_result"] == "blocked" and len(calls) == 1
    assert report["rpc_stage"] == "ProductRegistered"
    assert report["rpc_method"] == "eth_getLogs"
    assert report["rpc_http_status"] == 429 and report["rpc_failure_kind"] == "http_error"
    assert "private" not in json.dumps(report) and "provider.example" not in json.dumps(report)


def test_probe_rejects_changed_canonical_target():
    w3, _ = fake_web3(environment("testing"))
    headers = iter([b"before", b"after"])
    w3.eth.get_block = lambda number: {"hash": next(headers)}
    report = inspect(w3)
    assert report["overall_result"] == "blocked" and report["state"] == "canonical_target_mismatch"


def test_probe_does_not_query_unconfirmed_blocks():
    policy = environment("testing")
    w3, calls = fake_web3(policy)
    w3.eth.block_number = policy["start_block"] + policy["confirmations"] + 2
    report = inspect(w3)
    assert report["to_block"] == policy["start_block"] + 2
    assert len(calls) == 5
    w3.eth.block_number = policy["start_block"] + policy["confirmations"]
    calls.clear()
    report = inspect(w3)
    assert report["state"] == "confirmed_history_unavailable" and calls == []


@pytest.mark.parametrize("code,expected", [(-32005, -32005), (True, None), (999999, None), ("private-key", None)])
def test_legacy_web3_value_errors_expose_only_valid_numeric_rpc_codes(code, expected):
    report = rpc_failure(ValueError({"code": code, "message": "private-api-key"}))
    assert report.get("rpc_error_code") == expected
    assert "private" not in json.dumps(report)


def test_invalid_probe_configuration_never_prints_secret(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SEPOLIA_RPC_URL", "private-api-key")
    output = tmp_path / "report.json"
    monkeypatch.setattr("sys.argv", ["probe", "--environment", "testing", "--output", str(output)])
    assert probe.main() == 1
    assert json.loads(output.read_text())["state"] == "invalid_probe_configuration"
    assert "private-api-key" not in capsys.readouterr().out
