<#
.SYNOPSIS
    Merge per-device CSV rows collected by the GPO agent (gpo\agent-gpo.ps1)
    into one clean, Excel-ready inventory report with exactly one row per
    machine (serial number).

.DESCRIPTION
    The GPO agent appends one CSV row per boot to the central share. Re-runs
    are guarded against duplicates by serial number, but if the file is used
    from several department folders, or if a device's serial changes (security
    wipe, motherboard swap), it is useful to generate a clean report.

    This script:
      1) reads the central CSV (all rows from all folders if a share root is
         given),
      2) drops duplicated header lines and duplicated serial numbers, keeping
         the newest rows,
      3) optionally drops rows older than -StaleDays days,
      4) writes ONE new CSV (Excel-ready, UTF-8, one row per device),
      5) prints a small summary (total rows, unique devices, ...),
      6) with -ExportXlsx also writes an .xlsx version alongside the CSV using
         the local Excel COM server if Excel is installed (purely best-effort).

    UTF-8 output: Excel reads UTF-8 CSVs directly (double-click) provided the
    file starts with a BOM, which is how this script writes the output.

.EXAMPLE
    PS> .\Merge-DeviceData.ps1 -SourceFolder \\SRVFILE01\AssetInventory$ `
                               -ExportXlsx
    Merges every device_inventory.csv under every folder on the share and
    writes an .xlsx beside it.

.EXAMPLE
    PS> .\Merge-DeviceData.ps1 -SourceCsv device_inventory.csv -InPlace
    Clean up the file itself in place (dedupe + sort).
#>
[CmdletBinding()]
param(
    # Folder to scan for the collected CSV files. If not given, falls back to
    # $env:ASSET_SHARE.
    [string]$SourceFolder,

    # Alternatively the exact CSV file (used with -InPlace).
    [string]$SourceCsv,

    # Where to write the merged report. Default: <script-dir>\merged_inventory.csv
    # (or <parent-of-source>.csv when -InPlace was not passed).
    [string]$OutputCsv,

    # Rewrite the source file itself (dedupe + sorted) instead of adding a new one.
    [switch]$InPlace,

    # Drop rows whose collected_at is older than this many days.
    [int]$StaleDays = 0,

    # Also write an .xlsx (requires a local Microsoft Excel installation).
    [switch]$ExportXlsx,

    # Field name to pivot on for the console summary (e.g. ou, department).
    [string]$PivotOn = 'ou'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# ══════════════════════════════════════════════════════════════════════════════
#  locate input
# ══════════════════════════════════════════════════════════════════════════════
if (-not $SourceFolder -and -not $SourceCsv) {
    if ($env:ASSET_SHARE) {
        $SourceFolder = $env:ASSET_SHARE
    } else {
        throw 'Provide -SourceFolder (e.g. \\SRVFILE01\AssetInventory$) or -SourceCsv.'
    }
}

$inputFiles = @()
if ($SourceCsv) {
    if (-not (Test-Path -LiteralPath $SourceCsv)) { throw "CSV not found: $SourceCsv" }
    $inputFiles = @($SourceCsv)
} else {
    $folder = $SourceFolder.TrimEnd('\')
    # the agent writes  <share>\DeviceData\device_inventory.csv  (default) plus
    # optionally per-department folders; pick up every device_inventory.csv below.
    $inputFiles = @(Get-ChildItem -LiteralPath $folder -Filter 'device_inventory.csv' -Recurse -File |
                    Select-Object -ExpandProperty FullName)
    if ($inputFiles.Count -eq 0) {
        throw "No device_inventory.csv found under: $folder"
    }
}

# ══════════════════════════════════════════════════════════════════════════════
#  robust CSV reader  (handles quoted fields with embedded commas/quotes)
# ══════════════════════════════════════════════════════════════════════════════
function Read-CsvRobust {
    param([string]$Path)

    $result = @{
        header = @()
        rows   = [System.Collections.Generic.List[object]]::new()  # each row: object[] of string
    }

    $reader   = [System.IO.StreamReader]::new($Path, [System.Text.Encoding]::UTF8)
    try {
        $fields   = [System.Collections.Generic.List[string]]::new()
        $field    = [System.Text.StringBuilder]::new()
        $inQuotes = $false

        while ($null -ne ($line = $reader.ReadLine())) {
            $i = 0
            while ($i -lt $line.Length) {
                $ch = $line[$i]
                if ($inQuotes) {
                    if ($ch -eq '"') {
                        if (($i + 1) -lt $line.Length -and $line[$i + 1] -eq '"') {
                            [void]$field.Append('"')
                            $i += 2
                            continue
                        }
                        $inQuotes = $false
                        $i++
                        continue
                    }
                    [void]$field.Append($ch)
                    $i++
                } else {
                    if ($ch -eq '"') {
                        $inQuotes = $true
                        $i++
                    } elseif ($ch -eq ',') {
                        [void]$fields.Add($field.ToString())
                        [void]$field.Clear()
                        $i++
                    } else {
                        [void]$field.Append($ch)
                        $i++
                    }
                }
            }
            if ($inQuotes) {
                # quoted field continued onto the next physical line
                [void]$field.Append("`r`n")
                $inQuotes = $false
            } else {
                [void]$fields.Add($field.ToString())
                [void]$field.Clear()
                $row = $fields.ToArray()
                $fields.Clear()
                if (-not $result.header) {
                    $result.header = $row
                } else {
                    [void]$result.rows.Add($row)
                }
            }
        }
        # flush a trailing row without a final newline
        if ($field.Length -gt 0 -or $fields.Count -gt 0) {
            [void]$fields.Add($field.ToString())
            [void]$field.Clear()
            if ($result.header) { [void]$result.rows.Add($fields.ToArray()) }
        }
    } finally {
        $reader.Close()
    }
    return $result
}

# ══════════════════════════════════════════════════════════════════════════════
#  load + dedupe
# ══════════════════════════════════════════════════════════════════════════════
$allRows = @()
$header  = @()
foreach ($file in $inputFiles) {
    $parsed = Read-CsvRobust -Path $file
    if ($parsed.header.Count -gt 0) {
        if (-not $header) { $header = $parsed.header }
        foreach ($row in $parsed.rows) { $allRows += ,@($row) }
    }
}
if ($header.Count -eq 0) { throw 'The first input file had no header row.' }

# Rows with orphan cols (shorter/longer than header) are still kept as-is.
$offset = @{}  # header-name -> index
for ($i = 0; $i -lt $header.Count; $i++) {
    if (-not $offset.ContainsKey($header[$i])) { $offset[$header[$i]] = $i }
}
$serialHdr   = if ($offset.ContainsKey('serial_number'))   { $offset['serial_number'] }   else { -1 }
$collectedHdr = if ($offset.ContainsKey('collected_at'))   { $offset['collected_at'] }    else { -1 }

# drop blank rows already
$allRows = @($allRows | Where-Object { @($_ | Where-Object { $_ -and $_ -ne '' }).Count -gt 0 })

# drop stray duplicate header lines that sneak in when several devices
# appended to a fresh file simultaneously (schema field #1 = collected_at,
# which a real data row can never carry)
$allRows = @($allRows | Where-Object { -not ($_.Count -gt 0 -and [string]$_[0] -eq 'collected_at') })

# serialize dedupe: serial -> row with the newest collected_at
$bySerial    = @{}
$noSerial    = @()
$duplicates  = 0
foreach ($row in $allRows) {
    $key = if ($serialHdr -ge 0 -and $row.Count -gt $serialHdr) { [string]$row[$serialHdr] } else { '' }
    $ts  = if ($collectedHdr -ge 0 -and $row.Count -gt $collectedHdr) { [string]$row[$collectedHdr] } else { '' }
    $parsed = [datetime]::MinValue
    if ($ts) {
        [datetime]::TryParseExact(
            $ts, 'yyyy-MM-dd HH:mm:ss',
            [System.Globalization.CultureInfo]::InvariantCulture,
            [System.Globalization.DateTimeStyles]::None,
            [ref]$parsed) | Out-Null
    }

    if (-not $key -or $key -eq 'N/A') {
        $noSerial += ,@($row)
        continue
    }
    if ($bySerial.ContainsKey($key)) {
        $duplicates++
        if ($parsed -gt $bySerial[$key].ts) {
            $bySerial[$key] = @{ ts = $parsed; row = $row }
        }
    } else {
        $bySerial[$key] = @{ ts = $parsed; row = $row }
    }
}

$kept = @($bySerial.Values | ForEach-Object { ,@($_.row) })
if ($StaleDays -gt 0) {
    $cutoff = (Get-Date).AddDays(-$StaleDays)
    # rows with an unparseable timestamp have MinValue and get pruned too
    $kept   = @($kept | Where-Object { $_.ts -ge $cutoff })
}
$out = @($kept + $noSerial)

# stable sort by hostname (2nd column in the payload schema), fallback untouched
$hostHdr = if ($offset.ContainsKey('hostname')) { $offset['hostname'] } else { -1 }
if ($hostHdr -ge 0) {
    $out = @($out | Sort-Object { [string]$_[$hostHdr] })
}

# ══════════════════════════════════════════════════════════════════════════════
#  write
# ══════════════════════════════════════════════════════════════════════════════
function _EscapeCsv {
    param([string]$Value)
    if ([string]::IsNullOrEmpty($Value)) { return '' }
    if ($Value -match '[",\r\n]') {
        return '"' + $Value.Replace('"', '""') + '"'
    }
    return $Value
}

if (-not $OutputCsv) {
    if ($InPlace) {
        $OutputCsv = $SourceCsv
    } else {
        $OutputCsv = Join-Path $PSScriptRoot 'merged_inventory.csv'
    }
}
$outDir = Split-Path -Parent $OutputCsv
if ($outDir -and -not (Test-Path -LiteralPath $outDir)) {
    New-Item -Path $outDir -ItemType Directory -Force | Out-Null
}

# Excel hits both: UTF-8 BOM at the top; CRLF row separators.
$utf8Bom   = New-Object System.Text.UTF8Encoding $true
$sw        = [System.IO.StreamWriter]::new($OutputCsv, $false, $utf8Bom)
try {
    $sw.WriteLine(($header | ForEach-Object { _EscapeCsv $_ }) -join ',')
    foreach ($row in $out) {
        $cells = foreach ($c in $row) { _EscapeCsv ([string]$c) }
        if ($row.Count -lt $header.Count) {
            $cells += @(('') * ($header.Count - $row.Count))
        }
        $sw.WriteLine(($cells -join ','))
    }
} finally {
    $sw.Close()
}

# ══════════════════════════════════════════════════════════════════════════════
#  optional Excel export (COM-based, best-effort)
# ══════════════════════════════════════════════════════════════════════════════
if ($ExportXlsx) {
    $xlsxPath = [IO.Path]::ChangeExtension($OutputCsv, '.xlsx')
    Write-Host "  Exporting Excel workbook ... $xlsxPath"
    try {
        $excel = New-Object -ComObject Excel.Application -ErrorAction Stop
        $excel.Visible = $false
        $wb = $excel.Workbooks.Open((Resolve-Path -LiteralPath $OutputCsv).Path)
        $wb.SaveAs($xlsxPath, 51)   # 51 = xlOpenXMLWorkbook (.xlsx)
        $wb.Close($false)
        $excel.Quit()
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel) | Out-Null
        Write-Host '  Excel export done.' -ForegroundColor Green
    } catch {
        Write-Warning "  Could not export xlsx (is Excel installed?): $($_.Exception.Message)"
    }
}

# ══════════════════════════════════════════════════════════════════════════════
#  summary
# ══════════════════════════════════════════════════════════════════════════════
Write-Host ''
Write-Host "  Merged device inventory  -  $OutputCsv" -ForegroundColor Cyan
Write-Host ''
Write-Host ("    input file(s) ................: {0}" -f $inputFiles.Count)
Write-Host ("    raw collected rows ...........: {0}" -f ($allRows.Count))
Write-Host ("    duplicate rows collapsed .....: {0}" -f $duplicates)
Write-Host ("    rows without a serial ........: {0}" -f $noSerial.Count)
Write-Host ("    rows in the merged output ....: {0}" -f $out.Count)
Write-Host ''

if ($PivotOn -and $offset.ContainsKey($PivotOn)) {
    $pivotIdx = $offset[$PivotOn]
    $groups = $out | Group-Object { [string]$_[$pivotIdx] } | Sort-Object Count -Descending | Select-Object -First 12
    Write-Host ("    top {0} by {1}:" -f $groups.Count, $PivotOn) -ForegroundColor Green
    foreach ($g in $groups) {
        Write-Host ("      {0,4}  {1}" -f $g.Count, ($(if ([string]::IsNullOrWhiteSpace($g.Name)) { '(blank)' } else { $g.Name })))
    }
    Write-Host ''
}
