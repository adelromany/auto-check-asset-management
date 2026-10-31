"""Small, testable wrapper around the pinned Archify CLI.

Archify is fetched into the git-ignored ``.tools/archify`` folder by
``scripts/fetch_archify.sh`` / ``scripts/fetch_archify.ps1``. It is a
development tool only: nothing here is imported by the portal at runtime.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = REPO_ROOT / ".tools" / "archify"
CLI = TOOLS_DIR / "archify" / "bin" / "archify.mjs"
PINNED_VERSION = "3.2.0"
PINNED_COMMIT = "a4065941f12be7967436261d9934784e381d423c"


class ArchifyError(RuntimeError):
    """Raised when the CLI is missing or a command does not succeed."""


def available() -> bool:
    return CLI.is_file()


def require() -> Path:
    if not available():
        raise ArchifyError(
            "Archify is not fetched. Run scripts/fetch_archify.sh "
            "(or scripts/fetch_archify.ps1 on Windows)."
        )
    return CLI


def node_version() -> str:
    proc = subprocess.run(
        ["node", "--version"], cwd=REPO_ROOT, capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise ArchifyError(f"node --version failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run the CLI from the repository root and return the completed process."""
    require()
    proc = subprocess.run(
        ["node", str(CLI), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and proc.returncode != 0:
        detail = (proc.stdout + "\n" + proc.stderr).strip()
        raise ArchifyError(f"archify {' '.join(args)} failed:\n{detail}")
    return proc


def _json_from_stdout(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    if not text:
        raise ArchifyError("Archify produced no JSON output")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ArchifyError(f"Archify output is not JSON:\n{text}") from None
        return json.loads(text[start : end + 1])


def doctor() -> dict[str, Any] | str:
    proc = run(["doctor"])
    return proc.stdout


def validate(
    diagram_type: str,
    source: Path,
    *,
    quality: str = "showcase",
    writing: str = "strict",
) -> dict[str, Any]:
    args = [
        "validate",
        diagram_type,
        str(source),
        "--quality",
        quality,
        "--json",
    ]
    if diagram_type == "explainer":
        args += ["--writing", writing]
    proc = run(args, check=False)
    receipt = _json_from_stdout(proc.stdout)
    if proc.returncode != 0:
        receipt["_command_failed"] = True
        receipt["_stderr"] = proc.stderr.strip()
    return receipt


def finalize(
    diagram_type: str,
    source: Path,
    output: Path,
    *,
    quality: str = "showcase",
    writing: str = "strict",
    out_dir: Path | None = None,
) -> dict[str, Any]:
    args = [
        "finalize",
        diagram_type,
        str(source),
        str(output),
        "--quality",
        quality,
        "--json",
    ]
    if diagram_type == "explainer":
        args += ["--writing", writing]
    if out_dir is not None:
        args += ["--out-dir", str(out_dir)]
    proc = run(args, check=False)
    receipt = _json_from_stdout(proc.stdout)
    if proc.returncode != 0:
        receipt["_command_failed"] = True
        receipt["_stderr"] = proc.stderr.strip()
    return receipt


def visual_check(
    output: Path, *, out_dir: Path | None = None
) -> dict[str, Any]:
    args = ["visual-check", str(output), "--summary", "--require-provenance"]
    if out_dir is not None:
        args += ["--out-dir", str(out_dir)]
    proc = run(args, check=False)
    receipt = _json_from_stdout(proc.stdout)
    if proc.returncode != 0:
        receipt["_command_failed"] = True
        receipt["_stderr"] = proc.stderr.strip()
    return receipt


def diagnostics(receipt: dict[str, Any]) -> list[dict[str, Any]]:
    """Return every diagnostic found in a validation/finalize receipt."""
    found: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "diagnostics" and isinstance(item, list):
                    found.extend(x for x in item if isinstance(x, dict))
                else:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(receipt)
    return found


def problems(receipt: dict[str, Any]) -> list[str]:
    """Human-readable blocking problems from a receipt."""
    result: list[str] = []
    for item in diagnostics(receipt):
        severity = str(item.get("severity", "error")).lower()
        if severity == "warning":
            result.append(f"warning {item.get('code', '?')}: {item.get('message', '')}")
        elif severity in {"error", "fatal"}:
            result.append(f"error {item.get('code', '?')}: {item.get('message', '')}")
    if receipt.get("_command_failed"):
        result.append("command failed: " + str(receipt.get("_stderr", "")).strip())
    return result
