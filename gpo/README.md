# GPO-Based Asset Data Collection

New data collection method for this project: the **existing** PowerShell agent
(`..\static\agent.ps1`, built for interactive onboarding with a session code)
is re-implemented as a **headless startup agent** deployed through **Active
Directory Group Policy**, writing inventory rows to a central network share in
**CSV** (Excel-compatible) instead of POSTing to the web app.

```
     every domain-joined device                    central file server
  +-----------------------------+             +--------------------------+
  | boot -> GPO Startup script  |             | \\SRV\AssetInventory$    |
  |   Launcher.bat (SysVol)     |  SMB 445    |  agent-gpo.ps1 (copy)    |
  |   -> powershell -Bypass     |------------>|  DeviceData\             |
  |   -> agent-gpo.ps1          |  write      |    device_inventory.csv  |
  |   -> append row (1/device)  |<------------|  SalesLaptops\ ...       |
  +-----------------------------+             +--------------------------+
                                                      |
                                            .\Merge-DeviceData.ps1
                                            -> merged_inventory.csv (+ .xlsx)
```

## Why this shape

| Decision                                                 | Reason |
| ---------------------------------------------------------| ------ |
| GPO **Startup** script, not a per-device copy            | SysVol serves the script automatically to every linked machine. Nothing is copied device-by-device, and updating the agent means re-running `Deploy-AssetGPO.ps1`, not touching a fleet. |
| `.cmd` wrapper (`Launcher.bat`)                          | A `.ps1` launched by the GP "PowerShell Scripts" mechanism honors the machine's PowerShell execution policy, and **SysVol is a network source** — a `RemoteSigned`/`AllSigned` domain would reject the unsigned agent. The wrapper instead calls `powershell.exe -ExecutionPolicy Bypass` explicitly, deterministically, everywhere. It also caches the agent to `%ProgramData%\AssetAgent`, so the run survives the network not being up at boot. |
| Hidden SMB share (`AssetInventory$`) | CSV files are trivially generated, open in Excel, and append-friendly. The share is hidden from the browse list. |
| **One row per device** (deduped by serial number) | The agent skips a device whose serial is already recorded; the rollup script still collapses duplicates at merge time as a safety net. |
| `Merge-DeviceData.ps1` rollup      | The raw share CSV is append-only (content never rewritten), so the Excel workbook is generated as a snapshot derived from it. |

## Files

| File                   | Runs on      | Purpose |
| ---------------------- | ------------ | ------- |
| `agent-gpo.ps1`        | every device | Headless twin of `static\agent.ps1`: same hardware / activation / software detection, no session code, appends a CSV row to the central share. May also run interactively for testing. |
| `Launcher.bat`         | every device | The script registered in the GPO Startup list. ASCII + CRLF only. |
| `Deploy-AssetGPO.ps1`  | DC / RSAT box| One-time (and re-runnable) setup: share + GPO + SysVol distribution + startup-script registration + link. `-Remove` tears it down. |
| `collect-anywhere.ps1` | admin box    | Push the agent over WinRM to selected machines **right now** (no reboot needed). |
| `Merge-DeviceData.ps1` | admin box    | Collapse the raw CSV into one row per serial, sort, optionally export `.xlsx` via Excel COM. |

## Deployment (about 15 minutes, one operator)

Prereqs:

* A Domain Controller (or an RSAT machine) with the `ActiveDirectory` +
  `GroupPolicy` PowerShell modules. All commands below run from an elevated
  shell with Domain Admin rights.
* Decide on the central storage location. By default the share is created on
  the machine running the deployment script; to use a dedicated file server
  instead, create the share there once and pass `-SkipShare -ShareUNC`.

### 1) Copy collector + launcher to the GPO store

`Deploy-AssetGPO.ps1` does this automatically (it stamps both files into the
GPO's SysVol `Machine\Scripts\Startup` folder and rewrites `.bat` files with
CRLF endings). Every future agent update is the same: edit the source in this
repo, rerun the deploy script, done — no per-device work.

### 2) Create the central share

Default (auto-created by the deploy script):

* NTFS folder `C:\Shares\AssetInventory`
* Hidden SMB share `AssetInventory$`
* NTFS/SMB ACLs: `Domain Computers` = Modify (the agent runs as Local SYSTEM
  which authenticates over SMB as the **computer account**), Administrators =
  Full, `Authenticated Users` = read.

To instead hand the agent a pre-existing share:

```powershell
.\Deploy-AssetGPO.ps1 -SkipShare -ShareUNC "\\SRVFILE01\AssetInventory$"
```

No Excel-to-share mapping is needed at start: the first agent run creates the
`DeviceData\device_inventory.csv` file with its header row.

### 3) Create + link the GPO

Same deploy script:

* `New-GPO -Name 'Snipe-IT Asset Collection'` (reused if it exists)
* `Machine\Scripts\scripts.ini` + the machine registry hooks the GP CSE reads
  are updated so `Launcher.bat` is a machine **Startup** script
* `New-GPLink` at the domain root (every domain-joined computer); narrow it to
  an OU (or a security group, via Security Filtering) whenever you want.

It completes with a self-check: `Get-GPOReport` (XML) must reference
`Launcher.bat` and the agent file must exist in SysVol.

### 4) Trigger the first collection

On any one representative machine:

```
gpupdate /target:computer /force
shutdown /r /t 0
```

...or grab data right now from selected machines without waiting for a boot:

```
.\collect-anywhere.ps1 -ComputerName NEMRA1-LT003, NEMRA1-LT004 `
                       -Share "\\SRVFILE01\AssetInventory$"
