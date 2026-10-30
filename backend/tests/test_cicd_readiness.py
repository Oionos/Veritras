import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from check_deployment_identity import configured_verification, rpc_failure, verify_identity
from environment_policy import load_policy, policy_digest
from prepare_readiness_report import build_report
from sync_environment_policy import sync

SHA = "a" * 40


@pytest.fixture
def policy():
    return copy.deepcopy(load_policy())


class FakeWeb3:
    to_checksum_address = staticmethod(lambda value: value)

    def __init__(self, policy):
        self.policy = policy
        self.receipts = {
            policy[name + "_creation_tx"]: {
                "status": 1,
                "contractAddress": policy[name],
                "transactionHash": bytes.fromhex(policy[name + "_creation_tx"][2:]),
                "blockNumber": policy["start_block"] + index + 1,
                "blockHash": bytes([index + 1]) * 32,
            }
            for index, name in enumerate(("registry", "tracker"))
        }
        self.blocks = {
            row["blockNumber"]: {"hash": row["blockHash"]}
            for row in self.receipts.values()
        }
        self.eth = SimpleNamespace(
            chain_id=policy["chain_id"],
            block_number=policy["start_block"] + 100,
            get_transaction_receipt=lambda tx: self.receipts[tx],
            get_block=lambda block: self.blocks[block],
            get_code=lambda address: b"code",
            contract=lambda **_: SimpleNamespace(
                functions=SimpleNamespace(
                    productRegistry=lambda: SimpleNamespace(
                        call=lambda: policy["registry"]
                    )
                )
            ),
        )


def health(expected, enabled=True):
    common = {
        "environment": "testing",
        "chain_id": expected["chain_id"],
        "release_commit": SHA,
    }
    indexer = {
        "enabled": enabled,
        "status": "current" if enabled else "disabled",
        "ready": enabled,
        "confirmation_policy": "depth",
        "confirmations": expected["confirmations"],
        "registry_address": expected["registry"],
        "tracker_address": expected["tracker"],
        "start_block": expected["start_block"],
        "chain_head": 112,
        "target_head": 100,
        "last_processed_block": 100,
        "lag_blocks": 0,
        "max_lag_blocks": 0,
        "success_age_seconds": 1,
        "stale_after_seconds": 120,
        "chain_id": expected["chain_id"],
        "cursor_storage": "database",
        "head_age_seconds": 1,
        "head_stale_after_seconds": 300,
    }
    return dict(common, status="alive"), dict(
        common, status="ready", database="connected", indexer=indexer
    )


def test_policy_is_valid_mirrored_and_keeps_production_disabled(policy):
    assert sync()
    assert policy["environments"]["production"]["indexer_mode"] == "disabled"
    assert policy["environments"]["production"]["start_block"] is None
    assert len(policy_digest(policy)) == 64
    root = Path(__file__).resolve().parents[2]
    assert json.loads((root / "release/environment-policy.json").read_text()) == policy
    deployed = json.loads((root / "blockchain/deployment.testing.json").read_text())
    testing = policy["environments"]["testing"]
    assert testing["start_block"] == deployed["startBlock"] - 1
    for key, contract in (
        ("registry", "ProductRegistry"),
        ("tracker", "ShipmentTracker"),
    ):
        assert testing[key] == deployed["contracts"][contract]
        assert (
            testing[key + "_creation_tx"]
            == deployed["deploymentTransactions"][contract]
        )


