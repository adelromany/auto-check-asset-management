"""Builders for the device-handover diagrams.

Every fact in these diagrams is read from the application code: the stage
list, order and dependency table from ``app/domain/stages.py`` and the table
columns from the SQLAlchemy models.  Nothing here is copied from memory or
from the task prompt; the differences page shows where the prompt and the
code disagree.

The builders are deterministic: the same code produces byte-identical JSON.
"""

from __future__ import annotations

import html
from pathlib import Path

from .artifacts import REPO_ROOT
from .markdown import BLOB_BASE, source_sha256
from .principles import INDEX_CSS, INDEX_JS
from app.db.models.handover import (
    AgentReport,
    Document,
    Event,
    Handover,
    HandoverStage,
)
from app.domain.stages import (
    STAGE_DEPENDENCIES,
    STAGE_ORDER,
    HandoverStatus,
    Stage,
    StageStatus,
)

OUTPUT_DIR = "docs/visual/handover"

STAGE_LABELS: dict[Stage, str] = {
    Stage.DEVICE_PREPARED: "Device prepared",
    Stage.USER_SIGNED_IN: "User signed in",
    Stage.AGENT_REPORT: "Agent report",
    Stage.SOFTWARE_CHECK: "Software check",
    Stage.RECIPIENT_CHECK: "Recipient check",
    Stage.CHECKOUT: "Checkout",
    Stage.REPORT_PRINTED: "Report printed",
    Stage.USER_SIGNED: "Sheet signed",
    Stage.DOCUMENT_SCANNED: "Document scanned",
    Stage.DOCUMENT_PUSHED: "Document pushed",
}

STAGE_CHECKS: dict[Stage, str] = {
    Stage.DEVICE_PREPARED: "Device ready for handover",
    Stage.USER_SIGNED_IN: "Employee signs in",
    Stage.AGENT_REPORT: "Serial, CPU, RAM, disks",
    Stage.SOFTWARE_CHECK: "Software + Windows licence",
    Stage.RECIPIENT_CHECK: "Snipe-IT user confirmation",
    Stage.CHECKOUT: "Checkout + re-read asset",
    Stage.REPORT_PRINTED: "Printable report",
    Stage.USER_SIGNED: "Signed paper sheet",
    Stage.DOCUMENT_SCANNED: "PDF / PNG / JPEG upload",
    Stage.DOCUMENT_PUSHED: "Upload + re-read files",
}

STAGE_ACTORS: dict[Stage, str] = {
    Stage.DEVICE_PREPARED: "engineer",
    Stage.USER_SIGNED_IN: "employee",
    Stage.AGENT_REPORT: "employee",
    Stage.SOFTWARE_CHECK: "portal",
    Stage.RECIPIENT_CHECK: "engineer",
    Stage.CHECKOUT: "snipeit",
    Stage.REPORT_PRINTED: "engineer",
    Stage.USER_SIGNED: "employee",
    Stage.DOCUMENT_SCANNED: "portal",
    Stage.DOCUMENT_PUSHED: "snipeit",
}

# Columns are the six columns Archify's workflow schema allows.  The four
# evidence stages share the last two columns, each in its own actor lane, so
# the left-to-right order is preserved without stacking nodes on top of each
# other.
STAGE_COLUMNS: dict[Stage, int] = {
    Stage.DEVICE_PREPARED: 0,
    Stage.USER_SIGNED_IN: 1,
    Stage.AGENT_REPORT: 2,
    Stage.SOFTWARE_CHECK: 3,
    Stage.RECIPIENT_CHECK: 3,
    Stage.CHECKOUT: 4,
    Stage.REPORT_PRINTED: 4,
    Stage.USER_SIGNED: 5,
    Stage.DOCUMENT_SCANNED: 5,
    Stage.DOCUMENT_PUSHED: 5,
}


def _meta(title: str, slug: str, *, subtitle: str = "", **extra) -> dict:
    meta: dict = {
        "title": title,
        "output": f"{OUTPUT_DIR}/{slug}.html",
        "quality_profile": "showcase",
    }
    if subtitle:
        meta["subtitle"] = subtitle
    meta.update(extra)
    return meta


