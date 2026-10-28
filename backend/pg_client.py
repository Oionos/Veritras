"""Official matching PostgreSQL clients for an isolated GitHub runner.

Wrapper receives only libpq environment variables, never a credentialed CLI URI.
Uses Docker's ordinary network; no host network or proxy bypass configuration.
"""

import os
from pathlib import Path
import re
import subprocess
import sys


def command(tool, arguments, environment):
    image = environment.get("PG_CLIENT_IMAGE", "")
    if tool not in {"pg_dump", "pg_restore"} or not re.fullmatch(
        r"postgres:(16|17|18)-bookworm", image
    ):
        raise ValueError("Invalid PostgreSQL client selection")
    if tool == "pg_dump":
        paths = [
            value.removeprefix("--file=")
            for value in arguments
            if value.startswith("--file=")
        ]
    else:
        paths = [arguments[-1]] if arguments else []
    if len(paths) != 1 or not Path(paths[0]).is_absolute():
        raise ValueError("Explicit private archive path required")
    directory = Path(paths[0]).parent
    if (
        directory.is_symlink()
        or not directory.is_dir()
        or directory.stat().st_mode & 0o077
    ):
        raise ValueError("Private archive directory required")
    if any(character in str(directory) for character in (",", "\n", "\r")):
        raise ValueError("Invalid private archive path")
    mount = f"type=bind,src={directory},dst={directory}" + (
        ",readonly" if tool == "pg_restore" else ""
    )
    result = [
        "docker",
        "--host=unix:///var/run/docker.sock",
        "run",
        "--rm",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--mount",
        mount,
    ]
    if environment.get("PGSSLROOTCERT"):
        ca = "/etc/ssl/certs/ca-certificates.crt"
        if environment["PGSSLROOTCERT"] != ca:
            raise ValueError("Reviewed public CA bundle required")
        result += ["--mount", f"type=bind,src={ca},dst={ca},readonly"]
    for name in (
        "PGHOST",
        "PGPORT",
        "PGDATABASE",
        "PGUSER",
        "PGPASSWORD",
        "PGCONNECT_TIMEOUT",
        "PGOPTIONS",
        "PGSSLMODE",
        "PGSSLROOTCERT",
        "PGCHANNELBINDING",
    ):
        if name in environment:
            result.extend(["--env", name])
    return result + [image, tool, *arguments]


if __name__ == "__main__":
    try:
        result = subprocess.run(
            command(sys.argv[1], sys.argv[2:], os.environ), check=False
        )
        raise SystemExit(result.returncode)
    except Exception:
        raise SystemExit(1)
