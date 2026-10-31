"""The workflow visual must stay aligned with the executable stage model."""

import re
import subprocess
import sys
from pathlib import Path

from app.domain.stages import HandoverStatus, STAGE_DEPENDENCIES, STAGE_ORDER, StageStatus
from tools.build_handover_workflow import OUT, workflow_html


def test_generated_workflow_has_exact_code_order_edges_and_stage_content() -> None:
    document = workflow_html()
    main_flow = document.split('id="main-flow"', 1)[1].split('id="swim-lanes"', 1)[0]
    stages = re.findall(r'class="stage-card"[^>]*data-stage="([^"]+)"', main_flow)
    assert stages == [stage.value for stage in STAGE_ORDER]
    assert len(stages) == len(set(stages))
    cards = re.findall(r'<button class="stage-card".*?</button>', main_flow)
    assert len(cards) == len(STAGE_ORDER)
    for stage, card in zip(STAGE_ORDER, cards):
        assert f'data-stage="{stage.value}"' in card
        assert 'data-lane="' in card
        assert "<b>Who:</b>" in card
        assert "<b>Done when:</b>" in card

    actual_edges = set(re.findall(r'<li><code>([^<]+)</code> → <code>([^<]+)</code></li>', document))
    expected_edges = {
        (dependency.value, stage.value)
        for stage in STAGE_ORDER
        for dependency in STAGE_DEPENDENCIES[stage]
    }
    assert actual_edges == expected_edges
    lane_edges = set(re.findall(r'<span>([a-z_]+) → ([a-z_]+)</span>', document))
    assert lane_edges == {
        (dependency.value, stage.value)
        for stage in STAGE_ORDER
        for dependency in STAGE_DEPENDENCIES[stage]
    }
    assert len(re.findall(r'class="failure-card"', document)) == len(STAGE_ORDER)
    assert ", ".join(status.value for status in StageStatus) in document
    assert ", ".join(status.value for status in HandoverStatus) in document
    assert "FICTIONAL EXAMPLE ONLY" in document
    assert "TEST-SN-0001" in document and "TEST-recipient" in document
    assert len(re.findall(r'class="detail-card"', document)) == len(STAGE_ORDER)
    assert len(re.findall(r'<a href="05-business-principles.html#BIZ-', document)) >= len(STAGE_ORDER)
    assert 'class="lane-stage" tabindex="0" role="button"' in document
    assert actual_edges == expected_edges


def test_generated_page_is_current_and_linked_from_visual_index() -> None:
    root = Path(__file__).resolve().parents[1]
    assert OUT.read_text(encoding="utf-8") == workflow_html()
    index = (root / "docs/principles/visual/index.html").read_text(encoding="utf-8")
    assert 'href="handover-workflow.html"' in index
    assert not re.search(r'(?:href|src)=["\']https?://', OUT.read_text(encoding="utf-8"))
    result = subprocess.run(
        [sys.executable, "tools/build_handover_workflow.py", "--check"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
