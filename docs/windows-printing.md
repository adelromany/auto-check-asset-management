# Windows printing — "Print Laptop Form"

Everything an administrator needs to run the Print Laptop Form feature on the
Windows Server that hosts the Asset Management web application.

## 1. What happens on a print request

```
Browser (laptop details page)
   │  click "Print Laptop Form"
   ▼
POST /api/session/{code}/print          (same session-ownership rules as data)
   │
   ├─ 1. Backend reads the session's LATEST agent inventory
   │      (+ best-effort Snipe-IT record lookup by serial)
   ├─ 2. Fills templates/Laptop Form.docx  ({{tokens}} replaced in Word runs,
   │      formatting preserved; python-docx)
   ├─ 3. Converts DOCX → PDF  (unattended LibreOffice headless by default)
   └─ 4. Submits the PDF to the configured Windows print queue
               via Ghostscript (mswinpr2 device → spooler)
   ▼
GUI shows "accepted by the print spooler"  → polls /api/print/jobs to show
whether the job is still spooling/printing or has left the queue.
```

Two states are deliberately distinguished — **"spooler accepted the job"**
(the submission API returned success) is not the same as **"paper came out"**
(observable only via the queue: `GET /api/print/jobs` lists live jobs with
their spool status; the GUI polls for up to ~12 s and reports the transition).

Generated artifacts (`.docx` + `.pdf`) are kept in `FORM_OUTPUT_DIR`
(default `var/print/`) as an audit trail.

## 2. Install the two server-side tools

```bat
:: 1) LibreOffice — DOCX→PDF converter (recommended, unattended-safe)
::    Install the 64-bit Windows build. Only soffice.exe is invoked headless.
:: 2) Ghostscript — PDF→printer submission
::    Install the 64-bit "Ghostscript for Windows" build (AGPL licence).
winget install -e --id TheDocumentFoundation.LibreOffice
winget install -e --id ArtifexSoftware.GhostScript
:: (or download from libreoffice.org / ghostscript.com — MSI installers)
```

Both are auto-detected if installed under `C:\Program Files`; otherwise set
`PRINT_SOFFICE_PATH` / `PRINT_GHOSTSCRIPT_PATH` explicitly.

> **Word automation (`PRINT_PDF_CONVERTER=word_com`) is supported as a
> fallback but discouraged.** Microsoft does not recommend or support
> unattended server-side automation of Office applications (session 0
> isolation, instability under service accounts). LibreOffice headless is the
> reliable default; no interactivity is required anywhere in the default
> pipeline.

## 3. Install / choose the printer

The queue must be installed **on the server** for the service account (a
per-user/per-session printer does not exist for a service). **Printing runs
entirely on the Windows Server that hosts the app** — employee laptops never
need the printer, and nothing is printed from a laptop.

For this deployment the printer is the USB-attached HP multifunction
(*HP Laser MFP 131 133 135-138*) hosted on server **fss**. The print flow
prints from the server under the service account, so:

* if the app runs **on fss itself**, the queue name is `HP Laser MFP USB`;
* from any other machine Windows shows the same share as
  `HP Laser MFP USB on fss` (the "on fss" suffix) — that is what appears in
  `Get-Printer` there. Set `PRINT_PRINTER` to the exact `Name` returned by
  `Get-Printer` **on the machine that runs the web app**:

```powershell
# run on the app server — use the exact "Name" column value
Get-Printer
# e.g.:  .env →  PRINT_PRINTER=HP Laser MFP USB
```

> **Paper size:** the declaration form is A4 portrait. Ghostscript's
> `mswinpr2` device uses the printer's default paper size, so set the queue's
> default form to **A4** (Printer Properties → Device Options / Printing
> Preferences → A4) once; the template's own page size is preserved on
> conversion.

## 4. Configuration (environment variables)

Add to the service's `.env` — all printing settings are read only in
`app/config.py`:

