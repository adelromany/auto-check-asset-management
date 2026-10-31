"""Generate the offline, code-derived device handover workflow page."""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.domain.handover_rules import _STAGE_HINTS, can_run, missing_steps
from app.domain.stages import STAGE_DEPENDENCIES, STAGE_ORDER, HandoverStatus, Stage, StageStatus

OUT = ROOT / "docs/principles/visual/handover-workflow.html"
TITLES = {
    Stage.DEVICE_PREPARED: ("Prepare device", "Engineer", "Device is ready for handover."),
    Stage.USER_SIGNED_IN: ("User signs in", "Employee", "The employee signs in on the device."),
    Stage.AGENT_REPORT: ("Collect agent report", "Local agent", "Serial and required hardware details pass validation."),
    Stage.SOFTWARE_CHECK: ("Check software", "Portal", "Required programs are installed and Windows is activated."),
    Stage.RECIPIENT_CHECK: ("Confirm recipient", "Engineer", "The selected employee exists in Snipe-IT."),
    Stage.CHECKOUT: ("Assign device", "Snipe-IT", "A re-read verifies the device assignment."),
    Stage.REPORT_PRINTED: ("Print report", "Engineer", "The agent report is printed."),
    Stage.USER_SIGNED: ("Collect signature", "Employee", "The printed sheet is signed."),
    Stage.DOCUMENT_SCANNED: ("Upload signed sheet", "Portal", "A supported scan is stored against the case."),
    Stage.DOCUMENT_PUSHED: ("Attach to asset", "Engineer", "Snipe-IT confirms the scan is attached to the device."),
}
DETAILS = {
    Stage.DEVICE_PREPARED: ("Prepare and inspect the physical device.", "Engineer confirms the stage.", "Stage is pending.", "Confirm the device is prepared for handover.", "BIZ-01"),
    Stage.USER_SIGNED_IN: ("Have the employee sign in on the device.", "Engineer confirms the stage.", "device_prepared is not passed or skipped.", "Confirm the user signed in on the device.", "BIZ-01"),
    Stage.AGENT_REPORT: ("Run the local reporting agent.", "Serial must match; CPU, positive RAM, and a disk must be present.", "Missing or mismatched hardware fields fail the stage.", "Run the agent on the device; its serial must match.", "BIZ-07"),
    Stage.SOFTWARE_CHECK: ("Review reported software and activation.", "Every configured program must be installed and activation status code must equal 1.", "Missing software or unlicensed activation fails; authenticated override requires an audit reason.", "Verify required software and Windows activation.", "BIZ-18"),
    Stage.RECIPIENT_CHECK: ("Search for and confirm the intended employee.", "The recipient must exist in Snipe-IT; the portal never creates users.", "Recipient not found in Snipe-IT blocks the stage.", "Search Snipe-IT for the recipient and confirm the match.", "BIZ-08"),
    Stage.CHECKOUT: ("Preview then confirm assignment.", "A re-read must show the expected asset assignment.", "A conflicting holder or verification mismatch prevents pass.", "Checkout the device to the confirmed recipient in Snipe-IT.", "BIZ-05"),
    Stage.REPORT_PRINTED: ("Print the agent report page.", "Engineer confirms it was printed.", "Agent report must be satisfied.", "Print the agent report page.", "BIZ-01"),
    Stage.USER_SIGNED: ("Collect the employee signature on paper.", "Engineer confirms the signed sheet.", "report_printed must be satisfied.", "Get the printed sheet signed on paper.", "BIZ-01"),
    Stage.DOCUMENT_SCANNED: ("Scan and upload the signed sheet.", "The uploaded file type and size must pass validation.", "Unsupported file type or size is rejected.", "Upload the scanned signed sheet.", "BIZ-09"),
    Stage.DOCUMENT_PUSHED: ("Attach the scan to the device asset.", "Snipe-IT must verify the uploaded attachment.", "Unknown asset or unverified push fails.", "Push the scan to the device's Snipe-IT asset.", "BIZ-09"),
}
FAILURES = {
    Stage.DEVICE_PREPARED: ("Device is damaged or not ready", "Resolve the physical issue, then confirm preparation."),
    Stage.USER_SIGNED_IN: ("Employee cannot sign in", "Check network/identity access and confirm the employee reaches the desktop."),
    Stage.AGENT_REPORT: ("Agent report missing or serial/hardware invalid", "Run the agent again and resolve the reported mismatch."),
    Stage.SOFTWARE_CHECK: ("Required software missing or Windows not activated", "Install or activate, then re-evaluate; any override needs a reason."),
    Stage.RECIPIENT_CHECK: ("Recipient not found in Snipe-IT", "Check the identity and ask an asset administrator to correct Snipe-IT."),
    Stage.CHECKOUT: ("Checkout verification does not match", "Refresh the asset state and resolve the current holder before retrying."),
    Stage.DOCUMENT_SCANNED: ("Wrong file type or upload exceeds the limit", "Rescan to a supported file type and upload again."),
    Stage.DOCUMENT_PUSHED: ("Push was not verified", "Check the asset exists and verify the attachment before retrying."),
    Stage.REPORT_PRINTED: ("Report did not print", "Check the selected printer and print the report page again."),
    Stage.USER_SIGNED: ("Signed sheet was not returned", "Ask the employee to sign the printed sheet before scanning."),
}
LANES = ("Engineer", "Employee", "Local agent", "Portal", "Snipe-IT")
STAGE_LANE = {
    Stage.DEVICE_PREPARED: "Engineer", Stage.USER_SIGNED_IN: "Employee",
    Stage.AGENT_REPORT: "Local agent", Stage.SOFTWARE_CHECK: "Portal",
    Stage.RECIPIENT_CHECK: "Engineer", Stage.CHECKOUT: "Snipe-IT",
    Stage.REPORT_PRINTED: "Engineer", Stage.USER_SIGNED: "Employee",
    Stage.DOCUMENT_SCANNED: "Portal", Stage.DOCUMENT_PUSHED: "Snipe-IT",
}
WRITES = {Stage.CHECKOUT, Stage.DOCUMENT_PUSHED}
READS_SNIPE_IT = {Stage.RECIPIENT_CHECK}


