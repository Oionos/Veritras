"""Check (default), or explicitly regenerate, policy copies in hosting roots."""

import argparse
from pathlib import Path
from environment_policy import load_policy


def sync(*, write=False):
    root = Path(__file__).resolve().parent.parent
    source = root / "release/environment-policy.json"
    load_policy(source)
    content = source.read_bytes()
    copies = [root / directory / "environment_policy.json" for directory in ("backend", "frontend")]
    if write:
        for path in copies:
            path.write_bytes(content)
    return all(path.exists() and path.read_bytes() == content for path in copies)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if not sync(write=args.write):
        raise SystemExit("Environment policy copies differ; run python backend/sync_environment_policy.py --write")
