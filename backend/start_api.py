"""Check the separately released schema before serving the API."""

import os

from manage_schema import require_current_schema

if __name__ == "__main__":
    require_current_schema()
    os.execvp(
        "uvicorn",
        [
            "uvicorn",
            "app.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            os.environ.get("PORT", "8000"),
        ],
    )
