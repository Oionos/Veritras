"""Migrate a versioned database before serving the API."""
import os

from manage_schema import migrate


if __name__ == "__main__":
    # An unversioned legacy schema fails closed until explicitly inspected and
    # adopted with manage_schema.py. No startup flag blindly stamps production.
    migrate(apply=True)
    os.execvp("uvicorn", ["uvicorn", "app.main:app", "--host", "0.0.0.0",
                          "--port", os.environ.get("PORT", "8000")])