def build_workflow() -> dict:
    """All ten stages, their actors, checks and failure side paths."""
    nodes: list[dict] = []
    for stage in STAGE_ORDER:
        nodes.append(
            {
                "id": stage.value,
                "lane": STAGE_ACTORS[stage],
                "col": STAGE_COLUMNS[stage],
                "type": "security" if stage in {Stage.CHECKOUT, Stage.DOCUMENT_PUSHED} else "backend",
                "label": STAGE_LABELS[stage],
                "sublabel": STAGE_CHECKS[stage],
                "tag": f"{STAGE_ORDER.index(stage) + 1:02d}",
            }
        )

    failures = [
        {
            "id": "agent_report_missing",
            "lane": "failures_agent",
            "col": 2,
            "type": "security",
            "label": "Report missing",
            "sublabel": "No report submitted",
            "tag": "fail",
        },
        {
            "id": "serial_mismatch",
            "lane": "failures_agent",
            "col": 3,
            "type": "security",
            "label": "Serial mismatch",
            "sublabel": "Serial differs from case",
            "tag": "fail",
        },
        {
            "id": "software_missing",
            "lane": "failures_portal",
            "col": 3,
            "type": "security",
            "label": "Software missing",
            "sublabel": "Program absent / not activated",
            "tag": "fail",
        },
        {
            "id": "recipient_not_found",
            "lane": "failures_recipient",
            "col": 3,
            "type": "security",
            "label": "Recipient not found",
            "sublabel": "No Snipe-IT user match",
            "tag": "blocked",
        },
        {
            "id": "wrong_file_type",
            "lane": "failures_portal",
            "col": 5,
            "type": "security",
            "label": "Wrong file type",
            "sublabel": "PDF, PNG or JPEG only",
            "tag": "fail",
        },
        {
            "id": "checkout_mismatch",
            "lane": "failures_snipeit",
            "col": 4,
            "type": "security",
            "label": "Checkout not verified",
            "sublabel": "Asset assigned to someone else",
            "tag": "fail",
        },
        {
            "id": "push_unverified",
            "lane": "failures_snipeit",
            "col": 5,
            "type": "security",
            "label": "Push not verified",
            "sublabel": "Scan absent from asset files",
            "tag": "fail",
        },
    ]
    nodes.extend(failures)

    main = [stage.value for stage in STAGE_ORDER]
    edges: list[dict] = []
    for left, right in zip(main, main[1:]):
        edges.append(
            {
                "from": left,
                "to": right,
                "label": "next",
                "variant": "emphasis",
                "role": "main",
            }
        )

    # The dependency table is not a straight line: software_check and
    # recipient_check both depend on agent_report, and checkout waits for both.
    edges.extend(
        [
            {
                "from": Stage.AGENT_REPORT.value,
                "to": Stage.RECIPIENT_CHECK.value,
                "label": "dependency",
                "variant": "dashed",
                "role": "branch",
            },
            {
                "from": Stage.SOFTWARE_CHECK.value,
                "to": Stage.CHECKOUT.value,
                "label": "dependency",
                "variant": "dashed",
                "role": "branch",
            },
        ]
    )

    edges.extend(
        [
            {
                "from": Stage.AGENT_REPORT.value,
                "to": "agent_report_missing",
                "label": "no report",
                "variant": "security",
                "role": "error",
            },
            {
                "from": Stage.AGENT_REPORT.value,
                "to": "serial_mismatch",
                "label": "serial differs",
                "variant": "security",
                "role": "error",
            },
            {
                "from": Stage.SOFTWARE_CHECK.value,
                "to": "software_missing",
                "label": "missing",
                "variant": "security",
                "role": "error",
            },
            {
                "from": Stage.RECIPIENT_CHECK.value,
                "to": "recipient_not_found",
                "label": "not found",
                "variant": "security",
                "role": "error",
                "route": "drop",
                "fromSide": "bottom",
                "toSide": "top",
            },
            {
                "from": Stage.CHECKOUT.value,
                "to": "checkout_mismatch",
                "label": "not verified",
                "variant": "security",
                "role": "error",
            },
            {
                "from": Stage.DOCUMENT_SCANNED.value,
                "to": "wrong_file_type",
                "label": "rejected",
                "variant": "security",
                "role": "error",
            },
            {
                "from": Stage.DOCUMENT_PUSHED.value,
                "to": "push_unverified",
                "label": "not verified",
                "variant": "security",
                "role": "error",
            },
        ]
    )

    return {
        "schema_version": 2,
        "diagram_type": "workflow",
        "meta": _meta(
            "Device handover workflow",
            "workflow",
            subtitle="Ten fixed stages, the actor at each step, and the failure side paths",
        ),
        "lanes": [
            {"id": "engineer", "label": "Engineer"},
            {"id": "failures_recipient", "label": "Recipient exception", "variant": "exception"},
            {"id": "employee", "label": "Employee PC + agent"},
            {"id": "portal", "label": "Portal"},
            {"id": "snipeit", "label": "Snipe-IT"},
            {"id": "failures_agent", "label": "Agent failures", "variant": "exception"},
            {"id": "failures_portal", "label": "Portal failures", "variant": "exception"},
            {"id": "failures_snipeit", "label": "Snipe-IT failures", "variant": "exception"},
        ],
        "phases": [
            {"id": "prepare", "label": "Prepare", "fromCol": 0, "toCol": 1},
            {"id": "collect", "label": "Collect evidence", "fromCol": 2, "toCol": 3},
            {"id": "commit", "label": "Commit in Snipe-IT", "fromCol": 4, "toCol": 4, "variant": "emphasis"},
            {"id": "evidence", "label": "Signed evidence", "fromCol": 5, "toCol": 5, "variant": "dashed"},
        ],
        "mainPath": main,
        "nodes": nodes,
        "edges": edges,
        "cards": [
            {
                "dot": "cyan",
                "title": "Order is fixed",
                "items": [
                    "The ten stages and their dependency table come from app/domain/stages.py",
                    "A stage runs only when every dependency is passed or skipped",
                    "A skipped dependency is satisfied, not missing",
                ],
            },
            {
                "dot": "rose",
                "title": "Failures are visible",
                "items": [
                    "Agent, software, recipient, checkout and push failures are separate labeled nodes",
                    "A failed or blocked stage makes the case stalled",
                    "The same stage can be re-run after the cause is fixed",
                ],
            },
            {
                "dot": "emerald",
                "title": "One writer per fact",
                "items": [
                    "The engineer confirms the four manual stages",
                    "The portal records the agent report and verified Snipe-IT writes",
                    "Snipe-IT is re-read after every write before a stage passes",
                ],
            },
        ],
    }


