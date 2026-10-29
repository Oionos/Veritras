"""Read-only canonical deployment verification. No wallet or database access."""

import argparse
import json
import os
from urllib.parse import urlsplit

from environment_policy import environment


class IdentityMismatch(Exception):
    """Public fixed diagnostic only; never include provider exception strings."""


RPC_STAGES = {
    "configuration", "provider_initialization", "chain_id", "chain_head",
    "registry_creation_receipt", "tracker_creation_receipt",
    "registry_creation_block", "tracker_creation_block",
    "registry_code", "tracker_code", "tracker_registry",
    "registry_creation_recheck", "tracker_creation_recheck",
}
RPC_FAILURES = {
    "TransactionNotFound": "receipt_not_found", "BlockNotFound": "block_not_found",
    "ExtraDataLengthError": "block_header_format", "BadFunctionCallOutput": "contract_call_failed",
    "JSONDecodeError": "response_not_json", "InvalidJSONError": "response_not_json",
    "ConnectTimeout": "timeout", "ReadTimeout": "timeout", "Timeout": "timeout",
    "ConnectionError": "connection_failed", "HTTPError": "http_error",
    "ProxyError": "connection_failed", "SSLError": "tls_verification_failed",
    "Web3RPCError": "rpc_response_error", "BadResponseFormat": "response_invalid",
    "Web3ValueError": "response_invalid", "Web3TypeError": "response_invalid",
    "Web3ValidationError": "response_invalid", "MethodUnavailable": "method_unavailable",
    "ImportError": "client_dependency_unavailable", "ModuleNotFoundError": "client_dependency_unavailable",
    "KeyError": "response_invalid", "AttributeError": "response_invalid", "TypeError": "response_invalid",
    "InvalidURL": "configuration_invalid", "MissingSchema": "configuration_invalid",
    "InvalidSchema": "configuration_invalid",
}


def rpc_failure(error, stage=None):
    result = {"verified": False, "state": "rpc_invalid_or_unavailable"}
    result["rpc_failure_kind"] = RPC_FAILURES.get(type(error).__name__, "client_error")
    if isinstance(stage, str) and stage in RPC_STAGES:
        result["rpc_stage"] = stage
    status = getattr(getattr(error, "response", None), "status_code", None)
    if type(status) is int and 100 <= status <= 599:
        result["rpc_http_status"] = status
        result["rpc_failure_kind"] = "http_error"
    response = getattr(error, "rpc_response", None)
    detail = response.get("error") if isinstance(response, dict) else None
    code = detail.get("code") if isinstance(detail, dict) else None
    if type(code) is int and -32768 <= code <= 32767:
        result["rpc_error_code"] = code
        if "rpc_http_status" not in result:
            result["rpc_failure_kind"] = "rpc_response_error"
    return result


def verify_identity(policy, w3):
    if (policy["start_block"] is None or not policy["registry_creation_tx"]
            or not policy["tracker_creation_tx"]):
        return {"verified": False, "state": "deployment_evidence_missing"}
    stage = "chain_id"
    try:
        if w3.eth.chain_id != policy["chain_id"]:
            raise IdentityMismatch("chain_mismatch")
        stage = "chain_head"
        head = w3.eth.block_number
        receipts = []
        for name in ("registry", "tracker"):
            tx = policy[name + "_creation_tx"]
            stage = name + "_creation_receipt"
            receipt = w3.eth.get_transaction_receipt(tx)
            address = policy[name].lower()
            if (receipt["status"] != 1
                    or (receipt["contractAddress"] or "").lower() != address
                    or receipt["transactionHash"].hex().removeprefix("0x").lower() != tx[2:].lower()):
                raise IdentityMismatch("creation_receipt_mismatch")
            block_number = receipt["blockNumber"]
            if type(block_number) is not int or block_number < 1 or block_number > head - policy["confirmations"]:
                raise IdentityMismatch("creation_not_confirmed")
            stage = name + "_creation_block"
            block = w3.eth.get_block(block_number)
            if block["hash"] != receipt["blockHash"]:
                raise IdentityMismatch("noncanonical_creation")
            stage = name + "_code"
            if not w3.eth.get_code(w3.to_checksum_address(policy[name])):
                raise IdentityMismatch("contract_not_deployed")
            receipts.append({"contract": name, "address": policy[name], "transaction": tx,
                             "block": block_number, "block_hash": "0x" + block["hash"].hex().removeprefix("0x")})
        abi = [{"type": "function", "name": "productRegistry", "stateMutability": "view",
                "inputs": [], "outputs": [{"name": "", "type": "address"}]}]
        stage = "tracker_registry"
        linked = w3.eth.contract(address=w3.to_checksum_address(policy["tracker"]), abi=abi).functions.productRegistry().call()
        if linked.lower() != policy["registry"].lower():
            raise IdentityMismatch("tracker_registry_mismatch")
        anchor = min(item["block"] for item in receipts) - 1
        if anchor != policy["start_block"]:
            raise IdentityMismatch("deployment_anchor_mismatch")
        # Re-read inclusion headers after all calls; reject a fork during inspection.
        for receipt in receipts:
            stage = receipt["contract"] + "_creation_recheck"
            observed = "0x" + w3.eth.get_block(receipt["block"])["hash"].hex().removeprefix("0x")
            if observed != receipt["block_hash"]:
                raise IdentityMismatch("noncanonical_creation")
        return {"verified": True, "state": "verified", "chain_id": policy["chain_id"],
                "start_block": anchor, "confirmations": policy["confirmations"], "receipts": receipts}
    except IdentityMismatch as error:
        return {"verified": False, "state": str(error)}
    except Exception as error:
        return rpc_failure(error, stage)


def configured_verification(policy, rpc_url=None):
    if any(policy[field] is None for field in ("start_block", "registry_creation_tx", "tracker_creation_tx")):
        return {"verified": False, "state": "deployment_evidence_missing"}
    rpc_url = rpc_url if rpc_url is not None else os.environ.get("SEPOLIA_RPC_URL", "")
    if not rpc_url:
        return {"verified": False, "state": "rpc_not_configured"}
    try:
        parsed = urlsplit(rpc_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.fragment:
            raise ValueError("Invalid RPC configuration")
    except Exception:
        return {"verified": False, "state": "rpc_invalid_or_unavailable",
                "rpc_stage": "configuration", "rpc_failure_kind": "configuration_invalid"}
    try:
        from web3 import Web3
        return verify_identity(policy, Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10})))
    except Exception as error:
        return rpc_failure(error, "provider_initialization")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True, choices=["production", "testing"])
    args = parser.parse_args()
    try:
        result = configured_verification(environment(args.environment))
    except Exception:
        result = {"verified": False, "state": "invalid_policy"}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
