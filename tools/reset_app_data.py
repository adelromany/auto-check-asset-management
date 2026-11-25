"""Delete every record the portal created so testing starts from zero.

Default is a dry run: it prints what would be deleted and deletes nothing.
It never touches Snipe-IT, the migrations table or the reference lists
(diagnosis reasons, vendors) unless asked.

Usage::

    python tools/reset_app_data.py                # dry run
    python tools/reset_app_data.py --yes          # backup, then delete
    python tools/reset_app_data.py --yes --vendors
    python tools/reset_app_data.py --yes --demo-only
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import config  # noqa: E402

# Dependency order: children first, parents last.
CHILD_TABLES = (
    "handover_stages",
    "events",
    "documents",
    "agent_reports",
    "maintenance_info",
)
CASE_TABLES = (*CHILD_TABLES, "handovers")
VENDOR_TABLE = "maintenance_destinations"
KEEP_TABLES = ("alembic_version", "diagnosis_categories")
DEMO_PREFIX = "DEMO-%"


class ResetRefused(RuntimeError):
    """Raised when a safety rule stops the reset."""


def _database_file(url: str) -> Path | None:
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite" or not parsed.database:
        return None
    if parsed.database == ":memory:":
        return None
    path = Path(parsed.database)
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def _database_label(url: str) -> str:
    """A readable label: the file path for SQLite, the URL otherwise."""
    path = _database_file(url)
    if path is not None:
        return str(path)
    return make_url(url).render_as_string(hide_password=True)


def _safe_documents_dir(path: str | Path, project_root: Path) -> Path:
    resolved = Path(path).resolve()
    root = project_root.resolve()
    if resolved != root and root not in resolved.parents:
        raise ResetRefused(
            f"Refusing to delete files outside the project: {resolved}"
        )
    return resolved


def _backup_database(url: str) -> Path | None:
    source = _database_file(url)
    if source is None:
        return None
    if not source.is_file():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = source.parent / f"backup-{stamp}.db"
    shutil.copy2(source, target)
    return target


async def _table_count(connection, table: str) -> int:
    try:
        value = await connection.scalar(text(f'SELECT COUNT(*) FROM "{table}"'))
        return int(value or 0)
    except Exception:
        return 0


async def _case_ids(connection, demo_only: bool) -> list:
    if demo_only:
        result = await connection.execute(
            text("SELECT id FROM handovers WHERE device_serial LIKE :prefix"),
            {"prefix": DEMO_PREFIX},
        )
        return [row[0] for row in result.all()]
    result = await connection.execute(text("SELECT id FROM handovers"))
    return [row[0] for row in result.all()]


async def _delete_cases(connection, demo_only: bool) -> None:
    ids = await _case_ids(connection, demo_only)
    if not ids:
        return
    placeholders = ", ".join(f":id{index}" for index in range(len(ids)))
    params = {f"id{index}": value for index, value in enumerate(ids)}
    for table in CHILD_TABLES:
        await connection.execute(
            text(f'DELETE FROM "{table}" WHERE handover_id IN ({placeholders})'),
            params,
        )
    await connection.execute(
        text(f'DELETE FROM "handovers" WHERE id IN ({placeholders})'),
        params,
    )


async def _delete_all_cases(connection) -> None:
    for table in CASE_TABLES:
        await connection.execute(text(f'DELETE FROM "{table}"'))


def _remove_document_files(documents_dir: Path) -> int:
    removed = 0
    if not documents_dir.is_dir():
        return removed
    for child in documents_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)
        removed += 1
    return removed


async def reset_app_data(
    *,
    database_url: str | None = None,
    documents_dir: str | Path | None = None,
    apply: bool = False,
    vendors: bool = False,
    demo_only: bool = False,
    project_root: Path | None = None,
    app_env: str | None = None,
    allow_production: bool = False,
    make_backup: bool = True,
) -> dict:
    """Return the before/after counts; delete only when ``apply`` is true."""
    url = database_url or config.DATABASE_URL
    docs = Path(documents_dir or config.DOCUMENTS_DIR)
    root = project_root or PROJECT_ROOT
    environment = (app_env or os.getenv("APP_ENV", "development")).strip().lower()
    if environment == "production" and not allow_production:
        raise ResetRefused(
            "APP_ENV=production; pass --i-know-this-is-production to continue."
        )
    documents = _safe_documents_dir(docs, root)
    is_postgres = make_url(url).get_backend_name() != "sqlite"
    if apply and is_postgres and make_backup:
        raise ResetRefused(
            "PostgreSQL backup is manual; pass --no-backup to continue."
        )

    engine = create_async_engine(url)
    before: dict[str, int] = {}
    after: dict[str, int] = {}
    backup: Path | None = None
    files_before = (
        len([child for child in documents.iterdir()])
        if documents.is_dir()
        else 0
    )
    files_removed = 0
    try:
        async with engine.begin() as connection:
            for table in (*CASE_TABLES, VENDOR_TABLE, *KEEP_TABLES):
                before[table] = await _table_count(connection, table)
            if apply:
                if make_backup:
                    backup = _backup_database(url)
                if demo_only:
                    await _delete_cases(connection, demo_only=True)
                else:
                    await _delete_all_cases(connection)
                    if vendors:
                        await connection.execute(
                            text(f'DELETE FROM "{VENDOR_TABLE}"')
                        )
            for table in (*CASE_TABLES, VENDOR_TABLE, *KEEP_TABLES):
                after[table] = await _table_count(connection, table)
    finally:
        await engine.dispose()

    if apply:
        files_removed = _remove_document_files(documents)
    return {
        "database": url,
        "database_label": _database_label(url),
        "documents_dir": str(documents),
        "applied": apply,
        "demo_only": demo_only,
        "vendors_cleared": vendors and apply and not demo_only,
        "before": before,
        "after": after,
        "files_before": files_before,
        "files_removed": files_removed,
        "backup": str(backup) if backup else None,
    }


def _print_report(result: dict) -> None:
    mode = "DELETE" if result["applied"] else "DRY RUN"
    print(f"Reset app data ({mode})")
    print(f"Database: {result['database_label']}")
    print("Table counts:")
    for table, count in result["before"].items():
        kept = " (kept)" if table in KEEP_TABLES else ""
        after = result["after"][table]
        print(f"  {table}: {count} -> {after}{kept}")
    print(
        f"Documents: {result['documents_dir']} "
        f"({result['files_before']} files, {result['files_removed']} removed)"
    )
    if result["backup"]:
        print(f"Backup: {result['backup']}")
    if not result["applied"]:
        print("Nothing was deleted. Re-run with --yes to apply.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="delete after the backup")
    parser.add_argument(
        "--vendors", action="store_true", help="also clear maintenance vendors"
    )
    parser.add_argument(
        "--demo-only", action="store_true", help="only DEMO- rows"
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="skip the backup (required for PostgreSQL)",
    )
    parser.add_argument(
        "--i-know-this-is-production",
        action="store_true",
        help="allow APP_ENV=production",
    )
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(
            reset_app_data(
                apply=args.yes,
                vendors=args.vendors,
                demo_only=args.demo_only,
                allow_production=args.i_know_this_is_production,
                make_backup=not args.no_backup,
            )
        )
    except ResetRefused as exc:
        print(f"Refused: {exc}")
        return 2
    _print_report(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