def build_dependencies() -> dict:
    """The dependency DAG, edge for edge from ``STAGE_DEPENDENCIES``.

    This is deliberately separate from the workflow: the workflow follows the
    reader's happy path, while this diagram proves the dependency table.
    """
    columns = {
        Stage.DEVICE_PREPARED: 0,
        Stage.USER_SIGNED_IN: 1,
        Stage.AGENT_REPORT: 1,
        Stage.SOFTWARE_CHECK: 2,
        Stage.RECIPIENT_CHECK: 2,
        Stage.CHECKOUT: 3,
        Stage.REPORT_PRINTED: 3,
        Stage.USER_SIGNED: 4,
        Stage.DOCUMENT_SCANNED: 5,
        Stage.DOCUMENT_PUSHED: 5,
    }
    lanes = {
        Stage.DEVICE_PREPARED: "engineer",
        Stage.USER_SIGNED_IN: "employee",
        Stage.AGENT_REPORT: "agent",
        Stage.SOFTWARE_CHECK: "portal",
        Stage.RECIPIENT_CHECK: "engineer",
        Stage.CHECKOUT: "snipeit",
        Stage.REPORT_PRINTED: "engineer",
        Stage.USER_SIGNED: "employee",
        Stage.DOCUMENT_SCANNED: "portal",
        Stage.DOCUMENT_PUSHED: "snipeit",
    }
    nodes = [
        {
            "id": stage.value,
            "lane": lanes[stage],
            "col": columns[stage],
            "type": "security" if stage in {Stage.CHECKOUT, Stage.DOCUMENT_PUSHED} else "backend",
            "label": STAGE_LABELS[stage],
            "sublabel": f"depends on {len(STAGE_DEPENDENCIES[stage])} stage(s)",
            "tag": f"{STAGE_ORDER.index(stage) + 1:02d}",
        }
        for stage in STAGE_ORDER
    ]
    edges = [
        {
            "from": dependency.value,
            "to": stage.value,
            "label": "requires",
            "variant": "dashed",
            "role": "branch",
            "bias": 0.25 if stage is Stage.CHECKOUT else 0.75 if stage is Stage.USER_SIGNED else 0.5,
        }
        for stage in STAGE_ORDER
        for dependency in STAGE_DEPENDENCIES[stage]
    ]
    return {
        "schema_version": 2,
        "diagram_type": "workflow",
        "meta": _meta(
            "Handover stage dependencies",
            "dependencies",
            subtitle="Every edge is a row of STAGE_DEPENDENCIES; a stage runs only when all of them are passed or skipped",
        ),
        "lanes": [
            {"id": "engineer", "label": "Engineer"},
            {"id": "employee", "label": "Employee PC"},
            {"id": "agent", "label": "Agent"},
            {"id": "portal", "label": "Portal"},
            {"id": "snipeit", "label": "Snipe-IT"},
        ],
        "mainPath": [
            Stage.DEVICE_PREPARED.value,
            Stage.AGENT_REPORT.value,
            Stage.REPORT_PRINTED.value,
            Stage.USER_SIGNED.value,
            Stage.DOCUMENT_SCANNED.value,
            Stage.DOCUMENT_PUSHED.value,
        ],
        "nodes": nodes,
        "edges": edges,
        "cards": [
            {
                "dot": "cyan",
                "title": "Dependencies are one-directional",
                "items": [
                    "The table is a DAG with no cycles",
                    "A passed or skipped dependency is satisfied",
                    "A pending, failed or blocked dependency blocks the stage",
                ],
            },
            {
                "dot": "rose",
                "title": "Two joins",
                "items": [
                    "checkout waits for both recipient_check and software_check",
                    "software_check and recipient_check both wait for agent_report",
                ],
            },
        ],
    }