def test_observer_is_trusted_manual_read_only_and_not_an_admission_prerequisite():
    import yaml

    root = Path(__file__).resolve().parents[2]
    workflow = yaml.load(
        (root / ".github/workflows/production-readiness.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["inspect"]
    assert "github.ref == 'refs/heads/main'" in job["if"]
    assert "github.repository == 'Oionos/Veritras'" in job["if"]
    assert job["environment"] == "${{ inputs.environment == 'testing' && 'recovery-testing' || 'readiness' }}"
    assert workflow["on"]["workflow_dispatch"]["inputs"]["inspect_history"]["default"] == "false"
    history = next(step for step in job["steps"] if "check_reconciliation_rpc.py" in step.get("run", ""))
    assert history["if"] == "${{ !cancelled() && inputs.inspect_history && steps.readiness.outcome != 'skipped' }}"
    readiness = next(step for step in job["steps"] if step.get("id") == "readiness")
    assert "prepare_readiness_report.py" in readiness["run"]
    assert set(history["env"]) == {"SELECTED_ENVIRONMENT", "SEPOLIA_RPC_URL"}
    commands = "\n".join(step.get("run", "") for step in job["steps"])
    assert "prepare_readiness_report.py" in commands
    assert "--apply" not in commands
    assert "restore" not in commands
    for directory in ("backend", "frontend"):
        admission = json.loads((root / directory / "release_policy.json").read_text())
        assert all(
            item["path"]
            not in {
                ".github/workflows/production-readiness.yml",
                ".github/workflows/recovery-rehearsal.yml",
                ".github/workflows/recovery-cleanup.yml",
            }
            for item in admission["workflows"]
        )


@pytest.mark.parametrize("filename", ["production-readiness.yml", "recovery-rehearsal.yml"])
def test_recovery_workflow_embedded_python_is_valid(filename):
    import re
    import yaml
    root = Path(__file__).resolve().parents[2]
    workflow = yaml.load((root / ".github/workflows" / filename).read_text(), Loader=yaml.BaseLoader)
    snippets = []
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            snippets.extend(re.findall(r"python - <<'PY'\n(.*?)\nPY", step.get("run", ""), re.S))
    assert snippets
    for source in snippets:
        compile(source, filename, "exec")


@pytest.mark.parametrize(
    "field,value",
    [
        ("confirmations", True),
        ("start_block", -1),
        ("indexer_mode", "either"),
        ("api_origin", "https://user:secret@example.com"),
        ("registry", "0x0"),
        ("registry_creation_tx", "fake"),
        ("chain_id", 0),
    ],
)
def test_invalid_policy_is_rejected(policy, tmp_path, field, value):
    policy["environments"]["testing"][field] = value
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy))
    with pytest.raises(ValueError):
        load_policy(path)


def test_canonical_creation_and_registry_linkage(policy):
    expected = policy["environments"]["testing"]
    result = verify_identity(expected, FakeWeb3(expected))
    assert result["verified"]
    assert result["start_block"] == expected["start_block"]
    assert len(result["receipts"]) == 2


@pytest.mark.parametrize("status,code,expected", [
    (403, None, {"rpc_http_status": 403}),
    (429, -32005, {"rpc_http_status": 429, "rpc_error_code": -32005}),
    (True, "private-message", {}),
    (900, 10**20, {}),
])
def test_rpc_failure_publishes_numeric_codes_and_never_provider_messages(policy, status, code, expected):
    error = RuntimeError("https://provider.example/private-key and private-message")
    error.response = SimpleNamespace(status_code=status)
    error.rpc_response = {"error": {"code": code, "message": "private-message"}}
    wanted = {"verified": False, "state": "rpc_invalid_or_unavailable",
              "rpc_failure_kind": "http_error" if "rpc_http_status" in expected else "client_error", **expected}
    assert rpc_failure(error) == wanted
    w3 = FakeWeb3(policy["environments"]["testing"])
    def fail(_):
        raise error
    w3.eth.get_transaction_receipt = fail
    result = verify_identity(policy["environments"]["testing"], w3, sleep=lambda _: None)
    retry = {"rpc_attempts": 3, "rpc_retries": 2} if status == 429 else {}
    assert result == {**wanted, "rpc_stage": "registry_creation_receipt", **retry}
    assert "private" not in json.dumps(result)


