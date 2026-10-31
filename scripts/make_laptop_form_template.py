#!/usr/bin/env python
"""Generate a starter Laptop Form.docx merge template.

The application fills whatever .docx file FORM_TEMPLATE_PATH points at,
replacing {{...}} placeholders while preserving all Word formatting. This
script produces a clean, formatted starting template — an administrator can
then open it in Word and restyle freely, as long as the {{tokens}} remain.

Usage (from the project root):

    python scripts/make_laptop_form_template.py                # default path
    python scripts/make_laptop_form_template.py --force        # overwrite
    python scripts/make_laptop_form_template.py --out other.docx

Tokens written (all filled from the agent's inventory + best-effort Snipe-IT
record; unknown tokens are blanked at print time and logged):

    {{hostname}} {{username}} {{serial}} {{serial_number}} {{asset_id}}
    {{manufacturer}} {{model}} {{cpu}} {{cpu_cores}} {{ram_gb}} {{disks}}
    {{os_name}} {{os_version}} {{os_arch}} {{ip_addresses}} {{agent_os}}
    {{collected_at}} {{software_checks}}
    {{windows_activation_status}} {{windows_activation_product}}
    {{windows_activation_partial_key}}
    {{snipe_asset_tag}} {{snipe_name}} {{snipe_status}} {{snipe_assigned_to}}
    {{snipe_location}} {{snipe_purchase_date}} {{snipe_notes}}
"""
from __future__ import annotations

import argparse
import os
import sys

REPO_DEFAULT = os.path.join("templates", "Laptop Form.docx")
BR = "\u2021\u2021"   # internal multi-line sentinel used by the filler


def build(out_path: str) -> None:
    import docx
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, Cm

    document = docx.Document()
    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("Laptop Handover / Inventory Form")
    run.bold = True
    run.font.size = Pt(18)

    sub = document.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub_run = sub.add_run("Collected at {{collected_at}}  ·  Agent OS: {{agent_os}}")
    sub_run.font.size = Pt(9)

    document.add_paragraph()

    document.add_heading("Device", level=1)
    device_rows = [
        ("Hostname",                 "{{hostname}}"),
        ("Serial number / asset ID", "{{serial}}"),
        ("Asset tag (Snipe-IT)",     "{{snipe_asset_tag}}"),
        ("Record name",              "{{snipe_name}}"),
        ("Record status",            "{{snipe_status}}"),
        ("Assigned to",              "{{snipe_assigned_to}}"),
        ("Location",                 "{{snipe_location}}"),
        ("Manufacturer",             "{{manufacturer}}"),
        ("Model",                    "{{model}}"),
        ("Processor (cores)",        "{{cpu}} ({{cpu_cores}})"),
        ("Installed RAM (GB)",       "{{ram_gb}}"),
        ("Storage",                  "{{disks}}"),
        ("Operating system",         "{{os_name}} {{os_version}} ({{os_arch}})"),
        ("Network (IPv4)",           "{{ip_addresses}}"),
    ]
    _key_value_table(document, device_rows)

    document.add_heading("Software", level=1)
    document.add_paragraph(
        "Applications detected by the onboarding agent at collection time:")
    document.add_paragraph("{{software_checks}}")

    document.add_heading("Windows activation", level=1)
    _key_value_table(document, [
        ("Activation status", "{{windows_activation_status}}"),
        ("Edition",           "{{windows_activation_product}}"),
        ("Partial product key", "{{windows_activation_partial_key}}"),
    ])

    document.add_heading("Logistics", level=1)
    _key_value_table(document, [
        ("Collected on",     "{{collected_at}}"),
        ("Collected by",     "{{username}}"),
        ("Purchase date",    "{{snipe_purchase_date}}"),
        ("Notes",            "{{snipe_notes}}"),
    ])

    document.add_paragraph()
    document.add_paragraph("Device received by (name / signature):")
    document.add_paragraph("_" * 50)
    document.add_paragraph()
    document.add_paragraph("Handed over by (technician / signature):")
    document.add_paragraph("_" * 50)

    document.save(out_path)


def _key_value_table(document, rows) -> None:
    import docx
    table = document.add_table(rows=len(rows), cols=2)
    table.style = "Table Grid"
    for i, (key, value) in enumerate(rows):
        key_cell, value_cell = table.rows[i].cells
        key_run = key_cell.paragraphs[0].add_run(key)
        key_run.bold = True
        key_cell.width = docx.shared.Cm(6)
        value_cell.width = docx.shared.Cm(11)
        value_cell.paragraphs[0].add_run(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[2])
    parser.add_argument("--out", default=REPO_DEFAULT)
    parser.add_argument("--force", action="store_true",
                        help="overwrite an existing template")
    args = parser.parse_args()

    if os.path.exists(args.out) and not args.force:
        print(f"Refusing to overwrite existing '{args.out}'. Use --force.",
              file=sys.stderr)
        return 1
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    build(args.out)
    print(f"Written: {os.path.abspath(args.out)}")
    print("Open it in Word, restyle freely — keep the {{tokens}} intact.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