def build_sequence() -> dict:
    """Onboarding at the employee's PC, with the credential for each request."""
    messages = [
        ("engineer", "browser", 170, "Open the portal and sign in with Entra SSO", "emphasis"),
        ("browser", "portal", 210, "GET /login → /auth/callback (SSO)", "emphasis"),
        ("portal", "browser", 250, "Signed session cookie", "return"),
        ("browser", "portal", 290, "GET /api/session/new?handover_id=… (SSO)", "emphasis"),
        ("portal", "db", 330, "Store code hash bound to the handover", "emphasis"),
        ("portal", "browser", 370, "Code XXXX-XXXX-XXXX", "return"),
        ("engineer", "agent", 410, "Run the copied PowerShell command", "emphasis"),
        ("agent", "portal", 450, "GET /static/agent.ps1 (no SSO)", "dashed"),
        ("agent", "portal", 490, "POST /api/session/{code}/submit (code only)", "security"),
        ("portal", "db", 530, "Atomic waiting → submitted", "emphasis"),
        ("portal", "agent", 570, "200 ok / already_submitted", "return"),
        ("browser", "portal", 610, "Poll GET /api/session/{code}/data (SSO)", "emphasis"),
        ("portal", "browser", 650, "202 waiting, then 200 with the report", "return"),
        ("portal", "snipeit", 690, "Find the recipient in Snipe-IT (SSO)", "emphasis"),
        ("portal", "snipeit", 730, "Checkout the asset and re-read it (SSO)", "emphasis"),
        ("portal", "snipeit", 770, "Upload the signed sheet and re-read files (SSO)", "emphasis"),
        ("portal", "db", 810, "Stage transitions and audit events", "emphasis"),
        ("browser", "engineer", 850, "Print, sign, scan, upload and sign out", "return"),
    ]
    return {
        "schema_version": 1,
        "diagram_type": "sequence",
        "meta": _meta(
            "Onboarding sequence at the employee's PC",
            "sequence",
            subtitle="The engineer's SSO session and the agent's one-time code are different credentials",
            column_fit="spread",
        ),
        "participants": [
            {"id": "engineer", "type": "external", "label": "Engineer", "sublabel": "at the employee's PC"},
            {"id": "browser", "type": "frontend", "label": "Browser", "sublabel": "employee's PC"},
            {"id": "portal", "type": "backend", "label": "Handover Portal", "sublabel": "FastAPI"},
            {"id": "agent", "type": "external", "label": "PowerShell agent", "sublabel": "no browser cookie"},
            {"id": "snipeit", "type": "cloud", "label": "Snipe-IT", "sublabel": "asset system"},
            {"id": "db", "type": "database", "label": "Database", "sublabel": "handover state"},
        ],
        "segments": [
            {"from": 150, "to": 400, "label": "Create the one-time code (SSO)"},
            {"from": 400, "to": 600, "label": "Agent report (code only)"},
            {"from": 600, "to": 880, "label": "Confirm and record (SSO)"},
        ],
        "messages": [
            {
                "from": source,
                "to": target,
                "y": y,
                "label": label,
                "variant": variant,
            }
            for source, target, y, label, variant in messages
        ],
        "cards": [
            {
                "dot": "cyan",
                "title": "Two credentials",
                "items": [
                    "Every browser request carries the engineer's Entra SSO session",
                    "The agent has no cookie: the one-time code is its only credential",
                    "The engineer's identity never travels in the agent command or payload",
                ],
            },
            {
                "dot": "emerald",
                "title": "One report, one handover",
                "items": [
                    "The session is bound to the handover when the code is created",
                    "The atomic submit moves waiting to submitted exactly once",
                    "The report is redacted before it is stored as evidence",
                ],
            },
            {
                "dot": "rose",
                "title": "Verified writes",
                "items": [
                    "Checkout is followed by a re-read of the asset",
                    "The uploaded scan is followed by a re-read of the file list",
                    "A write that cannot be verified fails the stage",
                ],
            },
        ],
    }


