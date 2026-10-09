# ==============================================================================
# Snipe-IT Onboarding Agent — Windows
# Phase 3: Hardware + Software inventory + Windows Activation status
#
# Called automatically by the web page. Paste the one-liner shown in
# the browser into any PowerShell window on the managed device.
#
#   $env:ONBOARD_URL="http://SERVER:8080"; $env:ONBOARD_CODE="A7-X3-Q9"
#   iwr $env:ONBOARD_URL/static/agent.ps1 -UseBasicParsing | iex
# ==============================================================================

param(
    [string]$ServerUrl = $env:ONBOARD_URL,
    [string]$Code      = $env:ONBOARD_CODE
)

if (-not $ServerUrl -or -not $Code) {
    Write-Host "ERROR: ONBOARD_URL and ONBOARD_CODE must be set." -ForegroundColor Red
    Write-Host "Use the command shown on the onboarding page." -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "  Snipe-IT Onboarding Agent (Windows)" -ForegroundColor Cyan
Write-Host "  Session : $Code" -ForegroundColor Cyan
Write-Host "  Server  : $ServerUrl" -ForegroundColor Cyan
Write-Host ""

# ── Helper: swallow errors and return a default ───────────────────────────────

function Safe-Get {
    param([scriptblock]$Block, $Default = $null)
    try { $result = & $Block; if ($null -ne $result) { $result } else { $Default } }
    catch { $Default }
}

# ==============================================================================
# SECTION 1 — HARDWARE
# ==============================================================================

Write-Host "  [1/3] Collecting hardware information..." -ForegroundColor Gray

$cs    = Safe-Get { Get-CimInstance Win32_ComputerSystem }
$bios  = Safe-Get { Get-CimInstance Win32_BIOS }
$os    = Safe-Get { Get-CimInstance Win32_OperatingSystem }
$cpus  = Safe-Get { Get-CimInstance Win32_Processor }
$cpu   = if ($cpus) { $cpus | Select-Object -First 1 } else { $null }
$disks = Safe-Get { Get-CimInstance Win32_DiskDrive }
$nics  = Safe-Get { Get-NetAdapter -Physical | Where-Object { $_.Status -eq "Up" } }
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
if ([string]::IsNullOrWhiteSpace($currentUser)) {
    $currentUser = [Environment]::UserName
}
if ([string]::IsNullOrWhiteSpace($currentUser)) {
    throw "Could not determine the current Windows user."
}

# Physical RAM — sum all sticks for the true installed amount
$ramGB = Safe-Get {
    $sticks = Get-CimInstance Win32_PhysicalMemory
    [math]::Round(($sticks | Measure-Object -Property Capacity -Sum).Sum / 1GB, 1)
}

# Disk list
$diskList = @()
if ($disks) {
    foreach ($d in $disks) {
        $diskType = "Unknown"
        if ($d.MediaType -match "SSD|Solid State") { $diskType = "SSD" }
        elseif ($d.MediaType -match "HDD|Fixed|External") { $diskType = "HDD" }
        elseif ($d.MediaType) { $diskType = $d.MediaType }

        # Try MSFT_PhysicalDisk for a more reliable SSD/HDD flag (Win8+)
        $msftDisk = Safe-Get {
            Get-PhysicalDisk | Where-Object { $_.SerialNumber -eq $d.SerialNumber } |
                Select-Object -First 1
        }
        if ($msftDisk) {
            $diskType = switch ($msftDisk.MediaType) {
                "SSD"          { "SSD" }
                "HDD"          { "HDD" }
                "SCM"          { "SCM" }
                default        { $diskType }
            }
        }

        $diskList += @{
            name    = $d.Model
            size_gb = if ($d.Size) { [math]::Round($d.Size / 1GB, 1) } else { $null }
            type    = $diskType
        }
    }
}

# IPv4 addresses from active Wi-Fi and Ethernet adapters only
$ipList  = @()
if ($nics) {
    foreach ($nic in $nics) {
        $adapterInfo = "$($nic.Name) $($nic.InterfaceDescription) $($nic.PhysicalMediaType)"
        $connectionType = if ($adapterInfo -match "(?i)802\.3|ethernet") {
            "Ethernet"
        } elseif ($adapterInfo -match "(?i)802\.11|wireless|wi-?fi") {
            "Wi-Fi"
        } else {
            $null
        }
        if (-not $connectionType) { continue }

        $addresses = Safe-Get {
            Get-NetIPAddress -InterfaceIndex $nic.ifIndex -AddressFamily IPv4 -ErrorAction Stop
        }
        foreach ($address in @($addresses)) {
            if ($address -and $address.IPAddress) {
                $ipList += @{ iface = "$connectionType ($($nic.Name))"; ip = $address.IPAddress }
            }
        }
    }
}

# ==============================================================================
# SECTION 2 — WINDOWS ACTIVATION
# ==============================================================================

Write-Host "  [2/3] Checking Windows activation..." -ForegroundColor Gray

$activationInfo = @{
    status       = "Unknown"
    status_code  = -1
    product_name = $null
    partial_key  = $null
}

# LicenseStatus codes:
#  0 = Unlicensed
#  1 = Licensed  ← the good one
#  2 = OOBGrace (Out-of-Box Grace period)
#  3 = OOTGrace (Out-of-Tolerance Grace period)
#  4 = NonGenuineGrace
#  5 = Notification (Windows not activated, user notified)
#  6 = ExtendedGrace

$licenseStatusMap = @{
    0 = "Unlicensed"
    1 = "Activated"
    2 = "Grace period (Out-of-Box)"
    3 = "Grace period (Out-of-Tolerance)"
    4 = "Grace period (Non-Genuine)"
    5 = "Notification mode - not activated"
    6 = "Extended grace period"
}

$slp = Safe-Get {
    Get-CimInstance SoftwareLicensingProduct |
        Where-Object { $_.Name -match "Windows" -and $_.PartialProductKey } |
        Select-Object -First 1
}

if ($slp) {
    $code_int = [int]$slp.LicenseStatus
    $activationInfo = @{
        status       = if ($licenseStatusMap.ContainsKey($code_int)) { $licenseStatusMap[$code_int] } else { "Unknown ($code_int)" }
        status_code  = $code_int
        product_name = $slp.Name
        partial_key  = $slp.PartialProductKey
    }
}

# ==============================================================================
# SECTION 3 — SOFTWARE INVENTORY
# ==============================================================================

Write-Host "  [3/3] Scanning installed software..." -ForegroundColor Gray

# ── Registry uninstall hives (32-bit and 64-bit, machine and user) ────────────

$regPaths = @(
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKLM:\Software\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*"
)

$allInstalled = @()
foreach ($path in $regPaths) {
    $entries = Safe-Get { Get-ItemProperty $path -ErrorAction SilentlyContinue } -Default @()
    if ($entries) { $allInstalled += $entries }
}

# ── Helper: search registry entries by display name pattern ──────────────────

function Find-InstalledApp {
    param(
        [string[]]$Patterns,        # regex patterns to match DisplayName
        [string]$FallbackPath = $null  # if set, also check this path exists on disk
    )

    $match = $allInstalled | Where-Object {
        $dn = $_.DisplayName
        if (-not $dn) { return $false }
        foreach ($p in $Patterns) { if ($dn -match $p) { return $true } }
        return $false
    } | Sort-Object { $_.DisplayVersion } -Descending | Select-Object -First 1

    if ($match) {
        return @{
            installed = $true
            version   = if ($match.DisplayVersion) { $match.DisplayVersion } else { $null }
            method    = "registry"
        }
    }

    # Fallback: check if a known file/folder exists
    if ($FallbackPath -and (Test-Path $FallbackPath)) {
        # Try to read version from file
        $ver = Safe-Get {
            (Get-Item $FallbackPath).VersionInfo.ProductVersion
        }
        return @{
            installed = $true
            version   = $ver
            method    = "filesystem"
        }
    }

    return @{ installed = $false; version = $null; method = "not_found" }
}

# ── Helper: check a Windows Service or key executable path ───────────────────

function Find-ByService {
    param([string]$ServiceName, [string[]]$FallbackPaths = @())
    $svc = Safe-Get { Get-Service -Name $ServiceName -ErrorAction SilentlyContinue }
    if ($svc) {
        # Try to get version from the service executable
        $exe = Safe-Get {
            $wmiSvc = Get-CimInstance Win32_Service -Filter "Name='$ServiceName'" -ErrorAction SilentlyContinue
            if ($wmiSvc -and $wmiSvc.PathName) {
                $exePath = ($wmiSvc.PathName -replace '"','').Split(' ')[0]
                if (Test-Path $exePath) { (Get-Item $exePath).VersionInfo.ProductVersion }
            }
        }
        return @{ installed = $true; version = $exe; method = "service" }
    }
    foreach ($p in $FallbackPaths) {
        if (Test-Path $p) {
            $ver = Safe-Get { (Get-Item $p).VersionInfo.ProductVersion }
            return @{ installed = $true; version = $ver; method = "filesystem" }
        }
    }
    return @{ installed = $false; version = $null; method = "not_found" }
}

# ── Define the apps to check ─────────────────────────────────────────────────
#
# Each entry: id (slug), name (display), detection logic
#
# Detection notes:
#   Chrome      — registry "Google Chrome"; fallback chrome.exe path
#   FortiClient — registry "FortiClient"; FortiTray service as backup
#   Teams       — NEW Teams (2023+) is per-user MSIX, old Teams in registry
#   SCCM        — SMS Agent Host service (CcmExec); no classic installer entry
#   Intune      — Microsoft Intune Management Extension service
#   Office 2021 — registry entries for Click-to-Run or MSI "Microsoft Office"
#   VLC         — registry "VLC media player"

$chromePaths = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe"
)

