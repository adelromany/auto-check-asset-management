"""Shared harness for the UI click-through tests.

The harness starts the real app (uvicorn subprocess) on a temporary SQLite
database with ``SSO_ENABLED=false``, seeds one handover case and one
maintenance case through the API (``TEST-`` serials only) and hands the base
URL plus the seeded ids to the tests.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Portal:
    """Handle on the running portal: base URL, ids, and tiny API helpers."""

    def __init__(self, base: str):
        self.base = base
        self.handover_id: str | None = None
        self.maintenance_id: str | None = None
        self.click_handover_id: str | None = None
        self.click_maintenance_id: str | None = None

    def api(self, method: str, path: str, payload: dict | None = None) -> dict:
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read()
        return json.loads(body) if body else {}


@pytest.fixture(scope="module")
def portal():
    db_dir = tempfile.mkdtemp(prefix="clickthrough-")
    db_path = Path(db_dir) / "portal.db"
    port = _free_port()
    log_path = Path(db_dir) / "uvicorn.log"

    environment = dict(os.environ)
    environment.update(
        DATABASE_URL=f"sqlite+aiosqlite:///{db_path.as_posix()}",
        SSO_ENABLED="false",
        SESSION_SECRET="clickthrough-test",
        HTTPS_ONLY="false",
        APP_HOST=f"http://127.0.0.1:{port}",
        SNIPEIT_URL="http://127.0.0.1:9",
        SNIPEIT_TOKEN="",
        SNIPEIT_TIMEOUT_SECONDS="1",
        DOCUMENTS_DIR=str(Path(db_dir) / "documents"),
    )
    # The app relies on migrations; create the schema in the temp database.
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        env=environment,
        check=True,
        capture_output=True,
    )

    server_log = log_path.open("wb")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=REPO_ROOT,
        env=environment,
        stdout=server_log,
        stderr=subprocess.STDOUT,
    )

    portal_handle = Portal(f"http://127.0.0.1:{port}")
    try:
        for _ in range(80):
            try:
                with urllib.request.urlopen(
                    portal_handle.base + "/api/health", timeout=2
                ) as response:
                    if response.status == 200:
                        break
            except Exception:
                time.sleep(0.25)
        else:
            stderr = b""
            if process.stderr is not None:
                try:
                    stderr = process.stderr.read(4000)
                except Exception:
                    pass
            raise RuntimeError(
                "click-through portal did not start: "
                + stderr.decode("utf-8", errors="replace")
            )

        # Seed through the API, TEST- serials only.
        handover = portal_handle.api(
            "POST", "/api/handovers",
            {"device_serial": "TEST-H1", "kind": "handover", "ticket_ref": "TICK-H1"},
        )
        maintenance = portal_handle.api(
            "POST", "/api/handovers",
            {"device_serial": "TEST-M1", "kind": "maintenance",
             "ticket_ref": "TICK-M1"},
        )
        click_handover = portal_handle.api(
            "POST", "/api/handovers",
            {"device_serial": "TEST-C1", "kind": "handover"},
        )
        click_maintenance = portal_handle.api(
            "POST", "/api/handovers",
            {"device_serial": "TEST-C2", "kind": "maintenance"},
        )
        portal_handle.handover_id = handover["id"]
        portal_handle.maintenance_id = maintenance["id"]
        portal_handle.click_handover_id = click_handover["id"]
        portal_handle.click_maintenance_id = click_maintenance["id"]

        yield portal_handle
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        server_log.close()