@pytest.mark.parametrize(
    "change,state",
    [
        ("chain", "chain_mismatch"),
        ("receipt", "creation_receipt_mismatch"),
        ("hash", "noncanonical_creation"),
        ("code", "contract_not_deployed"),
        ("registry", "tracker_registry_mismatch"),
        ("anchor", "deployment_anchor_mismatch"),
        ("confirmation", "creation_not_confirmed"),
        ("transaction", "creation_receipt_mismatch"),
    ],
)
def test_identity_rejects_mismatches(policy, change, state):
    expected = policy["environments"]["testing"]
    w3 = FakeWeb3(expected)
    receipt = w3.receipts[expected["registry_creation_tx"]]
    if change == "chain":
        w3.eth.chain_id = 1
    elif change == "receipt":
        receipt["contractAddress"] = expected["tracker"]
    elif change == "transaction":
        receipt["transactionHash"] = b"x" * 32
    elif change == "hash":
        receipt["blockHash"] = b"x" * 32
    elif change == "code":
        w3.eth.get_code = lambda _: b""
    elif change == "registry":
        w3.eth.contract = lambda **_: SimpleNamespace(
            functions=SimpleNamespace(
                productRegistry=lambda: SimpleNamespace(
                    call=lambda: expected["tracker"]
                )
            )
        )
    elif change == "anchor":
        expected["start_block"] += 1
    elif change == "confirmation":
        w3.eth.block_number = receipt["blockNumber"]
    assert verify_identity(expected, w3) == {"verified": False, "state": state}


def test_missing_production_evidence_and_rpc_never_pass(policy):
    assert (
        configured_verification(policy["environments"]["production"])["state"]
        == "deployment_evidence_missing"
    )
    assert (
        configured_verification(policy["environments"]["testing"], "")["state"]
        == "rpc_not_configured"
    )


def test_transient_missing_creation_receipt_is_retried_then_fully_verified(policy):
    from web3.exceptions import TransactionNotFound
    expected = policy["environments"]["testing"]
    w3 = FakeWeb3(expected)
    calls, pauses = [], []
    original = w3.eth.get_transaction_receipt
    def receipt(tx):
        calls.append(tx)
        if len(calls) <= 2:
            raise TransactionNotFound("private-provider-message")
        return original(tx)
    w3.eth.get_transaction_receipt = receipt
    result = verify_identity(expected, w3, sleep=pauses.append)
    assert result["verified"] is True and result["rpc_retries"] == 2
    assert len(result["receipts"]) == 2 and len(calls) == 4
    assert pauses == [1, 2]
    assert "private" not in json.dumps(result)


def test_persistently_missing_receipt_fails_after_bounded_attempts(policy):
    from web3.exceptions import TransactionNotFound
    expected = policy["environments"]["testing"]
    w3 = FakeWeb3(expected)
    calls, pauses = [], []
    def fail(tx):
        calls.append(tx)
        raise TransactionNotFound("https://provider.example/private-key")
    w3.eth.get_transaction_receipt = fail
    result = verify_identity(expected, w3, sleep=pauses.append)
    assert result == {"verified": False, "state": "rpc_invalid_or_unavailable",
                      "rpc_stage": "registry_creation_receipt", "rpc_failure_kind": "receipt_not_found",
                      "rpc_attempts": 3, "rpc_retries": 2}
    assert pauses == [1, 2] and len(calls) == 3
    assert "private" not in json.dumps(result)


def test_receipt_identity_mismatch_is_not_retried_or_accepted(policy):
    expected = policy["environments"]["testing"]
    w3 = FakeWeb3(expected)
    calls, pauses = [], []
    original = w3.eth.get_transaction_receipt
    def wrong(tx):
        calls.append(tx)
        return {**original(tx), "contractAddress": expected["tracker"]}
    w3.eth.get_transaction_receipt = wrong
    assert verify_identity(expected, w3, sleep=pauses.append) == {"verified": False, "state": "creation_receipt_mismatch"}
    assert len(calls) == 1 and pauses == []


def test_recovered_receipt_still_must_match_the_reviewed_transaction(policy):
    from web3.exceptions import TransactionNotFound
    expected = policy["environments"]["testing"]
    w3 = FakeWeb3(expected)
    original = w3.eth.get_transaction_receipt
    calls, pauses = [], []
    def receipt(tx):
        calls.append(tx)
        if len(calls) == 1:
            raise TransactionNotFound("private-key")
        return {**original(tx), "transactionHash": b"wrong"}
    w3.eth.get_transaction_receipt = receipt
    result = verify_identity(expected, w3, sleep=pauses.append)
    assert result == {"verified": False, "state": "creation_receipt_mismatch"}
    assert pauses == [1] and len(calls) == 2


