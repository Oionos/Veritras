"""Admit the Docker build after CI, before Render replaces the running API."""

import os
from release_gate import build_production

if __name__ == "__main__":
    build_production(os.environ)
