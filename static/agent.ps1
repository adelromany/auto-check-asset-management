# ==============================================================================
# Snipe-IT Onboarding — Windows Agent
# Collects full hardware info and POSTs it to the onboarding server.
#
# Usage (paste into PowerShell — populated by the web page):
#   iwr http://SERVER/static/agent.ps1 | iex
#
# Or with an explicit code (the web page always embeds the code):
#   $env:ONBOARD_CODE="A7-X3-Q9"; $env:ONBOARD_URL="http://SERVER"; iwr http://SERVER/static/agent.ps1 | iex
# ==============================================================================

param(
    [string]$ServerUrl = $env:ONBOARD_URL,
    [string]$Code      = $env:ONBOARD_CODE
)

if (-not $ServerUrl -or -not $Code) {
    Write-Host "ERROR: ServerUrl and Code must be set." -ForegroundColor Red
    Write-Host "Run this from the link shown on the onboarding page." -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "  Snipe-IT Onboarding Agent (Windows)" -ForegroundColor Cyan
Write-Host "  Session code: $Code" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Collecting hardware information..." -ForegroundColor Gray

function Safe-Get {
    param([scriptblock]$Block, $Default = $null)
    try { & $Block } catch { $Default }
}

# ---- Collect ---------------------------------------------------------------

$cs      = Safe-Get { Get-CimInstance Win32_ComputerSystem }
$bios    = Safe-Get { Get-CimInstance Win32_BIOS }
$os      = Safe-Get { Get-CimInstance Win32_OperatingSystem }
$cpus    = Safe-Get { Get-CimInstance Win32_Processor }
$cpu     = if ($cpus) { $cpus | Select-Object -First 1 } else { $null }
$disks   = Safe-Get { Get-CimInstance Win32_DiskDrive }
$nics    = Safe-Get { Get-NetAdapter -Physical | Where-Object { $_.Status -eq "Up" } }
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
if ([string]::IsNullOrWhiteSpace($currentUser)) {
    $currentUser = [Environment]::UserName
    if (-not [string]::IsNullOrWhiteSpace($env:USERDOMAIN)) {
        $currentUser = "$env:USERDOMAIN\$currentUser"
    }
}
if ([string]::IsNullOrWhiteSpace($currentUser)) {
    throw "Could not determine the current Windows user."
}
Write-Host "  Current user: $currentUser" -ForegroundColor Gray

# RAM — sum of all physical memory sticks
$ramGB = Safe-Get {
    $sticks = Get-CimInstance Win32_PhysicalMemory
    [math]::Round(($sticks | Measure-Object -Property Capacity -Sum).Sum / 1GB, 1)
}

# Disks
$diskList = @()
if ($disks) {
    foreach ($d in $disks) {
        $diskList += @{
            name     = $d.Model
            size_gb  = if ($d.Size) { [math]::Round($d.Size / 1GB, 1) } else { $null }
            type     = if ($d.MediaType -match "SSD|Solid") { "SSD" } elseif ($d.MediaType -match "HDD|Fixed") { "HDD" } else { $d.MediaType }
        }
    }
}

# IPv4 addresses from active Wi-Fi and Ethernet adapters only
$ipList  = @()
if ($nics) {
    foreach ($nic in $nics) {
        $mediaType = [string]$nic.PhysicalMediaType
        $adapterInfo = "$($nic.Name) $($nic.InterfaceDescription) $mediaType"
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

$payload = @{
    hostname      = $env:COMPUTERNAME
    username      = $currentUser
    serial        = if ($bios)  { $bios.SerialNumber }          else { $null }
    manufacturer  = if ($cs)    { $cs.Manufacturer }            else { $null }
    model         = if ($cs)    { $cs.Model }                   else { $null }
    cpu           = if ($cpu)   { $cpu.Name }                   else { $null }
    cpu_cores     = if ($cpu)   { [int]$cpu.NumberOfCores }     else { $null }
    ram_gb        = $ramGB
    disks         = $diskList
    os_name       = if ($os)    { $os.Caption }                 else { $null }
    os_version    = if ($os)    { $os.Version }                 else { $null }
    os_arch       = if ($os)    { $os.OSArchitecture }          else { $null }
    ip_addresses  = $ipList
    agent_os      = "windows"
    collected_at  = (Get-Date -Format "yyyy-MM-ddTHH:mm:ss")
}

# ---- POST ------------------------------------------------------------------

$json    = $payload | ConvertTo-Json -Depth 5
$uri     = "$ServerUrl/api/session/$Code/submit"

Write-Host "  Sending to $uri ..." -ForegroundColor Gray

try {
    $resp = Invoke-RestMethod -Method POST -Uri $uri `
        -ContentType "application/json" -Body $json -ErrorAction Stop
    Write-Host ""
    Write-Host "  Done! Switch back to the web browser." -ForegroundColor Green
    Write-Host ""
} catch {
    Write-Host ""
    Write-Host "  ERROR: Could not reach the onboarding server." -ForegroundColor Red
    Write-Host "  $_" -ForegroundColor Red
    Write-Host ""
    exit 1
}