| Variable | Default | Meaning |
|---|---|---|
| `FORM_TEMPLATE_PATH` | `templates/Laptop Form.docx` | The merge template — for this deployment this is the **corporate declaration form** (B.TECH Finance "إقرار لاستخدام جهاز حاسب آلي", see §4a). A starter with every token is committed; regenerate with `scripts/make_laptop_form_template.py`. |
| `FORM_OUTPUT_DIR` | `var/print` | Filled `.docx`/`.pdf` artifacts (audit trail). |
| `PRINT_PRINTER` | *(unset)* | **Queue name used for printing.** Required unless the selector is enabled. Matches `Get-Printer` "Name". |
| `PRINT_ALLOW_PRINTER_SELECTOR` | `false` | When `true`, authorized users may pick any installed queue per request; otherwise requests specifying a printer are rejected (403). |
| `PRINT_PDF_CONVERTER` | `libreoffice` | `libreoffice` (recommended) or `word_com` (discouraged). |
| `PRINT_AUTOFILL_LABELS` | `true` | Fill the corporate form automatically by label cells (Model, Serial, Processor, RAM, …) — see §4a. `false` = {{tokens}} only. |
| `PRINT_SOFFICE_PATH` | *(auto-detect)* | Explicit path to `soffice.exe`. |
| `PRINT_GHOSTSCRIPT_PATH` | *(auto-detect)* | Explicit path to `gswin64c.exe`. |
| `PRINT_TIMEOUT_SECONDS` | `120` | Per-subprocess timeout (converter + spool submission). |
| `PRINT_LOG_FILE` | *(unset)* | Dedicated audit log file (see §7). |

Example:

```ini
PRINT_PRINTER=HP Laser MFP USB
PRINT_LOG_FILE=C:\SnipeitAsset\logs\printing.log
FORM_OUTPUT_DIR=D:\SnipeitAsset\print_output
```

## 4a. Using the corporate declaration form (no Word edits needed)

The production template is the B.TECH Finance handover form — Arabic RTL text,
the header logo, the Model/Serial table, the `NO. | SPECIFICATION |
BRAND/TYPE | CONFIG.` specification table and the signature block. Simply
**drop that .docx onto the server as `templates/Laptop Form.docx`** (or point
`FORM_TEMPLATE_PATH` at it). The filler never re-creates or re-typesets the
document: it opens a copy of your Word file and writes values into it, so
fonts, RTL layout, logos, borders and page numbering stay exactly as the
template author designed them, and the page prints A4 as before.

Two supported ways of getting the agent specs into it:

**1. Label autofill (default) — zero Word edits.** The filler looks for cells
whose entire text is one of the labels below and writes the value into the
*empty cell to the right* of the label. Existing text — the `NO.` numbers,
column headers, pre-typed cells and the second table's empty rows — is never
overwritten:

