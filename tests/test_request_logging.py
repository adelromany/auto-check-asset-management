"""Request ids, generic error response, and idempotent logging setup."""

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.logging_config import configure_logging
from app.main import _internal_error
from app.middleware.request_id import RequestIdMiddleware


def _app():
    application = FastAPI()
    application.add_exception_handler(Exception, _internal_error)
    application.add_middleware(RequestIdMiddleware)

    @application.get("/log")
    async def log_request():
        logging.getLogger("request-test").info("request marker")
        return {"ok": True}

    @application.get("/fail")
    async def fail_request():
        raise RuntimeError("private traceback detail")

    return application


def test_request_ids_are_fresh_and_client_supplied_values_are_ignored(caplog):
    configure_logging()
    caplog.set_level(logging.INFO)
    with TestClient(_app(), raise_server_exceptions=False) as client:
        first = client.get("/log", headers={"X-Request-ID": "client-value"})
        second = client.get("/log")

    first_id = first.headers["X-Request-ID"]
    second_id = second.headers["X-Request-ID"]
    assert first_id != second_id
    assert first_id != "client-value"
    marker_records = [record for record in caplog.records if record.name == "request-test"]
    assert len(marker_records) == 2
    assert {record.request_id for record in marker_records} == {first_id, second_id}


def test_generic_500_contains_request_id_and_logs_no_exception_text(monkeypatch):
    configure_logging()
    logger = logging.getLogger("app.middleware.request_id")
    emitted = []
    original_error = logger.error

    def capture_error(message, *args, **kwargs):
        emitted.append(message % args if args else message)
        original_error(message, *args, **kwargs)

    monkeypatch.setattr(logger, "error", capture_error)
    with TestClient(_app(), raise_server_exceptions=False) as client:
        response = client.get("/fail")

    assert response.status_code == 500
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert "private traceback detail" not in response.text
    assert "Traceback" not in response.text
    assert emitted == ["unhandled_request_error exception_type=RuntimeError"]
    assert all("private traceback detail" not in item for item in emitted)


def test_configure_logging_twice_keeps_single_handover_handler():
    configure_logging()
    configure_logging()
    count = sum(
        1 for handler in logging.getLogger().handlers
        if getattr(handler, "_handover_handler", False)
    )
    assert count == 1
    assert logging.getLogger("httpx").level >= logging.WARNING
    assert logging.getLogger("uvicorn.access").disabled