$fortiPaths = @(
    "$env:ProgramFiles\Fortinet\FortiClient\FortiClient.exe",
    "${env:ProgramFiles(x86)}\Fortinet\FortiClient\FortiClient.exe"
)

$teamsPaths = @(
    "$env:LOCALAPPDATA\Microsoft\Teams\current\Teams.exe",              # old Teams
    "$env:ProgramFiles\WindowsApps\MSTeams*\ms-teams.exe"              # new Teams (glob — handled below)
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

# ── Chrome ────────────────────────────────────────────────────────────────────
$chromeResult = Find-InstalledApp -Patterns @("^Google Chrome$") -FallbackPath $chromePaths[0]
if (-not $chromeResult.installed) {
    foreach ($p in $chromePaths) { if (Test-Path $p) {
        $chromeResult = @{ installed=$true; version=(Safe-Get{(Get-Item $p).VersionInfo.ProductVersion}); method="filesystem" }
        break
    }}
}

# ── FortiClient ───────────────────────────────────────────────────────────────
$fortiResult = Find-InstalledApp -Patterns @("FortiClient") -FallbackPath $fortiPaths[0]
if (-not $fortiResult.installed) {
    $svcCheck = Find-ByService -ServiceName "FortiTray" -FallbackPaths $fortiPaths
    if ($svcCheck.installed) { $fortiResult = $svcCheck }
}

# ── Microsoft Teams ───────────────────────────────────────────────────────────
# New Teams (2023+) installs as an MSIX package — not in classic Uninstall registry
$teamsResult = Find-InstalledApp -Patterns @("Microsoft Teams", "^Teams$") -FallbackPath "$env:LOCALAPPDATA\Microsoft\Teams\current\Teams.exe"

if (-not $teamsResult.installed) {
    # Check for new Teams MSIX package
    $newTeams = Safe-Get {
        Get-AppxPackage -Name "MSTeams" -ErrorAction SilentlyContinue |
            Select-Object -First 1
    }
    if ($newTeams) {
        $teamsResult = @{
            installed = $true
            version   = $newTeams.Version
            method    = "appx"
        }
    }
}

if (-not $teamsResult.installed) {
    # Check new Teams machine-wide install path
    $newTeamsExe = "$env:ProgramFiles\WindowsApps"
    $newTeamsFound = Safe-Get {
        Get-ChildItem "$env:ProgramFiles\WindowsApps" -Filter "MSTeams*" -Directory -ErrorAction SilentlyContinue |
            Select-Object -First 1
    }
    if ($newTeamsFound) {
        $teamsResult = @{ installed=$true; version=$null; method="filesystem" }
    }
}

# ── SCCM (Configuration Manager Client) ──────────────────────────────────────
$sccmResult = Find-ByService -ServiceName "CcmExec" -FallbackPaths $sccmPaths
if (-not $sccmResult.installed) {
    # Also check ccmsetup completed marker
    if (Test-Path "$env:WinDir\CCM") {
        $sccmResult = @{ installed=$true; version=$null; method="filesystem" }
    }
}

# ── Intune (Microsoft Intune Management Extension) ───────────────────────────
$intuneResult = Find-ByService -ServiceName "IntuneManagementExtension" -FallbackPaths $intunePaths
if (-not $intuneResult.installed) {
    $intuneResult = Find-InstalledApp -Patterns @("Microsoft Intune Management Extension", "Intune Management Extension")
}
if (-not $intuneResult.installed) {
    # Check for MDM enrollment (device enrolled in Intune via MDM, even without the extension)
    $mdmEnrolled = Safe-Get {
        $tasks = Get-ScheduledTask -TaskPath "\Microsoft\Windows\EnterpriseMgmt\" -ErrorAction SilentlyContinue
        if ($tasks) { $true } else { $false }
    }
    if ($mdmEnrolled) {
        $intuneResult = @{ installed=$true; version=$null; method="mdm_enrollment" }
    }
}

# ── Microsoft Office 2021 ────────────────────────────────────────────────────
# Match broadly — Click-to-Run and MSI both register differently
$officeResult = Find-InstalledApp -Patterns @(
    "Microsoft Office.*2021",
    "Microsoft 365",        # same installer base as Office 2021 C2R
    "Microsoft Office LTSC 2021",
    "Microsoft Office Professional"
) -FallbackPath $officePaths[0]

if (-not $officeResult.installed) {
    foreach ($p in $officePaths) {
        if (Test-Path $p) {
            $officeResult = @{
                installed = $true
                version   = Safe-Get { (Get-Item $p).VersionInfo.ProductVersion }
                method    = "filesystem"
            }
            break
        }
    }
}

# ── VLC ───────────────────────────────────────────────────────────────────────
$vlcResult = Find-InstalledApp -Patterns @("VLC media player", "^VLC$") -FallbackPath $vlcPaths[0]
if (-not $vlcResult.installed) {
    foreach ($p in $vlcPaths) { if (Test-Path $p) {
        $vlcResult = @{ installed=$true; version=(Safe-Get{(Get-Item $p).VersionInfo.ProductVersion}); method="filesystem" }
        break
    }}
}

# ── Assemble software list ────────────────────────────────────────────────────

$softwareChecks = @(
    @{ id="chrome";        name="Google Chrome";              installed=$chromeResult.installed; version=$chromeResult.version; method=$chromeResult.method }
    @{ id="forticlient";   name="FortiClient";                installed=$fortiResult.installed;  version=$fortiResult.version;  method=$fortiResult.method  }
    @{ id="teams";         name="Microsoft Teams";            installed=$teamsResult.installed;  version=$teamsResult.version;  method=$teamsResult.method  }
    @{ id="sccm";          name="SCCM (ConfigMgr Client)";   installed=$sccmResult.installed;   version=$sccmResult.version;   method=$sccmResult.method   }
    @{ id="intune";        name="Intune Mgmt Extension";      installed=$intuneResult.installed;  version=$intuneResult.version;  method=$intuneResult.method  }
    @{ id="office2021";    name="Microsoft Office 2021";      installed=$officeResult.installed;  version=$officeResult.version;  method=$officeResult.method  }
    @{ id="vlc";           name="VLC Media Player";           installed=$vlcResult.installed;    version=$vlcResult.version;    method=$vlcResult.method    }
)

# Print a quick summary to the terminal
Write-Host ""
Write-Host "  Software results:" -ForegroundColor Gray
foreach ($app in $softwareChecks) {
    $icon    = if ($app.installed) { "+" } else { "-" }
    $color   = if ($app.installed) { "Green" } else { "DarkGray" }
    $verText = if ($app.version)   { "  v$($app.version)" } else { "" }
    Write-Host "    [$icon] $($app.name)$verText" -ForegroundColor $color
}

$actColor = if ($activationInfo.status_code -eq 1) { "Green" } else { "Yellow" }
Write-Host ""
Write-Host "  Windows activation: $($activationInfo.status)" -ForegroundColor $actColor
Write-Host ""

# ==============================================================================
# SUBMIT
# ==============================================================================

$payload = @{
    # Hardware
    hostname      = $env:COMPUTERNAME
    username      = $currentUser
    serial        = if ($bios) { $bios.SerialNumber }      else { $null }
    manufacturer  = if ($cs)   { $cs.Manufacturer }        else { $null }
    model         = if ($cs)   { $cs.Model }               else { $null }
    cpu           = if ($cpu)  { $cpu.Name }               else { $null }
    cpu_cores     = if ($cpu)  { [int]$cpu.NumberOfCores } else { $null }
    ram_gb        = $ramGB
    disks         = $diskList
    os_name       = if ($os)   { $os.Caption }             else { $null }
    os_version    = if ($os)   { $os.Version }             else { $null }
    os_arch       = if ($os)   { $os.OSArchitecture }      else { $null }
    ip_addresses  = $ipList
    agent_os      = "windows"
    collected_at  = (Get-Date -Format "yyyy-MM-ddTHH:mm:ss")
    # Phase 3
    software_checks    = $softwareChecks
    windows_activation = $activationInfo
}

$json = $payload | ConvertTo-Json -Depth 6
$uri  = "$ServerUrl/api/session/$Code/submit"

Write-Host "  Sending data to server..." -ForegroundColor Gray

try {
    Invoke-RestMethod -Method POST -Uri $uri `
        -ContentType "application/json" -Body $json -ErrorAction Stop | Out-Null
    Write-Host "  Done! Switch back to the web browser." -ForegroundColor Green
    Write-Host ""
} catch {
    Write-Host "  ERROR: Could not reach the onboarding server." -ForegroundColor Red
    Write-Host "  $_" -ForegroundColor Red
    Write-Host ""
    exit 1
}