def _escape(value: str) -> str:
    return html.escape(value, quote=True)


def _contrast(hex_color: str) -> tuple[float, float, float]:
    vals = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in vals]
    return tuple(linear)  # type: ignore[return-value]


def contrast_ratio(fg: str, bg: str) -> float:
    luminance = lambda color: sum(w * c for w, c in zip((.2126, .7152, .0722), _contrast(color)))
    high, low = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (high + .05) / (low + .05)


def contrast_table() -> str:
    pairs = {
        ("body", "#1F2328", "#FFFFFF"), ("muted", "#57606A", "#FFFFFF"),
        ("surface text", "#1F2328", "#F6F8FA"), ("dark body", "#E6EDF3", "#0F1419"),
        ("dark muted", "#9AA4AF", "#0F1419"), ("dark surface text", "#E6EDF3", "#161B22"),
        ("link", "#0969DA", "#FFFFFF"), ("ok label", "#1A7F37", "#FFFFFF"),
        ("warning label", "#9A6700", "#FFFFFF"), ("error label", "#CF222E", "#FFFFFF"),
    }
    for theme, backgrounds in (("light", ("#FFFFFF", "#F6F8FA")), ("dark", ("#0F1419", "#161B22"))):
        for label, color in (("status ok icon", "#1A7F37"), ("status warning icon", "#9A6700"), ("status error icon", "#CF222E")):
            for bg in backgrounds:
                pairs.add((f"{label} {theme}", color, bg))
    for theme, backgrounds in (("light", ("#FFFFFF", "#F6F8FA")), ("dark", ("#0F1419", "#161B22"))):
        for layer, color in (("routers", "#0969DA"), ("services", "#1A7F37"), ("repositories/clients", "#9A6700"), ("db/external", "#8250DF"), ("domain", "#0A7C86")):
            for bg in backgrounds:
                pairs.add((f"Layer {layer} {theme}", color, bg))
    rows = []
    for label, fg, bg in sorted(pairs):
        ratio = contrast_ratio(fg, bg)
        minimum = 3.0 if label == "link" or label.startswith("Layer ") or "icon" in label else 4.5
        if ratio < minimum:
            raise ValueError(f"Contrast failure: {label} {fg} on {bg}: {ratio:.2f}:1")
        rows.append(f'<tr><th>{_escape(label)}</th><td>{fg}</td><td>{bg}</td><td>{ratio:.2f}:1</td></tr>')
    return "\n".join(rows)


