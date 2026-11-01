<#
.SYNOPSIS
    Collect asset data from one or more machines *right now*, over WinRM,
    using the same collector that the GPO runs at startup (gpo\agent-gpo.ps1).
    Useful before you reboot anything: press "collect" instead of "wait".

.DESCRIPTION
    For each computer given via -ComputerName (or from -ComputerListFile):
      1) powershell is invoked remotely over WinRM,
      2) the content of agent-gpo.ps1 is executed IN the remote session with
         the same -Share / -Folder parameters the GPO agent uses,
      3) the remote device appends its row to <Share>\<Folder>\device_inventory.csv,
      4) console output is reported per machine (success / skip / failure).

    The agent's own duplicate-serial guard means re-collecting a machine that
    already reported (e.g. at boot earlier today) is a cheap no-op: it either
    exits silently or adds a row that Merge-DeviceData.ps1 will collapse.

    Prereqs:
      * WinRM enabled on the targets   (start winrm / gpedit set it up).
      * Caller is local administrator on the targets (Domain Admin works),
        or pass -Credential with an account that is.
      * The central share is reachable from the targets (not from you).

.EXAMPLE
    .\collect-anywhere.ps1 -ComputerName NEMRA1-DC1

.EXAMPLE
    .\collect-anywhere.ps1 -ComputerName NEMRA1-LT003, NEMRA1-LT004 `
                           -Share '\\SRVFILE01\AssetInventory$'
#>
[CmdletBinding()]
param(
    # One or more machines to collect from immediately.
    [Parameter(Mandatory = $true, ParameterSetName = 'ByName')]
    [string[]]$ComputerName,

    # A text file, one hostname per line (# comments allowed).
    [Parameter(Mandatory = $true, ParameterSetName = 'FromFile')]
    [string]$ComputerListFile,

    # Central inventory share, same as the GPO agent writes to ($env:ASSET_SHARE
    # is honored the same way).
    [string]$Share = $env:ASSET_SHARE,

    # Sub-folder of the share (per-department collections).
    [string]$Folder = 'DeviceData',

    # Local path of agent-gpo.ps1 (its content is pushed over WinRM).
    [string]$AgentPath,

    # Optional explicit credential; defaults to your current identity.
    [System.Management.Automation.PSCredential]$Credential
)

$ErrorActionPreference = 'Stop'

# ── resolve inputs ────────────────────────────────────────────────────────────
if ($PSCmdlet.ParameterSetName -eq 'FromFile') {
    if (-not (Test-Path -LiteralPath $ComputerListFile)) {
        throw "Computer list file not found: $ComputerListFile"
    }
    $ComputerName = Get-Content -LiteralPath $ComputerListFile |
        Where-Object { $_ -and $_ -notmatch '^\s*#' } |
        ForEach-Object { $_.Trim() }
}
if (-not $Share) {
    throw 'No share given - pass -Share or set $env:ASSET_SHARE.'
}
if (-not $AgentPath) {
    $AgentPath = Join-Path $PSScriptRoot 'agent-gpo.ps1'
}
if (-not (Test-Path -LiteralPath $AgentPath)) {
    throw "agent script not found: $AgentPath"
}
$agentContent = Get-Content -LiteralPath $AgentPath -Raw -Encoding UTF8

Write-Host ''
Write-Host '  Snipe-IT GPO Asset Inventory - collect now' -ForegroundColor Cyan
Write-Host '  ==========================================' -ForegroundColor Cyan
Write-Host "  agent source .........: $AgentPath"
Write-Host "  central share ........: $Share"
Write-Host "  folder ...............: $Folder"
Write-Host "  machines .............: $($ComputerName.Count)"
Write-Host ''

# ── per-machine collection ────────────────────────────────────────────────────
$exchangeOk = @()
$exchangeFailed = @()
$startedAt = Get-Date

foreach ($c in $ComputerName) {
    Write-Host "  -> $c ..." -ForegroundColor Cyan
    try {
        $invokeParams = @{
            ComputerName = $c
            ScriptBlock  = [scriptblock]::Create($agentContent)
            ArgumentList = $Share, $Folder
            ErrorAction  = 'Stop'
        }
        if ($Credential) { $invokeParams.Credential = $Credential }

        $remoteOut = Invoke-Command @invokeParams
        foreach ($line in @($remoteOut)) {
            if ($line) { Write-Host "     $line" -ForegroundColor DarkGray }
        }
        $exchangeOk += $c
        Write-Host '     OK' -ForegroundColor Green
    } catch {
        $exchangeFailed += $c
        Write-Host "     FAILED: $($_.Exception.Message)" -ForegroundColor Red
    }
}

# ── report ────────────────────────────────────────────────────────────────────
$duration = (Get-Date) - $startedAt
Write-Host ''
Write-Host ('  done in {0:n1}s   collected: {1}   failed: {2}' -f $duration.TotalSeconds, $exchangeOk.Count, $exchangeFailed.Count) -ForegroundColor Cyan
if ($exchangeFailed) {
    Write-Host '  failed machines:' -ForegroundColor Yellow
    foreach ($f in $exchangeFailed) { Write-Host "    $f" -ForegroundColor Yellow }
}
Write-Host ''
Write-Host '  Central CSV: ' -NoNewline
Write-Host '(share)\DeviceData\device_inventory.csv' -ForegroundColor Cyan
Write-Host '  Roll up with Merge-DeviceData.ps1 next.' -ForegroundColor Gray
Write-Host ''