def build_lifecycle() -> dict:
    """The five case statuses and the rules that move between them."""
    states = [
        {"id": "draft", "type": "start", "label": "Draft", "sublabel": "no stage acted on", "tag": "entry", "step": "01"},
        {"id": "in_progress", "type": "active", "label": "In progress", "sublabel": "work has started", "tag": "open", "step": "02"},
        {"id": "stalled", "type": "waiting", "label": "Stalled", "sublabel": "a stage failed, blocked, or went stale", "tag": "attention", "step": "03"},
        {"id": "completed", "type": "success", "label": "Completed", "sublabel": "all ten stages passed or skipped", "tag": "closed", "step": "04"},
        {"id": "cancelled", "type": "failure", "label": "Cancelled", "sublabel": "explicit, never derived over", "tag": "terminal"},
    ]
    transitions = [
        {"id": "draft-progress", "from": "draft", "to": "in_progress", "label": "first stage acted on"},
        {"id": "draft-stalled", "from": "draft", "to": "stalled", "label": "first action fails"},
        {"id": "progress-stalled", "from": "in_progress", "to": "stalled", "label": "a stage failed or blocked", "variant": "security"},
        {"id": "progress-stale", "from": "in_progress", "to": "stalled", "label": "no update for STALL_HOURS", "variant": "dashed"},
        {"id": "stalled-progress", "from": "stalled", "to": "in_progress", "label": "re-run succeeds, no failure remains"},
        {"id": "progress-complete", "from": "in_progress", "to": "completed", "label": "all stages passed or skipped"},
        {"id": "stalled-complete", "from": "stalled", "to": "completed", "label": "all stages passed or skipped"},
        {"id": "draft-cancel", "from": "draft", "to": "cancelled", "label": "engineer cancels", "variant": "security"},
        {"id": "progress-cancel", "from": "in_progress", "to": "cancelled", "label": "engineer cancels", "variant": "security"},
        {"id": "stalled-cancel", "from": "stalled", "to": "cancelled", "label": "engineer cancels", "variant": "security"},
    ]
    return {
        "schema_version": 3,
        "diagram_type": "lifecycle",
        "meta": _meta(
            "Handover case lifecycle",
            "lifecycle",
            subtitle="Case status is derived from the stage states; cancellation is explicit",
        ),
        "mainPath": ["draft", "in_progress", "stalled", "completed"],
        "states": states,
        "transitions": transitions,
        "cards": [
            {
                "dot": "cyan",
                "title": "One status writer",
                "items": [
                    "HandoverService.recompute_status is the only writer",
                    "Cancelled wins before every other rule",
                    "Completed needs all ten stages passed or skipped",
                ],
            },
            {
                "dot": "amber",
                "title": "Stalled has two causes",
                "items": [
                    "Any failed or blocked stage",
                    "No update for STALL_HOURS (configurable, zero disables it)",
                ],
            },
        ],
    }


