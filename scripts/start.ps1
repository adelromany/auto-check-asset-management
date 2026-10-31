[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateSet("127.0.0.1", "0.0.0.0")]
    [string]$HostAddress = "127.0.0.1",
    [ValidateRange(1, 65535)]
    [int]$Port = 8080
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $VenvPython)) { throw "Run .\scripts\setup.ps1 first." }
Push-Location $RepoRoot
try {
    $env:SSO_ENABLED = "false"
    $env:HTTPS_ONLY = "false"
    Write-Output "Starting local development mode at http://$HostAddress`:$Port (SSO disabled)."
    Write-Output "Network binding 0.0.0.0 allows other devices to connect; use only on a trusted network."
    if ($PSCmdlet.ShouldProcess("http://$HostAddress`:$Port", "Start the Handover Portal")) {
        & $VenvPython -m uvicorn main:app --host $HostAddress --port $Port
        if ($LASTEXITCODE -ne 0) { throw "Uvicorn exited with code $LASTEXITCODE." }
    } else { Write-Output "Would run .\.venv\Scripts\python.exe -m uvicorn main:app --host $HostAddress --port $Port" }
} finally { Pop-Location }
