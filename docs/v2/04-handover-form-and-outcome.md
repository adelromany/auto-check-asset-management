# Phase 04: Handover form by company, signed paper, outcome (Complete / Not complete yet / Ready)

Prerequisite: `HANDOFF-V2.md` says `PHASE 03 DONE`. Read `00-README` A and B1 (parts 4, 8 and the outcome rules).

Goal: the portal produces the handover form from the company's Word template (only the engineer name filled); the signed paper is uploaded and attached in Snipe-IT; every case shows one outcome.

Hosting note: the portal runs on a server and cannot print to the office printer. The engineer downloads the filled Word file and prints it from his own PC. The "Form" part passes when the portal generated the file for this case.

## Step 4.1 Fill the placeholder (pure function, standard library only)
Create `app/domain/form_fill.py` with:
```python
PLACEHOLDER = "{{ENGINEER}}"
def fill_engineer(docx_bytes: bytes, engineer_name: str) -> bytes: ...
class TemplateError(ValueError): ...
```
Rules:
- A `.docx` is a zip. Use `zipfile` + `re` only. Process `word/document.xml`, and also `word/header*.xml` and `word/footer*.xml` if they exist.
- Word often splits `{{ENGINEER}}` across several runs (`<w:t>{{</w:t>`, `<w:t>ENGINEER</w:t>`, `<w:t>}}</w:t>`). Algorithm per paragraph (`<w:p ...>...</w:p>` blocks): collect the text of every `<w:t ...>...</w:t>` in the paragraph, join them; if the joined text contains the placeholder, put the replaced full text in the FIRST `<w:t>` (add `xml:space="preserve"`) and make the other `<w:t>` of that paragraph empty. Leave paragraphs without the placeholder byte-for-byte unchanged.
- Escape the engineer name for XML (`&`, `<`, `>`, quotes).
- If the placeholder is found nowhere: raise `TemplateError("Placeholder {{ENGINEER}} not found in the template")`.
- Keep every other zip member unchanged and keep the zip valid (write with `ZIP_DEFLATED`, preserve `[Content_Types].xml` first).
Tests `tests/test_form_fill.py`: build a tiny docx in the test with `zipfile` (document.xml with the placeholder in one run; another case with it split into three runs; one with `&` in the name; one without placeholder expecting `TemplateError`). Re-open the result with `zipfile` and assert the text.
Check: `pytest tests/test_form_fill.py -q` green.

## Step 4.2 Template lookup by company
Config: `FORMS_DIR = os.getenv("FORMS_DIR", "forms")` in `app/config.py`.
Service `app/services/forms.py`:
```python
def find_template(forms_dir: Path, company: str | None) -> Path | None
```
It compares `normalize_company(company)` (from phase 03) with `normalize_company(path.stem)` for every `*.docx` in the folder. `None` when nothing matches or the company is unknown.
Create the folder `forms/` with a `README.md` of three lines: file name = company name from Snipe-IT (`B.tech.docx`, `Mylo.docx`), the placeholder `{{ENGINEER}}`, and how to check. Do NOT invent templates; the owner supplies `B.tech.docx` and `Mylo.docx`. For tests generate temporary templates.
Tool `tools/check_forms.py`: for each `forms/*.docx` prints `OK` or the `TemplateError`; exits non-zero on any error.
Tests: `B.tech` matches `B.tech.docx`; `btech` matches too; unknown company returns None.
Check: `pytest tests/test_form_fill.py tests/test_forms_service.py -q` green.

## Step 4.3 Form endpoint
`GET /api/handovers/{id}/form` in `app/routers/documents.py` (or handovers router; follow where documents live):
1. Load the case; company = `device_company`.
2. No template for the company: record `REPORT_PRINTED` as `failed` with reason `No form template for <company>` and return 404 JSON with the same line.
3. Template found: fill with the case's `engineer_name` (SSO identity of the engineer who OPENED the case; fall back to the current signed-in user if empty), return the file with `Content-Disposition: attachment; filename="<company>-<serial>.docx"` and the Word media type. Record `REPORT_PRINTED` as `passed` with detail `{"template": "<stem>", "engineer": "<name>"}`.
4. Never log the file content.
Tests: success returns a valid docx containing the engineer name; missing template gives 404 and a failed operation; a case with no company gives the same 404 line.
Check: `pytest tests/test_documents.py -q` green (adjust only tests tied to the removed print flow, and list them in `HANDOFF-V2.md`).

