# Fetch the pinned Archify development tool into the git-ignored .tools folder.
# Archify is not an application dependency; the generated HTML is committed.
$ErrorActionPreference = "Stop"

$ArchifyVersion = "3.2.0"
$ArchifyCommit = "a4065941f12be7967436261d9934784e381d423c"
$ArchifyRepo = "https://github.com/tt-a1i/archify"
$Root = Split-Path -Parent $PSScriptRoot
$Dest = Join-Path $Root ".tools\archify"
$Cli = Join-Path $Dest "archify\bin\archify.mjs"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git is required"
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "Node.js 18 or newer is required"
}

$NodeMajor = [int]((node -p "process.versions.node.split('.')[0]").Trim())
if ($NodeMajor -lt 18) {
    throw "Node.js 18 or newer is required (found $(node --version))"
}
Write-Host "Node $(node --version) found."

if (Test-Path (Join-Path $Dest ".git")) {
    $Current = (git -C $Dest rev-parse HEAD).Trim()
    if ($Current -eq $ArchifyCommit) {
        Write-Host "Archify $ArchifyVersion is already present at $ArchifyCommit."
    } else {
        Write-Host "Updating Archify checkout from $Current to $ArchifyCommit..."
        git -C $Dest fetch --depth 1 origin $ArchifyCommit
        if ($LASTEXITCODE -ne 0) { throw "git fetch failed" }
        git -C $Dest checkout --detach $ArchifyCommit
        if ($LASTEXITCODE -ne 0) { throw "git checkout failed" }
    }
} else {
    New-Item -ItemType Directory -Force -Path (Join-Path $Root ".tools") | Out-Null
    Write-Host "Cloning $ArchifyRepo into $Dest..."
    git clone $ArchifyRepo $Dest
    if ($LASTEXITCODE -ne 0) { throw "git clone failed" }
    git -C $Dest checkout --detach $ArchifyCommit
    if ($LASTEXITCODE -ne 0) { throw "git checkout failed" }
}

$Actual = (git -C $Dest rev-parse HEAD).Trim()
if ($Actual -ne $ArchifyCommit) {
    throw "expected $ArchifyCommit, found $Actual"
}

Write-Host "Archify $ArchifyVersion pinned at $Actual"
Write-Host "CLI: $Cli"
node $Cli doctor
if ($LASTEXITCODE -ne 0) { throw "archify doctor failed" }
