# ==============================================================================
# Snipe-IT Asset Inventory Agent — GPO edition (Windows)
# ==============================================================================
#
# Radius of change vs. static\agent.ps1:
#   * Designed to run hidden at computer STARTUP via Active Directory GPO.
#   * Runs as LOCAL SYSTEM -> has NO user session and NO interactive prompt.
#   * No onboarding session code, no /api call, no ONBOARD_URL needed.
#   * Writes one flat CSV row to a central network share (Excel-compatible).
#   * ONE row per device - the script appends only if this serial number is
#     not already recorded (idempotent re-runs).
#
# File share contract (see ../Deploy-AssetGPO.ps1, which creates this share):
#   \\SERVER\AssetInventory$
#     agent-gpo.ps1       this script (per-device "last seen" copy)
#     DeviceData.csv      central device inventory (one row per device)
#     SalesLaptops.csv    per-OU example same layout (folder per report scope)
#     Collected.json      optional: the web-ready JSON version of this payload
#
# ==============================================================================

[CmdletBinding()]
param(
    # Central share root. Override:  -Share '\\SRV\AssetInventory$'
    #                                or $env:ASSET_SHARE
    [string]$Share = $env:ASSET_SHARE,

    # Folder *inside* the share for this collection run (per-OU/per-department).
    # Default: 'DeviceData' (the all-devices report). Example: 'SalesLaptops'.
    [string]$Folder = $env:ASSET_GPO_FOLDER,

    # Also drop a .json copy (same schema as static\agent.ps1 POST body).
    [switch]$AlsoJson,

    # CSV lock retry (network share contention / Excel has the file open).
    [int]$LockRetries = 5,
    [int]$LockWaitMs  = 500
)

$ErrorActionPreference = 'SilentlyContinue'
# Startup scripts run whatever policy the machine enforces; allow ourselves.
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force -ErrorAction SilentlyContinue

$Script:AgentVersion = '1.0-gpo'
$Script:IsGpoRun = (-not [Environment]::UserInteractive)
# ==============================================================================
# Shared collector helpers (same detection logic as static\agent.ps1)
# ==============================================================================

function Safe-Get {
    param([scriptblock]$Block, $Default = $null)
    try { $result = & $Block; if ($null -ne $result) { $result } else { $Default } }
    catch { $Default }
}

function _EscapeCsv {
    param([string]$Value)
    if ([string]::IsNullOrEmpty($Value)) { return '' }
    # CSV quoting per RFC 4180
    if ($Value -match '[",\r\n]') {
        $Value = '"' + $Value.Replace('"', '""') + '"'
    }
    return $Value
}

# ==============================================================================
# SECTION 1 — HARDWARE
# ==============================================================================

$cs    = Safe-Get { Get-CimInstance Win32_ComputerSystem }
$bios  = Safe-Get { Get-CimInstance Win32_BIOS }
$os    = Safe-Get { Get-CimInstance Win32_OperatingSystem }
$cpus  = Safe-Get { Get-CimInstance Win32_Processor }
$cpu   = if ($cpus) { $cpus | Select-Object -First 1 } else { $null }
$disks = Safe-Get { Get-CimInstance Win32_DiskDrive }

