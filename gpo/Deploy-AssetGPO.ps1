<#
.SYNOPSIS
    Set up (or remove) the Active Directory side of the GPO-based asset
    collection:  central hidden file share  ->  SysVol script distribution  ->
    GPO with a machine Startup script  ->  GPO link.

.DESCRIPTION
    Run ON a Domain Controller (or an RSAT machine) with Domain Admin rights.

    What it does when run with defaults:

      1) Creates a central, hidden share  \\THIS-SERVER\AssetInventory$
         (NTFS folder + SMB share + ACLs:  Domain Computers = Change on the
         share, Modify on NTFS) so a server running agent-gpo.ps1 as Local
         SYSTEM can append its device row.
         Default THIS-SERVER = the machine the script runs on. To point the
         GPO at a share already hosted elsewhere (a dedicated file server)
         use -SkipShare together with -ShareUNC.
      2) Copies gpo\agent-gpo.ps1 and gpo\Launcher.bat into the GPO's
         SysVol   ...\Machine\Scripts\Startup\   folder.
         .bat files get CRLF line endings (they are distributed via SYSVOL).
      3) Registers the machine Startup script Launcher.bat:
           * the GPO's  ...\Machine\Scripts\scripts.ini
           * the registry hooks the Group Policy client-side extension reads
             (both  Group Policy\Scripts  and  Group Policy\State\Machine\Scripts)
      4) Creates (or reuses) the GPO and links it to <DomainRoot>.

    The -Remove switch unlinks/deletes the GPO and unregisters the scripts,
    but is refused unless -ForceRemove is passed as well (double confirmation;
    the GPO it manages is only ever the one named -GpoName, never an existing
    domain GPO).
    The share itself is only deleted when -DeleteShare is also passed.

.NOTES
    Why a .cmd wrapper instead of a PowerShell script in the GP "PowerShell
    Scripts" tab? The GPO honors whatever PowerShell execution policy the
    machine has; SysVol is a network source, so an AllSigned domain would
    reject the unsigned .ps1 (RemoteSigned flags network files). Launcher.bat
    calls powershell.exe with an explicit -ExecutionPolicy Bypass instead.

.EXAMPLE
    PS> .\Deploy-AssetGPO.ps1
    Default deployment: share on this DC, GPO linked at the domain root.

.EXAMPLE
    PS> .\Deploy-AssetGPO.ps1 -SkipShare -ShareUNC "\\SRVFILE01\AssetInventory$"
    Use a share that already exists on a file server.
#>
#Requires -Modules ActiveDirectory, GroupPolicy
[CmdletBinding()]
param(
    # SMB share name; ending in '$' keeps it out of net view.
    [string]$ShareName = 'AssetInventory$',

    # Local NTFS folder backing the share — only used when the script creates
    # the share (i.e. -SkipShare was NOT passed).
    [string]$SharePath = 'C:\Shares\AssetInventory',

    # GPO display name to create / reuse.
    [string]$GpoName = 'Snipe-IT Asset Collection',

    # Distinguished Name where the GPO is linked. Default: domain root
    # (i.e. every domain-joined computer). Narrow it to an OU later.
    [string]$DomainRoot,

    # Use when the central share already lives somewhere else:
    # e.g.  \\SRVFILE01\AssetInventory$  - the script skips creation and just
    # verifies reachability.
    [string]$ShareUNC,

    # The share is managed elsewhere; only verify its presence.
    [switch]$SkipShare,

    # Print the exact icacls / New-SmbShare commands instead of running them.
    [switch]$WhatShare,

    # Tear the deployment down (GPO + link + script registrations).
    [switch]$Remove,

    # Second, explicit confirmation for -Remove. Removal is refused unless
    # BOTH switches are passed, so no stray flag can delete the GPO.
    [switch]$ForceRemove,

    # With -Remove: also delete the local share and its folder.
    [switch]$DeleteShare,

    # Folder containing agent-gpo.ps1 + Launcher.bat (default: the folder this
    # script lives in).
    [string]$ScriptSource
)

$ErrorActionPreference = 'Stop'

# ── Script location ───────────────────────────────────────────────────────────
if (-not $ScriptSource) {
    $ScriptSource = Split-Path -Parent $MyInvocation.MyCommand.Path
}
$agentScript  = Join-Path $ScriptSource 'agent-gpo.ps1'
$launchScript = Join-Path $ScriptSource 'Launcher.bat'
foreach ($f in @($agentScript, $launchScript)) {
    if (-not (Test-Path -LiteralPath $f)) { throw "Required file missing: $f" }
}

