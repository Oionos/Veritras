import json
import logging
import os
import sys
import re


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record to stdout.

    Only operational fields from an explicit allowlist become JSON fields.
    Exception messages and arbitrary extras are excluded.
    """

    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()

        log_obj: dict = {
            "time": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.message,
            "environment": os.environ.get("ENVIRONMENT", "development"),
            "release": (
                os.environ.get("RENDER_GIT_COMMIT")
                if re.fullmatch(
                    r"[0-9a-f]{40}", os.environ.get("RENDER_GIT_COMMIT", "")
                )
                else None
            ),
        }

        for key, val in record.__dict__.items():
            if key in {
                "method",
                "path",
                "status",
                "duration_ms",
                "request_id",
                "error_type",
                "reason",
                "last_processed_block",
                "target_head",
                "lag_blocks",
                "last_error",
            }:
                log_obj[key] = val

        if record.exc_info:
            log_obj["exc_info"] = (
                type(record.exc_info[1]).__name__ + " (details omitted)"
            )

        return json.dumps(log_obj, default=str)


class LazyStdoutHandler(logging.StreamHandler):
    """StreamHandler that resolves sys.stdout on every emit.

    The standard StreamHandler captures sys.stdout at construction time.
    This subclass always writes to whatever sys.stdout currently is, which
    ensures pytest's capfd/capsys capture works correctly even when the
    handler is constructed before the test's capture fixture activates.
    """

    def __init__(self):
        # Pass None so the parent doesn't lock in a stream reference.
        super().__init__(stream=None)

    @property
    def stream(self):  # type: ignore[override]
        return sys.stdout

    @stream.setter
    def stream(self, value):
        # Parent __init__ calls self.stream = stream; ignore that assignment.
        pass


_log_level = os.environ.get("LOG_LEVEL", "INFO").upper()

LOGGING_CONFIG: dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "app.core.logging.JsonFormatter",
            "datefmt": "%Y-%m-%dT%H:%M:%S",
        },
    },
    "handlers": {
        "stdout": {
            "()": "app.core.logging.LazyStdoutHandler",
            "formatter": "json",
        },
    },
    "loggers": {
        "veritras": {
            "handlers": ["stdout"],
            "level": _log_level,
            "propagate": True,  # allow caplog (root-attached) to capture in tests
        },
        "uvicorn.access": {
            # Suppress uvicorn's duplicate access logs — we emit our own in log_requests.
            "handlers": [],
            "level": "WARNING",
            "propagate": False,
        },
    },
    "root": {
        "handlers": [],  # no root handler — avoids duplicate output; caplog attaches here
        "level": "WARNING",
    },
}
