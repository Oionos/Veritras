"""Start the isolated local API using only a validated Hardhat manifest."""

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


def main():
    if os.environ.get("ENVIRONMENT") != "testing":
        raise RuntimeError("The testing entrypoint requires ENVIRONMENT=testing")
    manifest = json.loads(Path(os.environ["DEPLOYMENT_MANIFEST"]).read_text())
    if int(manifest["chainId"]) != 31337:
        raise RuntimeError("Local testing requires the isolated Hardhat chain")
    # Some runtimes inject lowercase no_proxy, which requests prefers over the
    # uppercase form. Preserve existing entries and add only local service hosts.
    for key in ("NO_PROXY", "no_proxy"):
        entries = set(filter(None, os.environ.get(key, "").split(",")))
        entries.update({"localhost", "127.0.0.1", urlparse(os.environ["SEPOLIA_RPC_URL"]).hostname})
        os.environ[key] = ",".join(sorted(entry for entry in entries if entry))
    os.environ["PRODUCT_REGISTRY_CONTRACT"] = manifest["contracts"]["ProductRegistry"]
    os.environ["SHIPMENT_TRACKER_CONTRACT"] = manifest["contracts"]["ShipmentTracker"]
    os.environ["INDEXER_START_BLOCK"] = str(manifest["startBlock"] - 1)
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    os.execvp("uvicorn", ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"])


if __name__ == "__main__":
    main()