# Running as SYSTEM at boot: there is no logged-in user. Prefer the console
# session owner (via Explorer.exe owner), else fall back to Device Owner /
# CIM owner, else "System".
function _Get-ConsoleUser {
    # 1) WMI Win32_ComputerSystem UserName (populated only while someone is logged on)
    if ($cs -and $cs.UserName) { return $cs.UserName }

    # 2) Owner of the interactive Explorer.exe process (works after fast user switching too)
    $explorer = Safe-Get {
        Get-CimInstance Win32_Process -Filter "Name='explorer.exe'" |
            Select-Object -First 1
    }
    if ($explorer) {
        $ownerInfo = Safe-Get { $explorer | Invoke-CimMethod -MethodName GetOwner }
        if ($ownerInfo -and $ownerInfo.User) {
            $domain = if ($ownerInfo.Domain) { "$($ownerInfo.Domain)\" } else { '' }
            return "$domain$($ownerInfo.User)"
        }
    }

    # 3) Registered device owner (Windows 10+ / aadjoin-aware)
    $registeredOwner = Safe-Get {
        (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion' -ErrorAction SilentlyContinue).RegisteredOwner
    }
    if ($registeredOwner) { return $registeredOwner }

    # 4) Fallback — the collection ran under SYSTEM
    return $env:COMPUTERNAME + '$'
}
$currentUser = _Get-ConsoleUser

# Physical RAM — sum all sticks for the true installed amount
$ramGB = Safe-Get {
    $sticks = Get-CimInstance Win32_PhysicalMemory
    [math]::Round(($sticks | Measure-Object -Property Capacity -Sum).Sum / 1GB, 1)
}

# Aggregate disks into one summary string: 3 slots -> "HDD 256.0GB | SSD 1024.0GB"
$diskSummary = ''
$diskSlots = @()
if ($disks) {
    $slots = 0
    foreach ($d in $disks) {
        if ($slots -ge 3) { break }
        $slots++
        $diskType = 'Unknown'
        if ($d.MediaType -match 'SSD|Solid State')    { $diskType = 'SSD' }
        elseif ($d.MediaType -match 'HDD|Fixed|External') { $diskType = 'HDD' }
        elseif ($d.MediaType) { $diskType = $d.MediaType }

        $msftDisk = Safe-Get {
            Get-PhysicalDisk -ErrorAction SilentlyContinue |
                Where-Object { $_.SerialNumber -eq $d.SerialNumber } |
                Select-Object -First 1
        }
        if ($msftDisk -and $msftDisk.MediaType) {
            $diskType = switch ($msftDisk.MediaType) {
                'SSD' { 'SSD' } 'HDD' { 'HDD' } 'SCM' { 'SCM' } default { $diskType }
            }
        }
        $sizeGb = if ($d.Size) { [math]::Round($d.Size / 1GB, 1) } else { 0 }
        $diskSlots += "${diskType} ${sizeGb}GB"
        $diskObjs  += @{ name = $d.Model; size_gb = $sizeGb; type = $diskType }
    }
    $diskSummary = $diskSlots -join ' | '
}

# IPv4 addresses from active Wi-Fi and Ethernet adapters only
$ipFlat = ''
$macAddresses = ''
$nics = Safe-Get { Get-NetAdapter -Physical -ErrorAction SilentlyContinue |
                   Where-Object { $_.Status -eq 'Up' } }
if ($nics) {
    $ipParts = @()
    $macParts = @()
    foreach ($nic in $nics) {
        $adapterInfo = "$($nic.Name) $($nic.InterfaceDescription) $($nic.PhysicalMediaType)"
        $connType = if ($adapterInfo -match '(?i)802\.3|ethernet') { 'Ethernet' }
                    elseif ($adapterInfo -match '(?i)802\.11|wireless|wi-?fi') { 'Wi-Fi' }
                    else { $null }
        if (-not $connType) { continue }
        if ($nic.MacAddress) { $macParts += $nic.MacAddress }

        $addresses = Safe-Get {
            Get-NetIPAddress -InterfaceIndex $nic.ifIndex -AddressFamily IPv4 `
                             -ErrorAction SilentlyContinue
        }
        foreach ($a in @($addresses)) {
            if ($a -and $a.IPAddress) {
                $ipParts += "$connType($($nic.Name))=$($a.IPAddress)"
            }
        }
    }
    $ipFlat       = $ipParts -join "; "
    $macAddresses = $macParts -join "; "
}

# ==============================================================================
# SECTION 2 — WINDOWS ACTIVATION
# ==============================================================================

$licenseStatusMap = @{
    0 = "Unlicensed"
    1 = "Activated"
    2 = "Grace period (Out-of-Box)"
    3 = "Grace period (Out-of-Tolerance)"
    4 = "Grace period (Non-Genuine)"
    5 = "Notification mode - not activated"
    6 = "Extended grace period"
}

$winStatus      = 'Unknown'
$winProductId   = ''
$winPartialKey  = ''
$winProductName = ''

$slp = Safe-Get {
    Get-CimInstance SoftwareLicensingProduct -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match 'Windows' -and $_.PartialProductKey } |
        Select-Object -First 1
}
if ($slp) {
    $code_int = [int]$slp.LicenseStatus
    $winStatus      = if ($licenseStatusMap.ContainsKey($code_int)) { $licenseStatusMap[$code_int] } else { "Unknown ($code_int)" }
    $winProductId   = if ($slp.Name)          { $slp.Name }          else { '' }
    $winPartialKey  = if ($slp.PartialProductKey) { $slp.PartialProductKey } else { '' }
}

# ==============================================================================
# SECTION 3 — SOFTWARE INVENTORY
# ==============================================================================

$regPaths = @(
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\Software\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*'
)
$allInstalled = @()
foreach ($p in $regPaths) {
    $entries = Safe-Get { Get-ItemProperty $p -ErrorAction SilentlyContinue } -Default @()
    if ($entries) { $allInstalled += $entries }
}

function Find-InstalledApp {
    param([string[]]$Patterns, [string]$FallbackPath = $null)
    $match = $allInstalled | Where-Object {
        $dn = $_.DisplayName
        if (-not $dn) { return $false }
        foreach ($p in $Patterns) { if ($dn -match $p) { return $true } }
        return $false
    } | Sort-Object { $_.DisplayVersion } -Descending | Select-Object -First 1
    if ($match) {
        return @{ installed=$true; version=$match.DisplayVersion; method='registry' }
    }
    if ($FallbackPath -and (Test-Path $FallbackPath)) {
        $ver = Safe-Get { (Get-Item $FallbackPath).VersionInfo.ProductVersion }
        return @{ installed=$true; version=$ver; method='filesystem' }
    }
    return @{ installed=$false; version=$null; method='not_found' }
}

function Find-ByService {
    param([string]$ServiceName, [string[]]$FallbackPaths = @())
    $svc = Safe-Get { Get-Service -Name $ServiceName -ErrorAction SilentlyContinue }
    if ($svc) {
        $exe = Safe-Get {
            $wmiSvc = Get-CimInstance Win32_Service -Filter "Name='$ServiceName'" -ErrorAction SilentlyContinue
            if ($wmiSvc -and $wmiSvc.PathName) {
                $exePath = ($wmiSvc.PathName -replace '"','').Split(' ')[0]
                if (Test-Path $exePath) { (Get-Item $exePath).VersionInfo.ProductVersion }
            }
        }
        return @{ installed=$true; version=$exe; method='service' }
    }
    foreach ($p in $FallbackPaths) {
        if (Test-Path $p) {
            $ver = Safe-Get { (Get-Item $p).VersionInfo.ProductVersion }
            return @{ installed=$true; version=$ver; method='filesystem' }
        }
    }
    return @{ installed=$false; version=$null; method='not_found' }
}

$chromePaths = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe"
)
$fortiPaths = @(
    "$env:ProgramFiles\Fortinet\FortiClient\FortiClient.exe",
    "${env:ProgramFiles(x86)}\Fortinet\FortiClient\FortiClient.exe"
)
$teamsPaths = @(
    "$env:LOCALAPPDATA\Microsoft\Teams\current\Teams.exe"
)
$sccmPaths = @(
    "$env:WinDir\CCM\CcmExec.exe",
    "$env:WinDir\ccmsetup\ccmsetup.exe"
)
$intunePaths = @(
    "$env:ProgramFiles\Microsoft Intune Management Extension\Microsoft.Management.Services.IntuneWindowsAgent.exe"
)
$officePaths = @(
    "$env:ProgramFiles\Microsoft Office\root\Office16\WINWORD.EXE",
    "${env:ProgramFiles(x86)}\Microsoft Office\root\Office16\WINWORD.EXE",
    "$env:ProgramFiles\Microsoft Office\Office16\WINWORD.EXE"
)
$vlcPaths = @(
    "$env:ProgramFiles\VideoLAN\VLC\vlc.exe",
    "${env:ProgramFiles(x86)}\VideoLAN\VLC\vlc.exe"
)

# Chrome
$chromeResult = Find-InstalledApp -Patterns @('^Google Chrome$') -FallbackPath $chromePaths[0]
if (-not $chromeResult.installed) {
    foreach ($p in $chromePaths) { if (Test-Path $p) {
        $chromeResult = @{ installed=$true; version=(Safe-Get{(Get-Item $p).VersionInfo.ProductVersion}); method='filesystem' }
        break
    }}
}
# FortiClient
$fortiResult = Find-InstalledApp -Patterns @('FortiClient') -FallbackPath $fortiPaths[0]
if (-not $fortiResult.installed) {
    $svc = Find-ByService -ServiceName 'FortiTray' -FallbackPaths $fortiPaths
    if ($svc.installed) { $fortiResult = $svc }
}
# Teams (new MSIX + classic)
$teamsResult = Find-InstalledApp -Patterns @('Microsoft Teams', '^Teams$') -FallbackPath $teamsPaths[0]
if (-not $teamsResult.installed) {
    $newTeams = Safe-Get { Get-AppxPackage -Name 'MSTeams' -ErrorAction SilentlyContinue | Select-Object -First 1 }
    if ($newTeams) {
        $teamsResult = @{ installed=$true; version=$newTeams.Version; method='appx' }
    }
}
if (-not $teamsResult.installed) {
    $found = Safe-Get {
        Get-ChildItem "$env:ProgramFiles\WindowsApps" -Filter 'MSTeams*' -Directory -ErrorAction SilentlyContinue |
            Select-Object -First 1
    }
    if ($found) { $teamsResult = @{ installed=$true; version=$null; method='filesystem' } }
}
# SCCM
$sccmResult = Find-ByService -ServiceName 'CcmExec' -FallbackPaths $sccmPaths
if (-not $sccmResult.installed -and (Test-Path "$env:WinDir\CCM")) {
    $sccmResult = @{ installed=$true; version=$null; method='filesystem' }
}
# Intune
$intuneResult = Find-ByService -ServiceName 'IntuneManagementExtension' -FallbackPaths $intunePaths
if (-not $intuneResult.installed) {
    $intuneResult = Find-InstalledApp -Patterns @('Microsoft Intune Management Extension', 'Intune Management Extension')
}
if (-not $intuneResult.installed) {
    $mdm = Safe-Get {
        $t = Get-ScheduledTask -TaskPath '\Microsoft\Windows\EnterpriseMgmt\' -ErrorAction SilentlyContinue
        if ($t) { $true } else { $false }
    }
    if ($mdm) { $intuneResult = @{ installed=$true; version=$null; method='mdm_enrollment' } }
}
# Office 2021 / Microsoft 365
$officeResult = Find-InstalledApp -Patterns @(
    'Microsoft Office.*2021'
    'Microsoft 365'
    'Microsoft Office LTSC 2021'
    'Microsoft Office Professional'
) -FallbackPath $officePaths[0]
if (-not $officeResult.installed) {
    foreach ($p in $officePaths) {
        if (Test-Path $p) {
            $officeResult = @{
                installed = $true
                version   = Safe-Get { (Get-Item $p).VersionInfo.ProductVersion }
                method    = 'filesystem'
            }
            break
        }
    }
}
# VLC
$vlcResult = Find-InstalledApp -Patterns @('VLC media player', '^VLC$') -FallbackPath $vlcPaths[0]
if (-not $vlcResult.installed) {
    foreach ($p in $vlcPaths) { if (Test-Path $p) {
        $vlcResult = @{ installed=$true; version=(Safe-Get{(Get-Item $p).VersionInfo.ProductVersion}); method='filesystem' }
        break
    }}
}

function _SoftwareFlag {
    param($Result, [string]$Version)
    if ($Result.installed) {
        if ($Result.version) { "Yes ($($Result.version))" } else { 'Yes' }
    } elseif ($Version) {
        $Version   # e.g. SCCM version discovered via the service exe
    } else {
        'No'
    }
}

$swChrome      = _SoftwareFlag $chromeResult
$swForti       = _SoftwareFlag $fortiResult
$swTeams       = _SoftwareFlag $teamsResult
$swSccm        = _SoftwareFlag $sccmResult $sccmResult.version
$swIntune      = _SoftwareFlag $intuneResult $intuneResult.version
$swOffice      = _SoftwareFlag $officeResult
$swVlc         = _SoftwareFlag $vlcResult
$swList        = (@(
    if ($chromeResult.installed) { 'Google Chrome' }
    if ($fortiResult.installed)  { 'FortiClient' }
    if ($teamsResult.installed)  { 'Microsoft Teams' }
    if ($sccmResult.installed)   { 'SCCM' }
    if ($intuneResult.installed) { 'Intune' }
    if ($officeResult.installed) { 'Office 2021' }
    if ($vlcResult.installed)    { 'VLC' }
) | Where-Object { $_ }) -join ', '

# ==============================================================================
# SECTION 4 — DOMAIN / OU INFO (lets you pivot the CSV per department)
# ==============================================================================

$domainName     = Safe-Get { ([System.DirectoryServices.ActiveDirectory.Domain]::GetComputerDomain()).Name } -Default ''
$computerDomain = Safe-Get { (Get-CimInstance Win32_ComputerSystem).Domain } -Default ''

# OU lookup: ask AD where this computer object lives (works for any domain user,
# not just admins — Read access to the computer's own DN is always granted).
$ouDn = ''
try {
    $rootEntry = New-Object System.DirectoryServices.DirectoryEntry('LDAP://RootDSE')
    $nc = [string]$rootEntry.defaultNamingContext
    if ($nc) {
        $searcher = New-Object System.DirectoryServices.DirectorySearcher
        $searcher.SearchRoot = New-Object System.DirectoryServices.DirectoryEntry("LDAP://$nc")
        $searcher.Filter     = "(&(objectCategory=computer)(sAMAccountName=$env:COMPUTERNAME`$))"
        $found = $searcher.FindOne()
        if ($found) { $ouDn = [string]$found.Properties['distinguishedname'][0] }
    }
} catch { }

# ==============================================================================
# SECTION 5 — Payload + central write
# ==============================================================================

$nowString = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'

$row = [ordered]@{
    collected_at        = $nowString
    collection_method   = 'gpo-startup'
    hostname            = $env:COMPUTERNAME
    domain              = if ($domainName) { $domainName } else { $computerDomain }
    is_domain_joined    = if ($domainName) { 'Yes' } else { 'No' }
    username            = $currentUser
    serial_number       = if ($bios -and $bios.SerialNumber) { $bios.SerialNumber } else { 'N/A' }
    manufacturer        = if ($cs)   { $cs.Manufacturer }     else { '' }
    model               = if ($cs)   { $cs.Model }            else { '' }
    os_name             = if ($os)   { $os.Caption }          else { '' }
    os_version          = if ($os)   { $os.Version }          else { '' }
    os_arch             = if ($os)   { $os.OSArchitecture }   else { '' }
    cpu                 = if ($cpu)  { $cpu.Name }            else { '' }
    cpu_cores           = if ($cpu)  { [int]$cpu.NumberOfCores }  else { 0 }
    logical_processors  = if ($cpu)  { [int]$cpu.NumberOfLogicalProcessors } else { 0 }
    ram_gb              = $ramGB
    disk_summary        = $diskSummary
    ip_addresses        = $ipFlat
    mac_addresses       = $macAddresses
    ou                  = $ouDn
    win_activation_status    = $winStatus
    win_product_name         = $winProductId
    win_partial_key          = $winPartialKey
    office_installed    = if ($swOffice -eq 'No') { 'No' } else { 'Yes' }
    chrome_installed    = if ($swChrome -eq 'No') { 'No' } else { 'Yes' }
    vlc_installed       = if ($swVlc   -eq 'No') { 'No' } else { 'Yes' }
    forticlient_installed = if ($swForti -eq 'No') { 'No' } else { 'Yes' }
    teams_installed     = if ($swTeams -eq 'No') { 'No' } else { 'Yes' }
    sccm_installed      = if ($swSccm  -eq 'No') { 'No' } else { 'Yes' }
    intune_installed    = if ($swIntune -eq 'No') { 'No' } else { 'Yes' }
    software_list       = $swList
    office_version      = if ($officeResult.version) { $officeResult.version } else { '' }
    chrome_version      = if ($chromeResult.version) { $chromeResult.version } else { '' }
    vlc_version         = if ($vlcResult.version)   { $vlcResult.version }   else { '' }
    forticlient_version = if ($fortiResult.version) { $fortiResult.version } else { '' }
    teams_version       = if ($teamsResult.version) { $teamsResult.version } else { '' }
    sccm_version        = if ($sccmResult.version)  { $sccmResult.version }  else { '' }
    intune_version      = if ($intuneResult.version) { $intuneResult.version } else { '' }
    agent_version       = $Script:AgentVersion
}

$csvHeaderFields = @($row.Keys)
$csvValues       = foreach ($k in $csvHeaderFields) { _EscapeCsv ([string]$row[$k]) }
$csvLine         = $csvValues -join ','
$serialNumber    = $row['serial_number']

if (-not $Share) {
    Write-Warning 'ASSET_SHARE is not set - no central share, exiting.'
    exit 1
}
$Share = $Share.TrimEnd('\')
$targetFolder = Join-Path $Share $Folder
if (-not (Test-Path $targetFolder -PathType Container)) {
    Write-Warning "Target folder not found or not accessible: $targetFolder"
    exit 1
}

$csvFilePath  = Join-Path $targetFolder 'device_inventory.csv'
$jsonFilePath = Join-Path $targetFolder 'device_inventory.json'

Write-Host ""
Write-Host "  Snipe-IT GPO Inventory Agent $Script:AgentVersion" -ForegroundColor Cyan
Write-Host "  Target    : $csvFilePath"
Write-Host "  Device    : $($row['hostname']) / $($row['serial_number'])"
Write-Host ""

#  ── Check for duplicate: skip writing if this serial number already logged ────
#  Looked up by header name (not index) so the schema can grow safely. While the
#  file is locked by a reader (Excel) or another writer we just proceed — the
#  append-retry loop below handles contention, and Merge-DeviceData.ps1 does a
#  final per-serial dedupe at report time.
$alreadyRecorded = $false
try {
    if (Test-Path $csvFilePath) {
        $headerLine  = Get-Content $csvFilePath -TotalCount 1 -ErrorAction Stop
        $headerCols  = @($headerLine -split ',')
        $serialIndex = [array]::IndexOf($headerCols, 'serial_number')
        if ($serialIndex -ge 0) {
            $pattern = [regex]::Escape($row['serial_number'])
            $found   = Select-String -LiteralPath $csvFilePath -Pattern $pattern -ErrorAction Stop
            if ($found) { $alreadyRecorded = $true }
        }
    }
} catch {
    # Can't check (file locked / missing) - let the append attempt proceed.
}

if ($alreadyRecorded) {
    Write-Host "  Device $($row['hostname']) (serial $($row['serial_number'])) already collected - skipping." -ForegroundColor DarkGray
    exit 0
}

#  ── Append with a file-open retry: CSV left open in Excel will not corrupt data ─
$needsHeader = -not (Test-Path $csvFilePath)
$retry    = 0
$written  = $false
$lastErr  = $null
while (-not $written -and $retry -lt $LockRetries) {
    $retry++
    try {
        $stream = [System.IO.StreamWriter]::new($csvFilePath, $true, [System.Text.Encoding]::UTF8)
        # First writer on a fresh file lays down the header row. Two devices
        # racing on the very first write can each emit one — harmless, and
        # Merge-DeviceData.ps1 drops duplicate header lines on merge.
        if ($needsHeader) {
            $stream.WriteLine(($csvHeaderFields -join ','))
            $needsHeader = $false
        }
        $stream.WriteLine($csvLine)
        $stream.Close()
        $written = $true
    } catch {
        $lastErr = $_
        Write-Host "  Attempt $retry/$LockRetries failed: $($_.Exception.Message)" -ForegroundColor Yellow
        Start-Sleep -Milliseconds $LockWaitMs
    }
}

if ($written) {
    Write-Host "  Written: $csvFilePath" -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host "  ERROR: Could not write to '$csvFilePath' after $LockRetries attempts." -ForegroundColor Red
    Write-Host "  Last error: $($lastErr)" -ForegroundColor Red
    # Keep the payload locally as a fallback so support can grab it later.
    $localFile = Join-Path $env:TEMP "inventory-$($row['hostname'])-$(Get-Date -Format 'yyyyMMdd-HHmmss').csv"
    try { [System.IO.File]::WriteAllText($localFile, $csvLine + [Environment]::NewLine, [System.Text.Encoding]::UTF8) } catch { }
    exit 1
}

#  ── Optional JSON copy (same shape as static\agent.ps1 submits to the web API) ─
if ($AlsoJson) {
    $ipOut = @(
        if ($ipFlat) {
            foreach ($part in $ipFlat -split '; ') {
                $iface, $ip = $part -split '=', 2
                @{ iface = $iface; ip = $ip }
            }
        }
    )
    $softwareOut = @(
        @{ id='chrome';      name='Google Chrome';         installed=($swChrome -eq 'Yes'); version=$chromeResult.version }
        @{ id='forticlient'; name='FortiClient';           installed=($swForti  -eq 'Yes'); version=$fortiResult.version }
        @{ id='teams';       name='Microsoft Teams';       installed=($swTeams  -eq 'Yes'); version=$teamsResult.version }
        @{ id='sccm';        name='SCCM (ConfigMgr Client)'; installed=($swSccm -eq 'Yes'); version=$sccmResult.version }
        @{ id='intune';      name='Intune Mgmt Extension'; installed=($swIntune -eq 'Yes'); version=$intuneResult.version }
        @{ id='office2021';  name='Microsoft Office 2021'; installed=($swOffice -eq 'Yes'); version=$officeResult.version }
        @{ id='vlc';         name='VLC Media Player';      installed=($swVlc    -eq 'Yes'); version=$vlcResult.version }
    )
    $payload = [ordered]@{
        hostname      = $row['hostname']
        username      = $row['username']
        serial        = $row['serial_number']
        manufacturer  = $row['manufacturer']
        model         = $row['model']
        cpu           = $row['cpu']
        cpu_cores     = [int]$row['cpu_cores']
        ram_gb        = $row['ram_gb']
        disks         = @($diskObjs)
        os_name       = $row['os_name']
        os_version    = $row['os_version']
        os_arch       = $row['os_arch']
        ip_addresses  = $ipOut
        agent_os      = 'windows'
        collected_at  = $row['collected_at']
        software_checks    = $softwareOut
        windows_activation = @{
            status       = $row['win_activation_status']
            status_code  = -1
            product_name = $row['win_product_name']
            partial_key  = $row['win_partial_key']
        }
    }
    try {
        $payload | ConvertTo-Json -Depth 6 | Set-Content -Path $jsonFilePath -Encoding UTF8 -Force
        Write-Host "  JSON copy: $jsonFilePath" -ForegroundColor DarkGray
    } catch {
        Write-Host "  WARN: could not write JSON copy: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

exit 0
