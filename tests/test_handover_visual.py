"""The handover diagrams must follow the code, not a remembered workflow."""

from __future__ import annotations

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
from tools.visual.handover import (
    build_dependencies,
    build_erd,
    build_lifecycle,
    build_sequence,
    build_stage_lifecycle,
    build_workflow,
)

STAGE_IDS = {stage.value for stage in STAGE_ORDER}


def test_workflow_contains_every_stage_in_order() -> None:
    workflow = build_workflow()
    main_nodes = [node["id"] for node in workflow["nodes"] if node["id"] in STAGE_IDS]
    assert main_nodes == [stage.value for stage in STAGE_ORDER]
    assert workflow["mainPath"] == [stage.value for stage in STAGE_ORDER]


def test_workflow_has_the_required_failure_paths() -> None:
    ids = {node["id"] for node in build_workflow()["nodes"]}
    assert {
        "agent_report_missing",
        "serial_mismatch",
        "software_missing",
        "recipient_not_found",
        "checkout_mismatch",
        "wrong_file_type",
        "push_unverified",
    } <= ids


def test_dependency_edges_equal_the_code_table() -> None:
    expected = {
        (dependency.value, stage.value)
        for stage, dependencies in STAGE_DEPENDENCIES.items()
        for dependency in dependencies
    }
    actual = {
        (edge["from"], edge["to"]) for edge in build_dependencies()["edges"]
    }
    assert actual == expected


def test_dependency_main_path_is_a_real_path() -> None:
    dependencies = build_dependencies()
    edges = {(edge["from"], edge["to"]) for edge in dependencies["edges"]}
    path = dependencies["mainPath"]
    assert len(path) >= 2
    for left, right in zip(path, path[1:]):
        assert (left, right) in edges


def test_erd_matches_the_sqlalchemy_models() -> None:
    erd = build_erd()
    entities = {entity["id"]: entity for entity in erd["entities"]}
    models = {
        Handover.__tablename__: Handover,
        HandoverStage.__tablename__: HandoverStage,
        AgentReport.__tablename__: AgentReport,
        Document.__tablename__: Document,
        Event.__tablename__: Event,
    }
    assert set(entities) == set(models)
    for table, model in models.items():
        expected = [column.name for column in model.__table__.columns]
        actual = [attribute["name"] for attribute in entities[table]["attributes"]]
        assert actual == expected, table


def test_erd_relationships_are_one_to_many_from_handovers() -> None:
    relationships = build_erd()["relationships"]
    assert len(relationships) == 4
    assert {relationship["to"] for relationship in relationships} == {
        "handover_stages",
        "agent_reports",
        "documents",
        "events",
    }
    for relationship in relationships:
        assert relationship["from"] == "handovers"
        assert relationship["fromCardinality"] == "one"
        assert relationship["toCardinality"] == "many"


def test_no_diagram_repeats_a_node_id() -> None:
    for payload in (
        build_workflow(),
        build_dependencies(),
        build_lifecycle(),
        build_stage_lifecycle(),
        build_erd(),
    ):
        ids = [node["id"] for node in payload.get("nodes", payload.get("states", payload.get("entities", [])))]
        assert len(ids) == len(set(ids)), payload["meta"]["title"]


def test_case_lifecycle_covers_every_handover_status() -> None:
    states = {state["id"] for state in build_lifecycle()["states"]}
    assert states == {status.value for status in HandoverStatus}


def test_stage_lifecycle_covers_every_stage_status() -> None:
    states = {state["id"] for state in build_stage_lifecycle()["states"]}
    assert states == {status.value for status in StageStatus}
    # The task prompt calls the software override "overridden"; the code
    # stores it as skipped with a reason.
    assert "skipped" in states
    assert "overridden" not in states


def test_sequence_separates_sso_from_the_one_time_code() -> None:
    sequence = build_sequence()
    participants = {participant["id"] for participant in sequence["participants"]}
    assert {
        "engineer",
        "browser",
        "portal",
        "agent",
        "snipeit",
        "db",
    } <= participants
    labels = " ".join(message["label"] for message in sequence["messages"])
    assert "POST /api/session/{code}/submit (code only)" in labels
    assert "SSO" in labels