@pytest.mark.parametrize("message,reason", [
    ("block range exceeds limit", "range_limit"),
    ("historical state unavailable", "historical_data_unavailable"),
    ("method not found", "method_unavailable"),
])
def test_permanent_rpc_errors_do_not_consume_retry_budget(policy, message, reason):
    expected = policy["environments"]["testing"]
    w3 = FakeWeb3(expected)
    calls, pauses = [], []
    def fail(tx):
        calls.append(tx)
        raise ValueError({"code": -32005, "message": message + " private-key"})
    w3.eth.get_transaction_receipt = fail
    result = verify_identity(expected, w3, sleep=pauses.append)
    assert not result["verified"] and result["rpc_reason"] == reason
    assert len(calls) == 1 and pauses == []
    assert "private" not in json.dumps(result)


def test_provider_internal_retries_are_disabled(policy, monkeypatch):
    import web3
    expected = policy["environments"]["testing"]
    options = {}
    class Factory:
        @staticmethod
        def HTTPProvider(url, **kwargs):
            options.update(kwargs)
            return object()
        def __new__(cls, provider):
            return FakeWeb3(expected)
    monkeypatch.setattr(web3, "Web3", Factory)
    assert configured_verification(expected, "https://provider.example/private-key")["verified"]
    assert options == {"request_kwargs": {"timeout": 10}, "exception_retry_configuration": None}


@pytest.mark.parametrize("status,attempts", [(401, 1), (403, 1), (429, 3), (503, 3)])
def test_identity_retries_transient_http_errors_but_not_auth_failures(policy, status, attempts):
    expected = policy["environments"]["testing"]
    w3 = FakeWeb3(expected)
    calls, pauses = [], []
    def fail(tx):
        calls.append(tx)
        error = RuntimeError("private-key")
        error.response = SimpleNamespace(status_code=status)
        raise error
    w3.eth.get_transaction_receipt = fail
    result = verify_identity(expected, w3, sleep=pauses.append)
    assert not result["verified"] and len(calls) == attempts
    assert pauses == ([1, 2] if attempts == 3 else [])
    assert result["rpc_http_status"] == status


@pytest.mark.parametrize("message,reason", [
    ("Too many requests: private-key", "rate_limited"),
    ("Please reduce block range: private-key", "range_limit"),
    ("Historical state unavailable: private-key", "historical_data_unavailable"),
    ("missing trie node: private-key", "historical_data_unavailable"),
    ("Method not found: private-key", "method_unavailable"),
    ("Unrecognized private provider message", None),
])
def test_rpc_messages_are_classified_into_fixed_reasons_without_publishing_them(message, reason):
    report = rpc_failure(ValueError({"code": -32000, "message": message}))
    assert report.get("rpc_reason") == reason
    assert "private" not in json.dumps(report)


def test_provider_failure_is_sanitized(policy):
    expected = policy["environments"]["testing"]
    w3 = FakeWeb3(expected)

    def fail(*_):
        raise RuntimeError("https://user:secret@provider.example/token")

    w3.eth.get_block = fail
    result = verify_identity(expected, w3)
    assert result == {"verified": False, "state": "rpc_invalid_or_unavailable",
                      "rpc_stage": "registry_creation_block", "rpc_failure_kind": "client_error"}
    assert "secret" not in json.dumps(result)


@pytest.mark.parametrize("url", [
    "private-api-key-only", "SEPOLIA_RPC_URL=https://provider.example/private-key",
    '"https://provider.example/private-key"', "http://provider.example/private-key",
    "https://provider.example/private-key#fragment",
])
def test_invalid_rpc_endpoint_shape_is_identified_without_printing_value(policy, url):
    result = configured_verification(policy["environments"]["testing"], url)
    assert result == {"verified": False, "state": "rpc_invalid_or_unavailable",
                      "rpc_stage": "configuration", "rpc_failure_kind": "configuration_invalid"}
    assert "private" not in json.dumps(result) and "provider.example" not in json.dumps(result)