# ── Resolve domain + share UNC ────────────────────────────────────────────────
Write-Host ''
Write-Host '  Snipe-IT GPO Asset Inventory - deploy' -ForegroundColor Cyan
Write-Host '  ========================================' -ForegroundColor Cyan
Write-Host ''

$adDomain = Get-ADDomain
if (-not $DomainRoot) {
    $DomainRoot = $adDomain.DistinguishedName
}
if (-not $ShareUNC) {
    $ShareUNC = "\\$env:COMPUTERNAME\$ShareName"
}
$ShareUNC = $ShareUNC.TrimEnd('\')

Write-Host "  Share ......................: $ShareUNC"
Write-Host "  GPO ........................: $GpoName"
Write-Host "  Domain (link target) .......: $DomainRoot"
Write-Host ''

# ══════════════════════════════════════════════════════════════════════════════
#  remove
# ══════════════════════════════════════════════════════════════════════════════
if ($Remove) {
    if (-not $ForceRemove) {
        Write-Warning 'Removal refused: -Remove must be combined with -ForceRemove.'
        Write-Warning 'This two-switch rule ensures nothing in the domain is ever deleted by accident.'
        Write-Warning "Verify first:  Get-GPO -Name '$GpoName'"
        exit 1
    }

    Write-Host '  [remove] unlinking and deleting GPO (if it exists)...' -ForegroundColor Yellow
    $existing = Get-GPO -Name $GpoName -ErrorAction SilentlyContinue
    if ($existing) {
        Remove-GPO -Id $existing.Id -Confirm:$false
        Write-Host "             removed GPO '$GpoName'" -ForegroundColor Yellow
    } else {
        Write-Host "             GPO '$GpoName' not found - nothing to remove" -ForegroundColor DarkGray
    }

    Write-Host '  [remove] clearing machine startup script registry state...' -ForegroundColor Yellow
    foreach ($key in @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Group Policy\Scripts\Startup',
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Group Policy\State\Machine\Scripts\Startup'
    )) {
        if (Test-Path -LiteralPath $key) {
            Remove-Item -LiteralPath $key -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    if ($DeleteShare) {
        Write-Host '  [remove] removing SMB share...' -ForegroundColor Yellow
        Get-SmbShare -Name $ShareName -ErrorAction SilentlyContinue |
            Remove-SmbShare -Confirm:$false -ErrorAction SilentlyContinue
        if (Test-Path -LiteralPath $SharePath) {
            Remove-Item -LiteralPath $SharePath -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    Write-Host ''
    Write-Host '  Removed. Run  gpupdate /target:computer /force  and reboot a machine' -ForegroundColor Green
    Write-Host '  to see it stop reporting.' -ForegroundColor Green
    Write-Host ''
    exit 0
}

# ══════════════════════════════════════════════════════════════════════════════
#  share
# ══════════════════════════════════════════════════════════════════════════════
if ($SkipShare) {
    Write-Host "  [1/4] Central share ($ShareUNC) ... skipping creation (-SkipShare)" -ForegroundColor Cyan
    if (-not (Test-Path -LiteralPath $ShareUNC)) {
        throw "Central share $ShareUNC is not accessible to this machine."
    }
    Write-Host '             share reachable' -ForegroundColor DarkGray
} else {
    Write-Host "  [1/4] Central share ($ShareUNC) ..." -ForegroundColor Cyan

    if (-not (Test-Path -LiteralPath $SharePath)) {
        if ($WhatShare) {
            Write-Host "    (dry-run) New-Item -Path $SharePath -ItemType Directory -Force" -ForegroundColor DarkGray
        } else {
            New-Item -Path $SharePath -ItemType Directory -Force | Out-Null
        }
    }

    # NTFS:  Domain Computers -> Modify  (computer accounts write the CSV row)
    #        Administrators / SYSTEM -> FullControl
    $ntfsGrants = @(
        'Domain Computers:(OI)(CI)M',
        'BUILTIN\Administrators:(OI)(CI)F',
        'NT AUTHORITY\SYSTEM:(OI)(CI)F'
    )
    foreach ($grant in $ntfsGrants) {
        if ($WhatShare) {
            Write-Host "    (dry-run) icacls `"$SharePath`" /grant `"$grant`" /T" -ForegroundColor DarkGray
        } else {
            & icacls "$SharePath" /grant "$grant" /T | Out-Null
        }
    }

    $existingShare = Get-SmbShare -Name $ShareName -ErrorAction SilentlyContinue
    if (-not $existingShare) {
        if ($WhatShare) {
            Write-Host "    (dry-run) New-SmbShare -Name $ShareName -Path $SharePath -ReadAccess 'Authenticated Users'" -ForegroundColor DarkGray
            Write-Host "    (dry-run) Grant-SmbShareAccess $ShareName 'Domain Computers' Change / 'BUILTIN\Administrators' Full" -ForegroundColor DarkGray
        } else {
            New-SmbShare -Name $ShareName -Path $SharePath -ReadAccess 'Authenticated Users' | Out-Null
            Grant-SmbShareAccess -Name $ShareName -AccountName 'Domain Computers'      -AccessRight Change -Force | Out-Null
            Grant-SmbShareAccess -Name $ShareName -AccountName 'BUILTIN\Administrators' -AccessRight Full   -Force | Out-Null
            Write-Host '             share created' -ForegroundColor Green
        }
    } else {
        Write-Host "             SMB share '$ShareName' already exists - reused" -ForegroundColor DarkGray
    }

    if (-not (Test-Path -LiteralPath $ShareUNC)) {
        throw "Central share $ShareUNC is not accessible to this machine."
    }
}
Write-Host ''

# ══════════════════════════════════════════════════════════════════════════════
#  GPO
# ══════════════════════════════════════════════════════════════════════════════
Write-Host "  [2/4] GPO '$GpoName' ..." -ForegroundColor Cyan

$gpo = Get-GPO -Name $GpoName -ErrorAction SilentlyContinue
if (-not $gpo) {
    $gpo = New-GPO -Name $GpoName -Comment 'Runs Launcher.bat at machine startup; agent-gpo.ps1 appends the device row to the central asset CSV on the inventory share.'
    Write-Host "             created ($($gpo.Id))" -ForegroundColor Green
} else {
    Write-Host "             already exists - reused ($($gpo.Id))" -ForegroundColor DarkGray
}
Write-Host ''

# ══════════════════════════════════════════════════════════════════════════════
#  SysVol script distribution + scripts.ini + machine registry state
# ══════════════════════════════════════════════════════════════════════════════
Write-Host '  [3/4] SysVol script files ...' -ForegroundColor Cyan

$sysvolPolicy = "\\$($adDomain.DNSRoot)\SYSVOL\$($adDomain.DNSRoot)\Policies\{$($gpo.Id)}"
$sysvolStart  = Join-Path $sysvolPolicy 'Machine\Scripts\Startup'

if (-not (Test-Path -LiteralPath $sysvolStart)) {
    New-Item -Path $sysvolStart -ItemType Directory -Force | Out-Null
}

# Batch files going to SysVol must have CRLF line endings; .ps1 files are
# re-emitted with a UTF-8 BOM so Windows PowerShell 5.x reads them correctly.
function Write-SysVolFile {
    param([string]$SourceFile, [string]$DestinationFile, [switch]$WithBom)
    $content  = Get-Content -LiteralPath $SourceFile -Raw -Encoding UTF8
    $content  = $content -replace "`r?`n", "`r`n"
    $encoding = if ($WithBom) { New-Object System.Text.UTF8Encoding $true }
                else          { New-Object System.Text.UTF8Encoding $false }
    [System.IO.File]::WriteAllText($DestinationFile, $content, $encoding)
}

Write-SysVolFile -SourceFile $agentScript  -DestinationFile (Join-Path $sysvolStart 'agent-gpo.ps1') -WithBom
Write-SysVolFile -SourceFile $launchScript -DestinationFile (Join-Path $sysvolStart 'Launcher.bat')
Write-Host "             -> $sysvolStart" -ForegroundColor DarkGray

#  ── scripts.ini: register Launcher.bat as  startup script slot 0  ────────────
$scriptsIniPath = Join-Path $sysvolPolicy 'Machine\Scripts\scripts.ini'

if (Test-Path -LiteralPath $scriptsIniPath) {
    $iniLines = [System.IO.File]::ReadAllLines($scriptsIniPath)  # keep anything already there
    # Drop lines belonging to Launcher.bat's previous slots, then re-add slot 0.
    $iniLines = @(
        $iniLines | Where-Object { $_ -notmatch '^0CmdLine=' } |
                   Where-Object { $_ -notmatch '^0Parameters=' }
    )
} else {
    $iniLines = @()
}

$iniContent = [System.Collections.Generic.List[string]]::new()
foreach ($line in $iniLines) { $iniContent.Add($line) }
if (-not ($iniContent -contains '[ScriptsConfig]')) {
    $iniContent.Add('[ScriptsConfig]')
    $iniContent.Add('StartScripts=1')
    $iniContent.Add('ShutScripts=0')
}
if (-not ($iniContent -contains '[Startup]')) { $iniContent.Add('[Startup]') }
$iniContent.Add('0CmdLine=Launcher.bat')
$iniContent.Add('0Parameters=')
[System.IO.File]::WriteAllText($scriptsIniPath, ($iniContent -join "`r`n") + "`r`n")

#  ── machine registry state consumed by the GP client-side extension ──────────
$execTimeZero = [byte[]]((,0) * 16)
foreach ($root in @(
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Group Policy\Scripts\Startup',
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Group Policy\State\Machine\Scripts\Startup'
)) {
    if (-not (Test-Path -LiteralPath $root)) {
        New-Item -Path $root -ItemType Directory -Force | Out-Null
    }
    $slot = New-Item -Path (Join-Path $root '0\0') -ItemType Directory -Force
    Set-ItemProperty -Path $slot.PSPath -Name 'Script'     -Value 'Launcher.bat' -Type String
    Set-ItemProperty -Path $slot.PSPath -Name 'Parameters' -Value ''             -Type String
    Set-ItemProperty -Path $slot.PSPath -Name 'ExecTime'   -Value $execTimeZero  -Type Binary
}
Write-Host '             startup script slot 0 -> Launcher.bat' -ForegroundColor DarkGray
Write-Host ''

# ══════════════════════════════════════════════════════════════════════════════
#  link
# ══════════════════════════════════════════════════════════════════════════════
Write-Host "  [4/4] GPO link to $DomainRoot ..." -ForegroundColor Cyan

$inheritance = Get-GPInheritance -Target $DomainRoot
$linkedHere  = @($inheritance.GpoLinks | Where-Object { $_.GpoId -eq $gpo.Id })
if (-not $linkedHere) {
    New-GPLink -Target $DomainRoot -Name $GpoName -LinkEnabled Yes -Order 1 | Out-Null
    Write-Host '             linked' -ForegroundColor Green
} else {
    Write-Host '             link already exists' -ForegroundColor DarkGray
}
Write-Host ''

# ══════════════════════════════════════════════════════════════════════════════
#  verify + next steps
# ══════════════════════════════════════════════════════════════════════════════
Write-Host '  Verify ...' -ForegroundColor Cyan

$reportFile = Join-Path $env:TEMP 'asset-gpo-report.xml'
Get-GPOReport -Name $GpoName -ReportType Xml -Path $reportFile
$xmlReport    = [xml](Get-Content -LiteralPath $reportFile -Raw)
$hasLauncher  = $xmlReport.OuterXml -match 'Launcher\.bat'
$hasAgent     = (Test-Path (Join-Path $sysvolStart 'agent-gpo.ps1'))
Write-Host ("             GPO references the launcher ....... : {0}" -f ($(if ($hasLauncher) {'yes'} else {'NO - manual check needed'}))) -ForegroundColor $(if ($hasLauncher) {'Green'} else {'Yellow'})
Write-Host ("             agent-gpo.ps1 present in SysVol .. : {0}" -f ($(if ($hasAgent)   {'yes'} else {'NO - copy failed'})))          -ForegroundColor $(if ($hasAgent)   {'Green'} else {'Red'})

Write-Host ''
Write-Host '  Next steps:' -ForegroundColor Green
Write-Host '  1. On a representative machine (or collect-anywhere.ps1 for a live sample):' -ForegroundColor White
Write-Host '         gpupdate /target:computer /force' -ForegroundColor Gray
Write-Host '         reboot' -ForegroundColor Gray
Write-Host '  2. Test the collection share:' -ForegroundColor White
Write-Host "         $ShareUNC\DeviceData\device_inventory.csv" -ForegroundColor Cyan
Write-Host '  3. Produce an Excel-ready rollup:' -ForegroundColor White
Write-Host '         .\Merge-DeviceData.ps1 -SourceFolder ' (Split-Path $ShareUNC -Parent) ' -ExportXlsx' -ForegroundColor Gray
Write-Host ''