def workflow_html() -> str:
    stages = list(STAGE_ORDER)
    if [item["stage"] for item in missing_steps([])] != [stage.value for stage in stages]:
        raise ValueError("handover_rules missing-step order differs from STAGE_ORDER")
    positions = {stage: index for index, stage in enumerate(stages, 1)}
    boxes = []
    for stage in stages:
        title, who, done = TITLES[stage]
        rules = DETAILS[stage]
        deps = ",".join(dependency.value for dependency in STAGE_DEPENDENCIES[stage])
        attrs = f'data-stage="{stage.value}" data-lane="{_escape(STAGE_LANE[stage])}" data-depends="{deps}"'
        write_marker = '<span class="write-marker">✎ Writes Snipe-IT</span>' if stage in WRITES else ('<span class="read-marker">◉ Reads Snipe-IT only</span>' if stage in READS_SNIPE_IT else '<span class="read-marker">○ Manual / portal evidence</span>')
        override_badge = '<span class="override-badge">Override only with an authenticated reason; hardware rules cannot be overridden</span>' if stage is Stage.SOFTWARE_CHECK else ""
        boxes.append(f'<button class="stage-card" {attrs} type="button"><span class="stage-number">{positions[stage]:02}</span><strong>{_escape(title)}</strong><span class="stage-key">{stage.value}</span><span><b>Who:</b> {_escape(who)}</span><span><b>Done when:</b> {_escape(done)}</span>{override_badge}{write_marker}<span class="detail-source" hidden>{" | ".join(map(_escape, rules))}</span></button>')
    edges = [(stage, dep) for stage in stages for dep in STAGE_DEPENDENCIES[stage]]
    edge_list = "".join(f'<li><code>{target.value}</code> → <code>{source.value}</code></li>' for source, target in edges)
    lane_edges = "".join(
        f'<li><b>{_escape(STAGE_LANE[dependency])}</b> → <b>{_escape(STAGE_LANE[stage])}</b><span>{dependency.value} → {stage.value}</span></li>'
        for stage, dependency in edges
    )
    lanes = []
    for lane in LANES:
        lane_cards = []
        for stage in stages:
            if STAGE_LANE[stage] != lane:
                continue
            title, who, done = TITLES[stage]
            marker = ' · Snipe-IT write' if stage in WRITES else ''
            deps = ",".join(dependency.value for dependency in STAGE_DEPENDENCIES[stage])
            lane_cards.append(f'<div class="lane-stage" tabindex="0" role="button" aria-label="Focus {_escape(title)} stage" data-stage="{stage.value}" data-depends="{deps}"><b>{positions[stage]:02} · {_escape(title)}</b><span>{_escape(done)}{marker}</span></div>')
        lanes.append(f'<div class="swim-lane"><h3>{_escape(lane)}</h3><div class="lane-steps">{"".join(lane_cards)}</div></div>')
    detail_rows = []
    for stage in stages:
        title, _, _ = TITLES[stage]
        engineer, checks, blocks, _, rule_id = DETAILS[stage]
        missing = _STAGE_HINTS[stage]
        detail_rows.append(f'<article class="detail-card" data-detail="{stage.value}"><h3>{positions[stage]:02} · {_escape(title)}</h3><dl><dt>Engineer does</dt><dd>{_escape(engineer)}</dd><dt>System checks</dt><dd>{_escape(checks)}</dd><dt>What blocks it</dt><dd>{_escape(blocks)}</dd><dt>Dashboard when missing</dt><dd>{_escape(missing)}</dd><dt>Rule</dt><dd><a href="05-business-principles.html#{rule_id}">{rule_id}</a></dd></dl></article>')
    failure_rows = []
    for stage in stages:
        if stage not in FAILURES:
            continue
        failure, recovery = FAILURES[stage]
        failure_rows.append(f'<article class="failure-card"><span aria-hidden="true">✕</span><h3>{_escape(stage.value)}</h3><p>{_escape(failure)}</p><p><b>Next:</b> {_escape(recovery)}</p></article>')
    status_names = ", ".join(status.value for status in StageStatus)
    case_statuses = ", ".join(status.value for status in HandoverStatus)
    dependency_rule = " ".join((can_run.__doc__ or "").split())
    lifecycle = "".join(f'<li><b>{status.value}</b> — {_escape(rule)}</li>' for status, rule in [
        (HandoverStatus.DRAFT, "All stages pending and below the age threshold."),
        (HandoverStatus.IN_PROGRESS, "At least one stage has activity; no failure, block, completion, cancellation, or age stall."),
        (HandoverStatus.STALLED, "Any stage failed/blocked, or inactive longer than STALL_HOURS (default 24; zero disables)."),
        (HandoverStatus.COMPLETED, "Every stage is passed or skipped."),
        (HandoverStatus.CANCELLED, "Explicit cancellation; this status takes precedence."),
    ])
    evidence = {
        Stage.DEVICE_PREPARED: "Engineer confirmation and event row.",
        Stage.USER_SIGNED_IN: "Engineer confirmation and event row.",
        Stage.AGENT_REPORT: "Validated report with TEST-SN-0001, CPU, RAM and disk evidence.",
        Stage.SOFTWARE_CHECK: "Software check result and activation status in the case record.",
        Stage.RECIPIENT_CHECK: "Confirmed TEST-recipient identity and event row.",
        Stage.CHECKOUT: "Snipe-IT checkout call followed by a verified re-read.",
        Stage.REPORT_PRINTED: "Engineer confirmation and event row.",
        Stage.USER_SIGNED: "Engineer confirmation that the paper sheet is signed.",
        Stage.DOCUMENT_SCANNED: "Stored scan and fictional SHA-256 evidence hash: 9f2c7e6a4d1b83c5e7190a2d6c4f0b8e1a3d5c7f902b6e4a8d1c3f5b7e9a10d2.",
        Stage.DOCUMENT_PUSHED: "Snipe-IT attachment call and verified re-read.",
    }
    example_timeline = "".join(
        f'<li><b>{positions[stage]:02} · {_escape(TITLES[stage][0])}</b><span>{_escape(evidence[stage])}</span></li>'
        for stage in stages
    )
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light dark"><title>Device handover workflow</title><link rel="stylesheet" href="assets/visual.css"><link rel="stylesheet" href="assets/workflow.css"><script defer src="assets/workflow.js"></script></head>
<body data-page="workflow"><header class="site-header"><a href="index.html">Principles</a><h1>Device handover workflow</h1><button type="button" data-theme>Theme</button></header>
<main class="workflow-main"><section class="workflow-legend"><h2>How to read this page</h2><p>Follow numbered steps in order. A dependency means every prerequisite must be passed or skipped before its dependent step runs. Select a step to inspect rules and neighbors. A pencil marks a write to Snipe-IT; a target marks a read or confirmation.</p><p><b>Stage statuses from code:</b> {_escape(status_names)}. Status always has a text label.</p><div class="legend-sticky"><span>● Stage dependency</span><span>✎ Write to Snipe-IT</span><span>◉ Snipe-IT read-only</span><span>○ Manual / portal evidence</span><label><input type="checkbox" data-failures checked> Show failure paths</label><button type="button" data-view="flow" aria-pressed="true">Main flow</button><button type="button" data-view="lanes" aria-pressed="false">Swim lanes</button></div></section>
<section class="workflow-section" id="main-flow"><h2>1. Main flow</h2><p>Each numbered stage names the actor and the observable condition that completes it. Select a box for direct dependencies.</p><ol class="stage-grid">{"".join(f'<li>{box}</li>' for box in boxes)}</ol><div class="dependency-list"><h3>Dependency arrows</h3><ul>{edge_list}</ul></div></section>
<section class="workflow-section" id="swim-lanes"><h2>2. Swim lanes</h2><p>Steps sit in the actor's lane; arrows identify the prerequisite and dependent lanes. Some dependencies stay within one lane. Checkout and the verified file push write to Snipe-IT.</p><div class="lanes">{"".join(lanes)}</div><ul class="cross-lane-arrows">{lane_edges}</ul><p class="irreversible"><b>⚠ Irreversible-looking action:</b> a verified Snipe-IT checkout changes the asset assignment. Preview first, then verify the resulting assignment.</p></section>
<section class="workflow-section" id="stage-details"><h2>3. Stage detail</h2><p>Choose any stage above to focus its details. Rule links open the business-principle source.</p><p><b>Execution rule from code:</b> {_escape(dependency_rule)}</p><div class="detail-grid">{"".join(detail_rows)}</div></section>
<section class="workflow-section failure-paths" id="failure-paths"><h2>4. Failure and recovery paths</h2><p>Dashed red branches indicate a failure; the next action is stated beside it.</p><div class="failure-grid">{"".join(failure_rows)}</div></section>
<section class="workflow-section" id="case-lifecycle"><h2>5. Case lifecycle</h2><p>Lifecycle names are read from <code>HandoverStatus</code>. Derivation follows <code>derive_status</code>.</p><p class="status-list">Statuses in code: {_escape(case_statuses)}</p><ol class="lifecycle">{lifecycle}</ol></section>
<section class="workflow-section" id="example"><h2>6. Example walkthrough</h2><p class="example-label">FICTIONAL EXAMPLE ONLY · TEST-SN-0001 · TEST-recipient</p><ol class="timeline">{example_timeline}</ol></section>
<section class="workflow-section" id="differences"><h2>Differences from briefing</h2><p>No handover briefing/diagram file was found under <code>docs/</code> during generation. The page therefore follows the executable source: ten ordered stages and the exact dependency map exported from <code>app/domain/stages.py</code>.</p></section>
<section class="workflow-section"><h2>Contrast check</h2><table><thead><tr><th>Pair</th><th>Foreground</th><th>Background</th><th>Ratio</th></tr></thead><tbody>{contrast_table()}</tbody></table></section>
<p class="generated">Generated from app/domain/stages.py, app/domain/handover_rules.py and app/domain/software_rules.py · {_escape(', '.join(stage.value for stage in STAGE_ORDER))}</p></main></body></html>'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = workflow_html()
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != expected:
            print(f"STALE: {OUT.relative_to(ROOT)}", file=sys.stderr)
            return 1
        print("OK: handover workflow page is current")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(expected, encoding="utf-8", newline="\n")
    print(f"Wrote {OUT.relative_to(ROOT)}")
    print("Contrast pairs checked (both themes):")
    print("Pair | foreground | background | ratio")
    for row in contrast_table().splitlines():
        readable = re.sub(r"</(?:th|td)><(?:th|td)>", " | ", row)
        print(" ".join(re.sub(r"<[^>]+>", "", readable).split()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
