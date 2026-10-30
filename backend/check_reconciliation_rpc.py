"""Read-only probe of the first historical event batch. No database or wallet."""

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from check_deployment_identity import rpc_failure, verify_identity
from environment_policy import environment

SOURCES = (
    ("registry", "ProductRegistry", ("ProductRegistered", "ProductMetadataUpdated")),
    ("tracker", "ShipmentTracker", ("CheckpointRecorded", "CustodyTransferred", "DeliveryCompleted")),
)


def inspect_history(policy, w3, *, verify=verify_identity):
    report = {"report_type": "read_only_historical_log_probe", "overall_result": "blocked",
              "authorizes_activation": False, "full_recovery_verified": False}
    identity = verify(policy, w3)
    if not identity["verified"]:
        return {**report, "state": "deployment_identity_not_verified", "deployment_identity": identity}
    stage = "chain_head"
    try:
        start = policy["start_block"] + 1
        end = min(w3.eth.block_number - policy["confirmations"], start + 999)
        if end < start:
            return {**report, "state": "confirmed_history_unavailable"}
        report.update(from_block=start, to_block=end)
        stage = "history_header"
        initial_hash = w3.eth.get_block(end)["hash"]
        counts = {}
        for scope, contract_name, names in SOURCES:
            abi = json.loads((Path(__file__).parent / "app" / "abi" / (contract_name + ".json")).read_text(encoding="utf-8-sig"))
            contract = w3.eth.contract(address=w3.to_checksum_address(policy[scope]), abi=abi)
            for name in names:
                stage = name
                logs = getattr(contract.events, name)().get_logs(from_block=start, to_block=end)
                if any(not start <= log["blockNumber"] <= end for log in logs):
                    return {**report, "state": "out_of_range_log_response", "rpc_stage": name}
                counts[name] = len(logs)
        stage = "history_header_recheck"
        if w3.eth.get_block(end)["hash"] != initial_hash:
            return {**report, "state": "canonical_target_mismatch"}
        return {**report, "state": "historical_log_probe_completed", "overall_result": "pass", "event_counts": counts}
    except Exception as error:
        details = rpc_failure(error)
        return {**report, "state": "historical_log_rpc_failed", "rpc_stage": stage,
                "rpc_method": "eth_getLogs" if stage in {name for _, _, names in SOURCES for name in names} else "eth_getBlockByNumber" if stage.startswith("history_header") else "eth_blockNumber",
                **{key: value for key, value in details.items() if key not in {"state", "verified"}}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=["testing", "production"], required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        policy = environment(args.environment)
        rpc_url = os.environ.get("SEPOLIA_RPC_URL", "")
        parsed = urlsplit(rpc_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.fragment:
            raise ValueError("Invalid endpoint")
        from web3 import Web3
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}, exception_retry_configuration=None))
        report = inspect_history(policy, w3)
    except Exception:
        report = {"overall_result": "blocked", "state": "invalid_probe_configuration",
                  "authorizes_activation": False, "full_recovery_verified": False}
    content = json.dumps(report, sort_keys=True, indent=2) + "\n"
    args.output.write_text(content)
    print(content, end="")
    return 0 if report["overall_result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
