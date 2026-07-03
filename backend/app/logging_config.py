import json
import logging
import sys
from datetime import datetime, timezone

# Standard LogRecord attributes — anything else is treated as structured context
# added via logger.info("msg", extra={"key": "value"}).
_STANDARD_LOG_ATTRS = frozenset(
    {
        "args", "created", "exc_info", "exc_text", "filename", "funcName",
        "levelname", "levelno", "lineno", "message", "module", "msecs", "msg",
        "name", "pathname", "process", "processName", "relativeCreated",
        "stack_info", "taskName", "thread", "threadName",
    }
)


class JSONFormatter(logging.Formatter):
    """Emits one JSON object per log line. Suitable for log aggregators."""

    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()
        entry: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.message,
        }
        # Include any extra fields the caller injected via extra={}
        for key, value in record.__dict__.items():
            if key not in _STANDARD_LOG_ATTRS and not key.startswith("_"):
                entry[key] = value

        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(entry, default=str)


class ConsoleFormatter(logging.Formatter):
    """Coloured, human-readable output for local development."""

    _COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
    }
    _RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self._COLORS.get(record.levelname, "")
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        prefix = f"{color}{record.levelname:<8}{self._RESET} {ts}"
        msg = f"{prefix}  {record.name}: {record.getMessage()}"
        if record.exc_info:
            msg += "\n" + self.formatException(record.exc_info)
        return msg


def setup_logging(log_level: str = "INFO", log_format: str = "json") -> None:
    formatter: logging.Formatter = (
        ConsoleFormatter() if log_format == "console" else JSONFormatter()
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    # Configure the "app" namespace logger — all app code uses logging.getLogger("app.*")
    app_logger = logging.getLogger("app")
    app_logger.setLevel(log_level.upper())
    app_logger.handlers.clear()
    app_logger.addHandler(handler)
    app_logger.propagate = False

    # Security audit logger — separate from "app.*" so events can be routed
    # to a different sink (file, SIEM) without changing app log routing.
    audit_logger = logging.getLogger("security.audit")
    audit_logger.setLevel(logging.INFO)
    audit_logger.handlers.clear()
    audit_logger.addHandler(handler)
    audit_logger.propagate = False

    # Reduce noise from third-party libraries in the root logger
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
