[CmdletBinding(SupportsShouldProcess = $true)]
param()

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $RepoRoot
try {
    $VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        if ($PSCmdlet.ShouldProcess(".venv", "Create Python virtual environment")) {
            python -m venv .venv
            if ($LASTEXITCODE -ne 0) { throw "python -m venv failed." }
        } else { Write-Output "Would create .venv" }
    } else { Write-Output "Using existing .venv" }

    if ($PSCmdlet.ShouldProcess("requirements.txt", "Install portal dependencies")) {
        if (Test-Path -LiteralPath $VenvPython) {
            & $VenvPython -m pip install -r requirements.txt
            if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
        } else { Write-Output "Would install requirements.txt in .venv" }
    } else { Write-Output "Would install requirements.txt in .venv" }

    if (-not (Test-Path -LiteralPath ".env")) {
        if ($PSCmdlet.ShouldProcess(".env", "Create ignored environment file and random session secret")) {
            Copy-Item -LiteralPath ".env.example" -Destination ".env"
            $Lines = Get-Content -LiteralPath ".env"
            $Bytes = [byte[]]::new(32)
            $Rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
            try { $Rng.GetBytes($Bytes) } finally { $Rng.Dispose() }
            $Secret = [Convert]::ToHexString($Bytes).ToLowerInvariant()
            $Output = foreach ($Line in $Lines) {
                if ($Line -match '^SESSION_SECRET=') { "SESSION_SECRET=$Secret" } else { $Line }
            }
            Set-Content -LiteralPath ".env" -Value $Output -Encoding utf8
            Write-Output "Created .env from .env.example with a random SESSION_SECRET (value hidden)."
        } else { Write-Output "Would create .env from .env.example and set a random SESSION_SECRET" }
    } else { Write-Output "Keeping existing .env; no secret values displayed." }

    if ($PSCmdlet.ShouldProcess("database", "Apply Alembic migrations")) {
        if (Test-Path -LiteralPath $VenvPython) {
            & $VenvPython -m alembic upgrade head
            if ($LASTEXITCODE -ne 0) { throw "Alembic migration failed." }
        } else { Write-Output "Would run python -m alembic upgrade head" }
    } else { Write-Output "Would run python -m alembic upgrade head" }
    Write-Output "Portal setup complete. Review .env for SSO and Snipe-IT settings; secrets are never displayed."
} finally { Pop-Location }