def build_stage_lifecycle() -> dict:
    """The five stage statuses, including the software override."""
    states = [
        {"id": "pending", "type": "waiting", "label": "Pending", "sublabel": "no result yet", "tag": "entry", "step": "01"},
        {"id": "passed", "type": "success", "label": "Passed", "sublabel": "confirmed or verified", "tag": "satisfied", "step": "02"},
        {"id": "failed", "type": "failure", "label": "Failed", "sublabel": "a check returned a problem", "tag": "retryable", "step": "03"},
        {"id": "blocked", "type": "waiting", "label": "Blocked", "sublabel": "recipient identity unknown", "tag": "needs input", "step": "04"},
        {"id": "skipped", "type": "neutral", "label": "Skipped (overridden)", "sublabel": "software override with a reason", "tag": "satisfied", "step": "05"},
    ]
    transitions = [
        {"id": "pending-passed", "from": "pending", "to": "passed", "label": "manual confirm or verified check"},
        {"id": "pending-failed", "from": "pending", "to": "failed", "label": "check fails", "variant": "security"},
        {"id": "pending-blocked", "from": "pending", "to": "blocked", "label": "no domain user detected", "variant": "security"},
        {"id": "failed-skipped", "from": "failed", "to": "skipped", "label": "engineer overrides software", "variant": "security"},
        {"id": "failed-pending", "from": "failed", "to": "pending", "label": "re-run after a fix", "variant": "dashed"},
        {"id": "blocked-pending", "from": "blocked", "to": "pending", "label": "search manually or new report", "variant": "dashed"},
        {"id": "skipped-pending", "from": "skipped", "to": "pending", "label": "re-evaluate software", "variant": "dashed"},
    ]
    return {
        "schema_version": 3,
        "diagram_type": "lifecycle",
        "meta": _meta(
            "Handover stage lifecycle",
            "stage-lifecycle",
            subtitle="Pending, passed, failed, blocked and skipped (the software override)",
        ),
        "mainPath": ["pending", "passed"],
        "states": states,
        "transitions": transitions,
        "cards": [
            {
                "dot": "emerald",
                "title": "Satisfied means passed or skipped",
                "items": [
                    "A skipped stage completes the case and satisfies dependents",
                    "It is never listed as a missing step",
                    "Only the software check can be overridden",
                ],
            },
            {
                "dot": "rose",
                "title": "Blocked is not failed",
                "items": [
                    "Blocked means the recipient cannot be determined",
                    "The engineer can search manually and continue",
                    "Failed means a check ran and returned a problem",
                ],
            },
        ],
    }


def _type_name(column) -> str:
    name = type(column.type).__name__.lower()
    if name == "uuid":
        return "uuid"
    if name == "string":
        length = getattr(column.type, "length", None)
        return f"varchar({length})" if length else "varchar"
    if name == "text":
        return "text"
    if name == "integer":
        return "integer"
    if name == "datetime":
        return "timestamptz" if getattr(column.type, "timezone", False) else "timestamp"
    if name in {"json", "jsonb"}:
        return "jsonb" if name == "jsonb" else "json"
    return name


def _entity(model, *, row: int, col: int, tag: str, width: int = 300) -> dict:
    attributes = []
    for column in model.__table__.columns:
        keys: list[str] = []
        if column.primary_key:
            keys.append("pk")
        if column.foreign_keys:
            keys.append("fk")
        if column.unique:
            keys.append("uk")
        item: dict = {"name": column.name, "type": _type_name(column)}
        if keys:
            item["key"] = keys[0] if len(keys) == 1 else keys
        if column.foreign_keys:
            target = next(iter(column.foreign_keys)).target_fullname
            item["references"] = target
        attributes.append(item)
    return {
        "id": model.__tablename__,
        "label": model.__tablename__,
        "tag": tag,
        "row": row,
        "col": col,
        "width": width,
        "attributes": attributes,
    }


