"""Small, standard-library structured logging configuration."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from app import config
from app.request_context import request_id_var


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


class KeyValueFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds")
        message = json.dumps(record.getMessage(), ensure_ascii=True)
        line = (
            f"ts={timestamp} level={record.levelname} logger={record.name} "
            f"request_id={getattr(record, 'request_id', '-')} message={message}"
        )
        return line


def configure_logging() -> None:
    """Configure one root stream handler; repeated calls do not duplicate it."""
    root = logging.getLogger()
    try:
        level = getattr(logging, config.LOG_LEVEL.strip().upper())
    except AttributeError:
        level = logging.INFO
    if not isinstance(level, int):
        level = logging.INFO
    root.setLevel(level)
    # Third-party access logs may include query strings with personal data.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").disabled = True
    for logger_filter in root.filters:
        if getattr(logger_filter, "_handover_request_id_filter", False):
            break
    else:
        logger_filter = RequestIdFilter()
        logger_filter._handover_request_id_filter = True
        root.addFilter(logger_filter)
    for existing in root.handlers:
        if not any(getattr(item, "_handover_request_id_filter", False) for item in existing.filters):
            handler_filter = RequestIdFilter()
            handler_filter._handover_request_id_filter = True
            existing.addFilter(handler_filter)
    handlers = [handler for handler in root.handlers if getattr(handler, "_handover_handler", False)]
    for handler in handlers[1:]:
        root.removeHandler(handler)
        handler.close()
    if handlers:
        handler = handlers[0]
    else:
        handler = logging.StreamHandler()
        handler._handover_handler = True
        handler.addFilter(RequestIdFilter())
        handler.setFormatter(KeyValueFormatter())
        root.addHandler(handler)
