"""Throw-away database checks for the v2 polish migrations."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _alembic(db: Path, revision: str) -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db.as_posix()}"
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        timeout=60,
    )


def _downgrade(db: Path, revision: str) -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db.as_posix()}"
    subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", revision],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        timeout=60,
    )


def _mode(db: Path) -> str:
    with sqlite3.connect(db) as connection:
        return connection.execute("SELECT recipient_mode FROM handovers").fetchone()[0]


def test_case_type_migration_round_trip(tmp_path: Path) -> None:
    db = tmp_path / "case-type.db"
    _alembic(db, "0012_vendor_contacts")
    with sqlite3.connect(db) as connection:
        connection.execute(
            "INSERT INTO handovers "
            "(id, kind, status, engineer_email, engineer_name, device_serial, "
            "recipient_mode, created_at, updated_at) "
            "VALUES (?, 'handover', 'draft', 'dev@example.com', '', 'TEST-SN-0001', "
            "'not_in_snipeit', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (uuid.uuid4().hex,),
        )
    _alembic(db, "0013_case_type")
    assert _mode(db) == "pending_user"
    _downgrade(db, "0012_vendor_contacts")
    assert _mode(db) == "not_in_snipeit"
    _alembic(db, "0013_case_type")
    assert _mode(db) == "pending_user"


def test_device_holder_migration_round_trip(tmp_path: Path) -> None:
    db = tmp_path / "device-holder.db"
    _alembic(db, "0013_case_type")
    _alembic(db, "0014_device_holder")
    with sqlite3.connect(db) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(handovers)")}
    assert {"device_holder_id", "device_holder_name"} <= columns
    _downgrade(db, "0013_case_type")
    with sqlite3.connect(db) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(handovers)")}
    assert "device_holder_id" not in columns
    _alembic(db, "0014_device_holder")
