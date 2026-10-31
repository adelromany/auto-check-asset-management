"""Tests for the GPO-based data collection scripts (gpo/ folder).

These do NOT touch the web app fixtures from conftest.py.

What is covered:
  * every PowerShell script in gpo/ parses cleanly (Windows PowerShell parser)
  * Launcher.bat really points at agent-gpo.ps1
  * Merge-DeviceData.ps1 collapses duplicate headers + duplicate serial
    numbers and keeps the newest row (functional, in-process subprocess)
  * agent-gpo.ps1 end-to-end run against a local pseudo-share (opt-in:
    set GPO_AGENT_TEST=1, it exercises WMI and can take a few seconds)
"""
import base64
import os
import shutil
import subprocess
import csv
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
GPO_DIR = os.path.normpath(os.path.join(HERE, "..", "gpo"))

PS_SCRIPTS = [
    "agent-gpo.ps1",
    "Deploy-AssetGPO.ps1",
    "Merge-DeviceData.ps1",
    "collect-anywhere.ps1",
]

POWERSHELL = shutil.which("powershell.exe")
pytestmark = pytest.mark.skipif(
    POWERSHELL is None, reason="Windows PowerShell not available"
)


def _run_ps(command: str):
    """Run a PowerShell command using -EncodedCommand (avoids quoting hell)."""
    encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
    proc = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True,
        text=True,
        timeout=180,
    )
    return proc


def _run_ps_file(script: str, *args: str, timeout: int = 180):
    proc = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive",
         "-ExecutionPolicy", "Bypass", "-File", script, *args],
        capture_output=True, text=True, timeout=timeout,
    )
    return proc


# ──────────────────────────────────────────────────────────────────────────────
# static checks
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", PS_SCRIPTS)
def test_ps1_scripts_parse(name: str):
    """The Windows PowerShell parser must report zero syntax errors."""
    path = os.path.join(GPO_DIR, name).replace("'", "''")
    command = (
        "$t=$n=$null;"
        "[System.Management.Automation.Language.Parser]::ParseFile("
        f"'{path}', [ref]$t, [ref]$n) | Out-Null;"
        "if ($n -and @($n).Count -gt 0) { $n | ForEach-Object { Write-Output $_.Message }; exit 1 }"
        "Write-Output 'PARSE_OK'; exit 0"
    )
    proc = _run_ps(command)
    assert proc.returncode == 0, f"{name} failed to parse:\n{proc.stdout}"
    assert "PARSE_OK" in proc.stdout


def test_launcher_references_agent():
    """Launcher.bat (registered in the GPO) must actually call agent-gpo.ps1."""
    launcher = open(os.path.join(GPO_DIR, "Launcher.bat"), encoding="ascii").read()
    assert "agent-gpo.ps1" in launcher
    assert "-ExecutionPolicy Bypass" in launcher
    # GPO distributes files over SMB; the .bat must use CRLF and no BOM
    # (cmd.exe mis-parses BOM-prefixed batch files)
    raw = open(os.path.join(GPO_DIR, "Launcher.bat"), "rb").read()
    assert b"\r\n" in raw, "Launcher.bat should use CRLF line endings"
    assert not raw.startswith(b"\xef\xbb\xbf"), "Launcher.bat must not have a UTF-8 BOM"


def test_deploy_registers_launcher():
    """Deploy script must register Launcher.bat as a machine Startup script."""
    deploy = open(
        os.path.join(GPO_DIR, "Deploy-AssetGPO.ps1"), encoding="utf-8-sig"
    ).read()
    assert "0CmdLine=Launcher.bat" in deploy
    assert "scripts.ini" in deploy
    assert "New-GPLink" in deploy


# ──────────────────────────────────────────────────────────────────────────────
# functional: Merge-DeviceData.ps1
# ──────────────────────────────────────────────────────────────────────────────

HEADER = "collected_at,hostname,serial_number,ram_gb"
NEWEST = "2026-10-19 12:00:00,LTA,SN001,32"
OLDER  = "2026-10-12 09:00:00,LTA,SN001,16"
OTHER  = "2026-10-19 12:00:00,LTB,SN002,8"


def _write_sample(tmp_path, merged_name="merged.csv"):
    src = tmp_path / "device_inventory.csv"
    src.write_text(
        "\r\n".join([HEADER, NEWEST, HEADER, OLDER, OTHER, ""]) + "\r\n",
        encoding="utf-8",
    )
    out = tmp_path / merged_name
    proc = _run_ps_file(
        os.path.join(GPO_DIR, "Merge-DeviceData.ps1"),
        "-SourceCsv", str(src),
        "-OutputCsv", str(out),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert out.exists()
    return out, proc


def test_merge_collapses_duplicates(tmp_path):
    """One row per serial must remain, keeping the newest collected_at."""
    out, proc = _write_sample(tmp_path)
    assert "duplicate rows collapsed .....: 1" in proc.stdout
    rows = list(csv.DictReader(out.read_text(encoding="utf-8-sig").splitlines()))
    serials = sorted(r["serial_number"] for r in rows)
    assert serials == ["SN001", "SN002"]
    kept = {r["serial_number"]: r for r in rows}
    # the duplicate SN001 rows collapse to the NEWEST one (32 GB, Oct 19)
    assert kept["SN001"]["ram_gb"] == "32"
    assert kept["SN001"]["collected_at"] == "2026-10-19 12:00:00"
    # the stray duplicate header line must not become a data row
    assert kept["SN001"]["hostname"] == "LTA" and kept["SN002"]["hostname"] == "LTB"


def test_merge_report_counts_raw_rows(tmp_path):
    _, proc = _write_sample(tmp_path, "merged_report.csv")
    # 5 physical lines: header, NEWEST, dup header (data-ish), OLDER, OTHER
    assert "raw collected rows ...........: 3" in proc.stdout


# ──────────────────────────────────────────────────────────────────────────────
# functional: agent-gpo.ps1 (opt-in — touches WMI, a few seconds)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(
    not os.environ.get("GPO_AGENT_TEST"),
    reason="set GPO_AGENT_TEST=1 to run the full agent end-to-end",
)
def test_agent_gpo_writes_csv_row(tmp_path):
    share = tmp_path / "share"
    (share / "DeviceData").mkdir(parents=True)
    proc = _run_ps_file(
        os.path.join(GPO_DIR, "agent-gpo.ps1"),
        "-Share", str(share),
        "-Folder", "DeviceData",
        timeout=300,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    csv_file = share / "DeviceData" / "device_inventory.csv"
    assert csv_file.exists()
    rows = list(csv.DictReader(csv_file.read_text(encoding="utf-8-sig").splitlines()))
    assert len(rows) == 1
    row = rows[0]
    for column in ("collected_at", "hostname", "serial_number", "os_name",
                   "agent_version", "collection_method"):
        assert column in row, f"missing schema column {column!r}"
    assert row["collection_method"] == "gpo-startup"
    # second run must be a no-op (duplicate serial guard)
    proc2 = _run_ps_file(
        os.path.join(GPO_DIR, "agent-gpo.ps1"),
        "-Share", str(share),
        "-Folder", "DeviceData",
        timeout=300,
    )
    assert "already collected" in proc2.stdout
    rows2 = list(csv.DictReader(csv_file.read_text(encoding="utf-8-sig").splitlines()))
    assert len(rows2) == 1