```

(Requires WinRM enabled on the targets and local-admin rights; the agent
content is pushed over the remote session, so no share copy is needed.)

### 5) Roll up for Excel

```powershell
.\Merge-DeviceData.ps1 -SourceFolder "\\SRVFILE01\AssetInventory$" -ExportXlsx
```

Produces `merged_inventory.csv` (+ `.xlsx` if Excel is installed locally),
sorted by hostname, one row per serial number, duplicates collapsed to the
**newest** row. Run it on demand or, later, from a scheduled task.

## CSV schema (written by `agent-gpo.ps1`)

One flat row per device samely-shaped across `DeviceData` and any per-department folder:

| Column                  | Notes |
| ----------------------- | ----- |
| `collected_at`          | `yyyy-MM-dd HH:mm:ss` (invariant, local server clock at collection time) |
| `collection_method`     | always `gpo-startup` (vs `session-http` for the legacy interactive agent) |
| `hostname`,`domain`,`is_domain_joined`,`username` | `username` is best-effort at boot: console owner via `Win32_ComputerSystem.UserName` → `explorer.exe` owner → registry `RegisteredOwner` |
| `serial_number`         | BIOS serial; **the dedupe key** |
| `manufacturer`,`model`  | Win32_ComputerSystem |
| `os_name`,`os_version`,`os_arch` | Win32_OperatingSystem |
| `cpu`,`cpu_cores`,`logical_processors`,`ram_gb` | Win32_Processor / Win32_PhysicalMemory (sum of sticks) |
| `disk_summary`          | up to 3 disks, e.g. `SSD 476.9GB | HDD 1024.0GB` |
| `ip_addresses`,`mac_addresses` | active physical adapters only (Ethernet + Wi-Fi) |
| `ou`                    | the computer's AD distinguished name (pivoting by department/OU) |
| `win_activation_status`,`win_product_name`,`win_partial_key` | Windows licensing (same semantics as the interactive agent) |
| `<app>_installed`,`<app>_version` | `office`,`chrome`,`vlc`,`forticlient`,`teams`,`sccm`,`intune` - same detection logic as `static\agent.ps1` (registry uninstall hives + services + MSIX + MDM fallbacks) |
| `software_list`         | comma-joined names of everything detected (for quick greps) |
| `agent_version`         | collector version, bump when the schema changes |

The whole set is mirrored as a JSON payload (same keys as the web app's Agent
Payload) at `<Share>\<Folder>\device_inventory.json` when `-AlsoJson` is used —
a natural bridge for feeding **Snipe-IT** through the existing API later.

## Operating details worth knowing

* **Re-runs are idempotent.** The agent checks (by serial number, looked up by
  header name) before appending, and `Merge-DeviceData.ps1` collapses again.
  Rebooting a machine twice only produces one row.
* **Network not ready at boot?** `Launcher.bat` caches the agent in
  `%ProgramData%\AssetAgent` and runs the cached copy; if neither SysVol nor
  cache is available it logs to the machine's Application event log
  (source `AssetAgentLauncher`).
* **Excel has the CSV open?** The agent retries the append (5× / 500 ms) and,
  worst case, spills the row to `%TEMP%` instead of corrupting the file. A
  device will simply re-try at its next boot.
* **Update the collector**: edit `gpo\agent-gpo.ps1` in the repo, rerun
  `Deploy-AssetGPO.ps1`. Since startup scripts are pulled from SysVol at every
  boot, all devices converge automatically; the cache is refreshed on the
  first successful boot after the update.
* **Scoping to a subset of devices**: link the GPO to OUs (simplest), or
  change the GPO's Security Filtering to a computer-security group and keep
  the link at the domain root. Don't use `-DomainRoot` for both — one or the
  other.
* **CSV per department**: every `<Share>\<SubFolder>\device_inventory.csv`
  using the same schema is picked up by the merge script automatically
  (`-Folder SalesLaptops` on the agent, an OU-scoped GPO, or
  `collect-anywhere.ps1 -Folder`).

## Security notes

* The share is hidden but not access-controlled against domain users beyond
  read; only `Domain Computers` (and administrators) can write, so a user
  cannot tamper with the inventory file. If tighter control matters, restrict
  SMB access further or host the file on an admin-only share and have the
  GPO agent POST instead (see roadmap).
* The agent runs as **Local SYSTEM**. It only reads WMI/registry and writes to
  the share; it does not touch user profiles.
* The `.cmd` uses `-ExecutionPolicy Bypass` **per invocation only**
  (`-Scope Process`), so the machine-wide execution policy is untouched.

## Roadmap (recommendation follow-ups)

1. **SQL Server**: replace the CSV share with a two-stage pipeline —
   `device_inventory.csv` stays the low-friction collection surface; a small
   import job (SQL Agent / PowerShell) loads rows into a staging table keyed
   by `serial_number` (UPSERT into `dbo.Device`), keeping history in a
   `dbo.DeviceSample` fact table. The `collected_at` column makes the delta
   trivial.
2. **HTTP-first**: extend `agent-gpo.ps1` with a `-SubmitUrl` mode that
   POSTs directly to the web app's `/api/...` (the JSON payload is already
   identical) once the app exposes a machine-authenticated endpoint, e.g.
   signed by a shared secret — the CSV share becomes the fallback.
3. **Non-Windows**: the same GPO can call the macOS/Unix equivalent; the
   `static/agent.sh` twin remains the linux counterpart for future phases.
