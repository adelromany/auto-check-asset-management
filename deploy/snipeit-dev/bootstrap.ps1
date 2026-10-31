$ErrorActionPreference = "Stop"
$DevDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $DevDir "..\..")).Path
$DevEnv = Join-Path $DevDir ".env"
$PortalEnv = Join-Path $RepoRoot ".env"

function New-RandomHex([int]$Count) {
  $Bytes = [byte[]]::new($Count)
  $Rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  try { $Rng.GetBytes($Bytes) } finally { $Rng.Dispose() }
  return [Convert]::ToHexString($Bytes).ToLowerInvariant()
}

function Set-EnvLine([string[]]$Lines, [string]$Key, [string]$Value) {
  $Pattern = "^$([regex]::Escape($Key))="
  $Found = $false
  $Updated = foreach ($Line in $Lines) {
    if ($Line -match $Pattern) {
      if (-not $Found) { $Found = $true; "$Key=$Value" }
    } else { $Line }
  }
  if (-not $Found) { $Updated += "$Key=$Value" }
  return ,$Updated
}

if (-not (Test-Path -LiteralPath $DevEnv)) {
  Copy-Item -LiteralPath (Join-Path $DevDir ".env.example") -Destination $DevEnv
  $Lines = Get-Content -LiteralPath $DevEnv
  $Lines = Set-EnvLine $Lines "SNIPEIT_APP_KEY" ("base64:" + [Convert]::ToBase64String([Convert]::FromHexString((New-RandomHex 32))))
  $Lines = Set-EnvLine $Lines "SNIPEIT_DB_PASSWORD" (New-RandomHex 32)
  $Lines = Set-EnvLine $Lines "SNIPEIT_DB_ROOT_PASSWORD" (New-RandomHex 32)
  Set-Content -LiteralPath $DevEnv -Value $Lines -Encoding utf8
}

if (-not (Test-Path -LiteralPath $PortalEnv)) {
  Copy-Item -LiteralPath (Join-Path $RepoRoot ".env.example") -Destination $PortalEnv
}

$env:SNIPEIT_PORT = "8081"
$env:SNIPEIT_APP_URL = "http://localhost:8081"
Push-Location $DevDir
try {
  & docker compose up -d
  if ($LASTEXITCODE -ne 0) { throw "docker compose up failed with exit code $LASTEXITCODE" }
  $Healthy = $false
  for ($Attempt = 0; $Attempt -lt 60; $Attempt++) {
    $ContainerId = & docker compose ps -q snipeit
    if ($LASTEXITCODE -ne 0) { throw "docker compose ps failed with exit code $LASTEXITCODE" }
    if ($ContainerId) {
      $State = & docker inspect --format '{{.State.Status}}' $ContainerId 2>$null
      if ($State -eq "running") {
        try {
          $null = Invoke-WebRequest -Uri "http://localhost:8081/login" -TimeoutSec 4 -UseBasicParsing
          $Healthy = $true
          break
        } catch { }
      }
    }
    Start-Sleep -Seconds 5
  }
  if (-not $Healthy) { throw "Snipe-IT did not become healthy within five minutes." }

  & docker compose exec -T snipeit sh -c "test -s /var/lib/snipeit/keys/oauth-private.key && test -s /var/lib/snipeit/keys/oauth-public.key" 2>$null | Out-Null
  $KeysExist = $LASTEXITCODE -eq 0
  if (-not $KeysExist) {
    & docker compose exec -T snipeit php artisan passport:keys --force | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "passport:keys failed with exit code $LASTEXITCODE" }
    & docker compose exec -T snipeit php artisan passport:install --force | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "passport:install failed with exit code $LASTEXITCODE" }
  }
  & docker compose exec -T snipeit sh -c "chmod 644 /var/lib/snipeit/keys/oauth-*" | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "OAuth key permissions command failed with exit code $LASTEXITCODE" }

  $Settings = 'if (!DB::table("settings")->exists()) { DB::table("settings")->insert(["site_name" => "Snipe-IT", "per_page" => 20]); }'
  & docker compose exec -T snipeit php artisan tinker --execute=$Settings | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "settings bootstrap failed with exit code $LASTEXITCODE" }

  $AdminExists = & docker compose exec -T snipeit php artisan tinker --execute='dump(DB::table("users")->where("username", "admin")->exists());'
  if ($LASTEXITCODE -ne 0) { throw "admin check failed with exit code $LASTEXITCODE" }
  if (($AdminExists -join "") -notmatch "true") {
    & docker compose exec -T snipeit php artisan snipeit:create-admin --first_name=Dev --last_name=Admin --email=admin@example.test --username=admin --password=ChangeMe-Dev-Only-1 --no-interaction | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "snipeit:create-admin failed with exit code $LASTEXITCODE" }
  }

  $Seed = '$user = App\Models\User::firstOrCreate(["username" => "TEST-recipient"], ["first_name" => "TEST", "last_name" => "Recipient", "email" => "test.recipient@example.test", "password" => bcrypt(\Illuminate\Support\Str::random(48)), "activated" => 1]); $category = App\Models\Category::firstOrCreate(["name" => "TEST-Computer"], ["category_type" => "asset"]); $manufacturer = App\Models\Manufacturer::firstOrCreate(["name" => "TEST-Manufacturer"]); $model = App\Models\AssetModel::firstOrCreate(["name" => "TEST-Portal Model"], ["category_id" => $category->id, "manufacturer_id" => $manufacturer->id, "model_number" => "TEST-0001", "require_serial" => 1]); $status = App\Models\Statuslabel::firstOrCreate(["name" => "Ready to Deploy"], ["deployable" => 1]); App\Models\Asset::updateOrCreate(["serial" => "TEST-SN-0001"], ["asset_tag" => "TEST-A-0001", "name" => "TEST-Portal Asset", "model_id" => $model->id, "status_id" => $status->id]);'
  & docker compose exec -T snipeit php artisan tinker --execute=$Seed | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "TEST-only seed failed with exit code $LASTEXITCODE" }

  $PortalLines = Get-Content -LiteralPath $PortalEnv
  $PortalUrl = "http://localhost:8081"
  $ExistingToken = ($PortalLines | Where-Object { $_ -match '^SNIPEIT_TOKEN=' } | Select-Object -First 1) -replace '^SNIPEIT_TOKEN=', ''
  if (-not $ExistingToken) {
    $ExistingToken = (& docker compose exec -T snipeit php artisan snipeit:make-api-key --user_id=1 --name=dev-portal --key-only | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $ExistingToken) { throw "API key creation failed; token was not written." }
  }
  $PortalLines = Set-EnvLine $PortalLines "SNIPEIT_URL" $PortalUrl
  $PortalLines = Set-EnvLine $PortalLines "SNIPEIT_TOKEN" $ExistingToken
  Set-Content -LiteralPath $PortalEnv -Value $PortalLines -Encoding utf8
} finally {
  Pop-Location
}

Write-Output "Snipe-IT is healthy at http://localhost:8081; TEST seed and portal configuration are ready."