| Label in the form | Value written |
|---|---|
| `Model` | device model (agent's `Win32_ComputerSystem.Model`, e.g. a ThinkPad machine type) |
| `Serial` | BIOS serial number |
| `Processor` | short family — `i7`, `Ultra 7`, `Ryzen 5`, `Xeon`, `Apple M1` … (same style as the form's `i7` example) |
| `RAM` / `Memory` (GB) | integer GB — `16`, `32` (never `32.0`) |
| `Hard Disk` / `Storage` / `SSD` | first disk, e.g. `KIOXIA 476.9 GB SSD` |
| `Operating System` | `Windows 11 Pro 10.0.26100 (64-bit)` |
| `OS` | OS name |
| `User` / `Employee` | logged-on user at collection time |
| `Device Name` / `Hostname` | computer name |
| `Asset Tag` / `Location` / `Assigned to` | Snipe-IT record fields (when found) |

Disable with `PRINT_AUTOFILL_LABELS=false` if you prefer tokens only.

> Note: Windows reports the machine *type* as model (e.g. `21M8SCTP1D`).
> If you want the marketing name ("ThinkPad E14 Gen 6 155H") on the form,
> keep it in the Snipe-IT record and use the `{{snipe_name}}` token (below),
> or pre-type the marketing name for known models.

**2. `{{token}}` placement (optional, for precise spots).** You may also paste
tokens into any cell of the Word file — the two methods coexist (tokens win;
labels only fill empty cells):

```
{{hostname}} {{username}} {{serial}} {{model}} {{manufacturer}}
{{cpu}} {{cpu_family}} {{cpu_cores}} {{ram}} {{ram_gb}}
{{disks}} {{disk1}} {{os_name}} {{os_version}} {{os_arch}} {{os_full}}
{{ip_addresses}} {{agent_os}} {{collected_at}} {{software_checks}}
{{windows_activation_status}} {{windows_activation_product}}
{{windows_activation_partial_key}}
{{snipe_asset_tag}} {{snipe_name}} {{snipe_status}} {{snipe_assigned_to}}
{{snipe_location}} {{snipe_purchase_date}} {{snipe_notes}}
```

**Arabic/RTL fidelity check (one-time):** after dropping the real template in,
print one test page and compare against the original — logos, Arabic
shaping/justification, the footer (`b.labs-DIOP-01/FR-01`) and the date line
must look identical to a manual Word printout. Templates authored in Word with
commonly available fonts (Calibri, Arial, …) convert cleanly; if anything
mis-renders with LibreOffice, install the missing font on the server, or
switch `PRINT_PDF_CONVERTER=word_com` (Word's own rendering, at the cost of
the COM caveats documented above).

## 5. Dedicated service account

Run the web application (uvicorn/IIS/NSSM wrapper) under a dedicated account,
not an administrator:

```powershell
# 1. create a local (or domain) service account, e.g. svc-asset-print
# 2. grant ONLY what the pipeline needs:
#    a) read/execute on the application folder and Python venv
#    b) read on the folder holding FORM_TEMPLATE_PATH
#    c) modify on FORM_OUTPUT_DIR (and the folder holding PRINT_LOG_FILE)
#    d) print access on the target queue:
$acct       = "DOMAIN\\svc-asset-print"
$queue      = "HP Laser MFP USB"
$acl        = Get-Sddl -PrinterName $queue   # PowerShell 7+; or via printui
# simplest robust alternative: grant the account "Print" via
#   Settings → Printers → {queue} → Printer Properties → Security
# 3) log on as a service right (secpol.msc → Log On As A Service), or run the
#    app through a scheduled task / NSSM under that account.
```

Run a sanity check as that account:

```powershell
Get-Printer                     # queues must be visible
 rundll32 printui.dll,PrintUIEntry /TestPrint /n"HP Laser MFP USB"
```

If the account cannot see the queues, re-install the driver **for all users**
(`Printer Properties → Sharing → render print jobs on client computers` off;
install the queue under the service account or as local machine).

## 6. Metrics of success — validation plan

1. **Document generation (no printing):**

   ```powershell
   .venv\Scripts\python scripts\print_smoke_test.py
   ```

   Generates a filled sample docx into `var/print`, walks the template, and
   reports exactly which environment item is missing if any (LibreOffice,
   Ghostscript, etc.).

2. **Printer submission (mocked):** the whole HTTP surface is covered by
   `tests/test_print.py` (mocked print system — no real prints).

3. **Real print test (server, one manual run):**
   * open the app, run an agent session, click **Print Laptop Form**;
   * expect: button shows progress → "✓ Sent to `<queue>` … Accepted by the
     print spooler" → job status → "Job finished … check the printed page";
   * cross-check the queue with `Get-PrintJob -PrinterName <name>` during the
     job, and the paper output after;
   * check `PRINT_LOG_FILE` (or stdout) contains the acceptance entry with
     asset id, queue, document name, timestamp and job id when available.

## 7. Logging

Every submission logs (logger `app.printing`, also written to
`PRINT_LOG_FILE` when set):

* timestamp, action (enumerate / fill / convert / submission accepted),
* printer queue name, asset ID (hostname + serial), session code,
* spool job ID when observable, token errors, actionable failure details.

```powershell
Get-Content C:\SnipeitAsset\logs\printing.log -Tail 50 -Wait
```

## 8. Troubleshooting

| GUI error | Cause / fix |
|---|---|
| `No printer configured. Set the PRINT_PRINTER …` | Set `PRINT_PRINTER` to a queue name from `Get-Printer`, restart the service. |
| `Laptop Form template is not configured …` | `FORM_TEMPLATE_PATH` missing — commit/deploy the template (starter: `scripts/make_laptop_form_template.py`). |
| `Ghostscript is not installed …` | Install 64-bit Ghostscript or set `PRINT_GHOSTSCRIPT_PATH`. |
| `LibreOffice … not installed …` | Install 64-bit LibreOffice or set `PRINT_SOFFICE_PATH`. |
| `Ghostscript exited with code …` | Queue went offline / driver issue; check Windows `Event Viewer → Print Admin`, queue status, and service-account print permission. |
| Job never leaves the queue | Keep the spooler window open: `Get-PrintJob -PrinterName <name>` — usually an offline/port problem on the device, not the app. |

## 9. Security notes

* The GUI never receives server filesystem paths or shell commands — responses
  carry only queue names, document names, statuses and actionable operator
  hints.
* The printer selector, when enabled (`PRINT_ALLOW_PRINTER_SELECTOR=true`),
  accepts only queues that actually exist on the server (validated server-side).
* Print endpoints require authentication (SSO when enabled) — `401` otherwise;
  the session print endpoint additionally enforces session ownership (`403`).
* Printed artifacts in `FORM_OUTPUT_DIR` contain inventory data — ACL them like
  other operational data and rotate/delete as policy requires.