def _index_lines(model) -> list[str]:
    lines: list[str] = []
    for index in sorted(model.__table__.indexes, key=lambda item: item.name or ""):
        columns = ", ".join(column.name for column in index.columns)
        suffix = " (unique)" if index.unique else ""
        lines.append(f"{index.name}: {columns}{suffix}")
    return lines


def build_erd() -> dict:
    """The five current tables, generated from the SQLAlchemy metadata."""
    entities = [
        _entity(Handover, row=0, col=0, tag="case", width=320),
        _entity(HandoverStage, row=0, col=1, tag="stages"),
        _entity(AgentReport, row=1, col=0, tag="evidence"),
        _entity(Document, row=1, col=1, tag="evidence"),
        _entity(Event, row=2, col=0, tag="audit"),
    ]
    relationships = [
        {
            "id": f"handovers-{table}",
            "from": "handovers",
            "to": table,
            "label": "has",
            "fromCardinality": "one",
            "toCardinality": "many",
            "fromOptional": False,
            "toOptional": False,
            "identifying": False,
            "variant": "dashed",
        }
        for table in ("handover_stages", "agent_reports", "documents", "events")
    ]
    return {
        "schema_version": 1,
        "diagram_type": "erd",
        "meta": _meta(
            "Handover database model",
            "erd",
            subtitle="Five tables from the SQLAlchemy models; child rows cascade with the case",
        ),
        "layout": {"mode": "grid", "gapX": 72, "gapY": 38},
        "entities": entities,
        "relationships": relationships,
        "cards": [
            {
                "dot": "cyan",
                "title": "One active case per serial",
                "items": [
                    "uq_handovers_active_device_serial is a partial unique index on device_serial",
                    "The predicate excludes completed and cancelled cases",
                    "The same rule is declared for PostgreSQL and SQLite",
                ],
            },
            {
                "dot": "slate",
                "title": "Indexes and constraints",
                "items": [
                    *_index_lines(Handover),
                    *_index_lines(HandoverStage),
                    *_index_lines(AgentReport),
                    *_index_lines(Document),
                    *_index_lines(Event),
                    "uq_handover_stages_handover_id_stage: one row per stage per case",
                ],
            },
            {
                "dot": "rose",
                "title": "Not in this model",
                "items": [
                    "agent_sessions is not a table in the current code",
                    "The task prompt lists it as optional; the differences page records the gap",
                ],
            },
        ],
    }


def _code_source_rows() -> list[str]:
    paths = [
        "app/domain/stages.py",
        "app/domain/handover_rules.py",
        "app/domain/software_rules.py",
        "app/db/models/handover.py",
    ]
    rows: list[str] = []
    for path in paths:
        rows.append(f"| Source file | [`{path}`]({BLOB_BASE}/{path}) |")
        rows.append(f"| SHA-256 | `{source_sha256(REPO_ROOT / path)}` |")
    return rows


