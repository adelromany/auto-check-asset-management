@echo off
rem ==============================================================================
rem  Snipe-IT Asset Inventory - GPO startup launcher
rem
rem  This .cmd is the script registered in the GPO's Startup Scripts (scripts.ini).
rem  It wraps agent-gpo.ps1 so that no ExecutionPolicy/remote-signing is required
rem  for the policy itself: the wrapper launches powershell.exe with an explicit
rem  -ExecutionPolicy Bypass argument.
rem
rem  What it does at every machine boot:
rem    1) copy the current agent-gpo.ps1 from this folder (GPO SysVol share) into
rem       a local cache folder  ->  the run survives the network not being ready.
rem    2) run the CACHED copy (fast, offline-proof) via powershell.exe
rem    3) fall back to the SYSVOL copy if the cache copy could not be made
rem    4) write an Application event-log entry if the agent file is nowhere to be
rem       found (disk problem, SysVol replication incomplete, ...)
rem
rem  ASCII only + CRLF line endings, please - it is distributed via SYSVOL.
rem ==============================================================================

setlocal
set "SCRIPT_DIR=%~dp0"
set "CACHE_DIR=%ProgramData%\AssetAgent"
set "CACHE_PS1=%CACHE_DIR%\agent-gpo.ps1"
set "SRC_PS1=%SCRIPT_DIR%agent-gpo.ps1"

if not exist "%CACHE_DIR%"            mkdir "%CACHE_DIR%"  >nul 2>&1
if     exist "%SRC_PS1%"              copy /Y "%SRC_PS1%" "%CACHE_PS1%" >nul 2>&1

if exist "%CACHE_PS1%" (
    powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "%CACHE_PS1%"
    goto :done
)

if exist "%SRC_PS1%" (
    powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "%SRC_PS1%"
    goto :done
)

eventcreate /L APPLICATION /T ERROR /SO AssetAgentLauncher /ID 100 /D "Asset Agent launcher: agent-gpo.ps1 was not found in SysVol or in the local cache folder." >nul 2>&1

:done
endlocal
