"""Non-secret operational expectations, independent of application settings/secrets."""

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

POLICY_PATH = Path(__file__).with_name("environment_policy.json")
FIELDS = {
    "api_origin", "chain_id", "registry", "tracker", "registry_creation_tx",
    "tracker_creation_tx", "start_block", "confirmations", "indexer_mode",
}


def load_policy(path=POLICY_PATH):
    policy = json.loads(Path(path).read_text())
    if (set(policy) != {"version", "environments"} or type(policy["version"]) is not int
            or policy["version"] != 1
            or set(policy["environments"]) != {"production", "testing"}):
        raise ValueError("Invalid environment policy")
    for item in policy["environments"].values():
        origin = urlsplit(item.get("api_origin", ""))
        if (set(item) != FIELDS or origin.scheme != "https" or not origin.hostname
                or origin.username or origin.password or origin.query or origin.fragment
                or origin.path or origin.port not in (None, 443)
                or item["indexer_mode"] not in {"enabled", "disabled"}):
            raise ValueError("Invalid environment policy")
        for name in ("registry", "tracker"):
            if not re.fullmatch(r"0x[0-9a-fA-F]{40}", item[name]) or int(item[name], 16) == 0:
                raise ValueError("Invalid contract policy")
        if item["registry"].lower() == item["tracker"].lower():
            raise ValueError("Distinct contracts required")
        for name in ("registry_creation_tx", "tracker_creation_tx"):
            if item[name] is not None and not re.fullmatch(r"0x[0-9a-fA-F]{64}", item[name]):
                raise ValueError("Invalid transaction policy")
        for name, minimum, maximum in (("chain_id", 1, 2**63 - 1), ("confirmations", 0, 256)):
            if type(item[name]) is not int or not minimum <= item[name] <= maximum:
                raise ValueError("Invalid numeric policy")
        if item["start_block"] is not None and (
            type(item["start_block"]) is not int or item["start_block"] < 0
        ):
            raise ValueError("Invalid deployment anchor")
    return policy


def policy_digest(policy):
    return hashlib.sha256(json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def environment(name):
    return load_policy()["environments"][name]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=["production", "testing"], required=True)
    parser.add_argument("--field", choices=sorted(FIELDS), required=True)
    args = parser.parse_args()
    value = environment(args.environment)[args.field]
    if value is None:
        raise SystemExit("Policy field is not verified")
    print(value)


if __name__ == "__main__":
    main()