def build_differences() -> str:
    """Explainer draft: the task prompt next to what the code actually does."""
    rows = [
        "| Topic | Task prompt or briefing | Code on this branch |",
        "| --- | --- | --- |",
        "| Stage count | \"all handover stages\" | Ten stages in `STAGE_ORDER`; the `HandoverStage` docstring still says \"exactly nine\" (stale comment) |",
        "| Stage statuses | pending, passed, failed, skipped, overridden | `pending`, `passed`, `failed`, `blocked`, `skipped`; a software override sets `skipped` with a reason |",
        "| Blocked stages | not named | `blocked` is used when the recipient identity cannot be determined |",
        "| Agent sessions table | `agent_sessions` \"if it exists\" | No `agent_sessions` table exists on this branch |",
        "| Stage order vs dependencies | stages listed in order | `STAGE_ORDER` is fixed; `STAGE_DEPENDENCIES` is a separate DAG (software and recipient both wait for the agent report) |",
        "| Who acts | engineer, employee PC + agent, portal, Snipe-IT | Same four actors; the agent is unauthenticated and the portal records its report |",
        "| One active case per serial | stated as a rule | `uq_handovers_active_device_serial`, a partial unique index excluding completed and cancelled |",
        "| Wrong file type | failure side path | Upload accepts PDF, PNG or JPEG only; anything else is rejected before storage |",
        "| Checkout verification | failure side path | Asset is re-read after checkout; a different assignee fails the stage |",
        "| Push verification | failure side path | Asset file list is re-read after upload; a missing scan fails the stage |",
        "| Briefing document | `docs/context/handover-portal-system-briefing.md` | The file does not exist; only the task prompt is available |",
    ]
    source_rows = _code_source_rows()
    return "\n".join(
        [
            "@meta locale=en",
            "",
            "# Device handover: code versus task prompt",
            "",
            "The code is the source of truth for the handover diagrams. This page "
            "puts the task prompt next to the behavior implemented on this branch, "
            "so a difference is visible instead of being silently aligned. The "
            "biggest gaps are the stage status vocabulary and the missing "
            "`agent_sessions` table; the ten-stage order and the dependency table "
            "match the prompt.",
            "",
            "## Differences {#differences}",
            "",
            *rows,
            "",
            "## What the diagrams read {#sources}",
            "",
            "The workflow, sequence, lifecycle and ERD builders import the pure "
            "stage modules and the SQLAlchemy models. A change to the stage list, "
            "the dependency table or a column changes the generated JSON and makes "
            "the visual check fail until the artifacts are rebuilt.",
            "",
            "## Source {#source}",
            "",
            "@facts",
            *source_rows,
            f"| Repository | [Open the repository]({BLOB_BASE}) |",
            "",
        ]
    ).rstrip() + "\n"


def build_handover_index() -> str:
    cards = [
        (
            "workflow.html",
            "WORKFLOW",
            "Device handover workflow",
            "All ten stages in order, the actor at each step, and every failure side path.",
            "Workflow",
        ),
        (
            "dependencies.html",
            "WORKFLOW",
            "Stage dependencies",
            "The dependency table as a DAG: every edge is a row of STAGE_DEPENDENCIES.",
            "Workflow",
        ),
        (
            "sequence.html",
            "SEQUENCE",
            "Onboarding at the employee's PC",
            "The SSO browser session, the one-time agent code and the verified Snipe-IT writes.",
            "Sequence",
        ),
        (
            "lifecycle.html",
            "LIFECYCLE",
            "Case lifecycle",
            "Draft, in progress, stalled, completed and cancelled, with the rule for each move.",
            "Lifecycle",
        ),
        (
            "stage-lifecycle.html",
            "LIFECYCLE",
            "Stage lifecycle",
            "Pending, passed, failed, blocked and skipped, including the software override.",
            "Lifecycle",
        ),
        (
            "erd.html",
            "ERD",
            "Database model",
            "Five tables, their columns, keys, indexes and the one-active-case-per-serial rule.",
            "ERD",
        ),
        (
            "differences.html",
            "EXPLAINER",
            "Code versus task prompt",
            "Where the task prompt and the implemented behavior disagree, shown side by side.",
            "Read",
        ),
    ]
    card_html = "\n".join(
        f"""      <a class="card" data-card href="{href}">
        <span class="num">{label}</span>
        <h2>{html.escape(title)}</h2>
        <p>{html.escape(description)}</p>
        <span class="meta"><span>Archify artifact</span><span class="pill">{pill}</span></span>
      </a>"""
        for href, label, title, description, pill in cards
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Device handover workflow</title>
<style>{INDEX_CSS}</style>
</head>
<body>
<main class="wrap">
  <header class="top">
    <div>
      <div class="eyebrow">auto-check-asset-management</div>
      <h1>Device handover workflow</h1>
      <p class="lede">The handover built from the application code: ten fixed stages, the onboarding sequence, both status lifecycles, the database model and the differences from the task prompt.</p>
    </div>
  </header>
  <div class="search"><input type="search" data-search placeholder="Search handover diagrams…" aria-label="Search handover diagrams"></div>
  <section class="grid" aria-live="polite">
{card_html}
  </section>
  <p data-empty class="hidden">No diagram matches that search.</p>
  <footer>Generated with Archify 3.2.0 from the committed code. Open any card; the pages work offline. <a href="../index.html">Back to all visuals</a>.</footer>
</main>
<script>{INDEX_JS}</script>
</body>
</html>
"""