@pytest.mark.parametrize("error_name,kind", [
    ("TransactionNotFound", "receipt_not_found"), ("BlockNotFound", "block_not_found"),
    ("ExtraDataLengthError", "block_header_format"), ("JSONDecodeError", "response_not_json"),
    ("BadFunctionCallOutput", "contract_call_failed"), ("ReadTimeout", "timeout"),
    ("PrivateSecretException", "client_error"),
])
def test_rpc_error_kinds_are_allowlisted_and_unknown_class_names_stay_private(error_name, kind):
    error = type(error_name, (Exception,), {})("private-key-in-error-message")
    result = rpc_failure(error, "registry_creation_receipt")
    assert result["rpc_failure_kind"] == kind
    assert result["rpc_stage"] == "registry_creation_receipt"
    assert "PrivateSecretException" not in json.dumps(result)
    assert "private-key" not in json.dumps(result)
    assert "rpc_stage" not in rpc_failure(error, ["private-stage"])


def test_rpc_call_sites_identify_linkage_failures(policy):
    expected = policy["environments"]["testing"]
    w3 = FakeWeb3(expected)
    def fail():
        raise type("BadFunctionCallOutput", (Exception,), {})("private-key")
    w3.eth.contract = lambda **_: SimpleNamespace(functions=SimpleNamespace(
        productRegistry=lambda: SimpleNamespace(call=fail)))
    result = verify_identity(expected, w3)
    assert result["rpc_stage"] == "tracker_registry"
    assert result["rpc_failure_kind"] == "contract_call_failed"
    assert result["verified"] is False and "private" not in json.dumps(result)


def test_readiness_report_binds_scope_policy_and_exact_backend(policy):
    expected = policy["environments"]["testing"]
    live, ready = health(expected)
    fetch = lambda url, _: (200, live if url.endswith("/live") else ready)
    verify = lambda item: verify_identity(item, FakeWeb3(item))
    report = build_report(
        "testing", SHA, SHA, policy=policy, fetch=fetch, verify=verify
    )
    assert report["overall_result"] == "pass"
    assert report["policy_digest"] == policy_digest(policy)
    assert report["authorizes_activation"] is False
    ready["indexer"]["tracker_address"] = "wrong"
    assert (
        build_report("testing", SHA, SHA, policy=policy, fetch=fetch, verify=verify)[
            "overall_result"
        ]
        == "blocked"
    )
    ready["indexer"]["tracker_address"] = expected["tracker"]
    ready["release_commit"] = "b" * 40  # Live/ready must agree on one allowed SHA.
    assert (
        build_report(
            "testing", SHA, "b" * 40, policy=policy, fetch=fetch, verify=verify
        )["overall_result"]
        == "blocked"
    )


def test_report_accepts_only_reviewed_branch_tip_or_backend_ancestor(policy):
    expected = policy["environments"]["testing"]
    live, ready = health(expected)
    fetch = lambda url, _: (200, live if url.endswith("/live") else ready)
    verify = lambda item: verify_identity(item, FakeWeb3(item))
    result = build_report(
        "testing", SHA, "b" * 40, policy=policy, fetch=fetch, verify=verify
    )
    assert result["overall_result"] == "pass" and result["backend_sha"] == SHA
    result = build_report(
        "testing",
        SHA,
        "b" * 40,
        release_sha="c" * 40,
        policy=policy,
        fetch=fetch,
        verify=verify,
    )
    assert result["overall_result"] == "blocked"


def test_missing_identity_cannot_be_hidden_by_healthy_api(policy):
    expected = policy["environments"]["testing"]
    live, ready = health(expected)
    result = build_report(
        "testing",
        SHA,
        SHA,
        policy=policy,
        fetch=lambda url, _: (200, live if url.endswith("/live") else ready),
        verify=lambda _: {"verified": False, "state": "deployment_evidence_missing"},
    )
    assert result["overall_result"] == "blocked"


def test_during_inspection_reorg_is_rejected(policy):
    expected = policy["environments"]["testing"]
    w3 = FakeWeb3(expected)
    calls = []

    def get_block(number):
        calls.append(number)
        return {"hash": b"z" * 32} if len(calls) > 2 else w3.blocks[number]

    w3.eth.get_block = get_block
    assert verify_identity(expected, w3)["state"] == "noncanonical_creation"