## Step 4.4 Signed paper (one action, two recorded operations)
Look at the existing scan/attach endpoints: `sed -n 277,330p app/routers/handovers.py`. Add one convenience endpoint `POST /api/handovers/{id}/signed-paper` (multipart file; PDF, PNG or JPEG; size limit from existing config):
1. Validate type and size (reuse existing validation).
2. Record `DOCUMENT_SCANNED` as `passed` (file stored as the current code does).
3. Immediately push it to the asset in Snipe-IT with the existing push logic; record `DOCUMENT_PUSHED` as `passed` or `failed` with the Snipe-IT error line. A failed push keeps the scan; `POST /{id}/operations/document_pushed/retry` retries only the push.
4. Requires `snipeit_asset_id`; otherwise 422 `Device is not linked to Snipe-IT`.
Tests: success records both; push failure keeps the scan passed and the push failed; retry succeeds.
Check: `pytest tests/test_handovers_api.py tests/test_snipeit_write_ops.py -q -k "signed_paper or push"` green.

## Step 4.5 Outcome (pure domain)
In `app/domain/handover_rules.py` add:
```python
def case_outcome(states, *, recipient_mode: str | None, cancelled: bool=False) -> Outcome
```
`Outcome` is a StrEnum: `complete`, `not_complete`, `ready`, `cancelled`.
- `cancelled` -> `cancelled`.
- every operation in `HANDOVER_OPERATIONS` is `passed` -> `complete`.
- `recipient_mode == "none"` and `DEVICE_STATUS`, `AGENT_REPORT`, `SOFTWARE_CHECK` are `passed` -> `ready` (a Ready lab).
- otherwise -> `not_complete`.
Also `def missing_parts(states) -> list[str]` returning the titles of the operations that are not passed (for the UI).
Wire it: the DTO `HandoverSummary` and `HandoverDetail` get `outcome: str` and `missing: list[str]`. `derive_status` returns `HandoverStatus.READY` when the outcome is `ready`, `COMPLETED` when `complete`, otherwise the existing active statuses (you may keep `STALLED`).
The list endpoint `GET /api/handovers` gets filters `outcome=complete|not_complete|ready` and `company=<name>`.
Tests: table-driven `tests/test_case_outcome.py` for all four outcomes, including the Ready case and a case where one failed operation keeps it not complete.
Check: `pytest tests/test_case_outcome.py tests/test_domain_rules.py -q` green.

## Step 4.6 Dashboard data
`app/services/dashboard.py` + `GET /api/dashboard/handover`: returns `{ready: {total, by_company: [{company, count}]}, complete: {total}, not_complete: {total}}` computed only from handover cases (kind handover). Add `GET /api/handovers?outcome=...&company=...` support if missing. Keep the older maintenance numbers out of this endpoint (separate section).
Tests with a few seeded cases in three companies.
Check: `pytest tests/test_dashboard.py -q` green (update tests that mixed maintenance numbers into the handover dashboard).

## Step 4.7 Live end to end for the handover backend (REQUIRED)
`tools/v2_probe_handover_full.py`, real Snipe-IT and the app code, `TEST-` data only:
1. Create template `forms/` files in a TEMP folder (not the repo) with the placeholder; set `FORMS_DIR` to it.
2. Case for `TEST-SN-0002` (B.tech): device-status passes; simulate the agent report with the documented payload (see `tests/` for a sample; no real device needed); software check passes.
3. Recipient `test.btech1`; items none; form endpoint returns a docx containing the engineer name.
4. Checkout; verify in Snipe-IT.
5. Signed paper upload of a small PNG; verify with `list_asset_files` that the file is on the asset.
6. Outcome is `complete`. Then repeat with recipient mode `none` on `TEST-SN-0003`: outcome is `ready`. Cleanup everything.
Check: all PASS; append to `docs/snipeit-integration-report.md` under "Phase 04".

## Step 4.8 Close the phase
Full suite once. `HANDOFF-V2.md`: `PHASE 04 DONE`, open items (Nexta template missing, printing from the hosted server). Add both to `docs/OPEN_QUESTIONS.md`. Commit.
Next file: `05-handover-ui.md`.
