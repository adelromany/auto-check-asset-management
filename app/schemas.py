"""Pydantic request/response models (moved unchanged from main.py)."""

from typing import Optional

from pydantic import BaseModel


class AgentPayload(BaseModel):
    hostname:     Optional[str] = None
    username:     Optional[str] = None
    user_domain:  Optional[str] = None
    console_user: Optional[str] = None
    serial:       Optional[str] = None
    manufacturer: Optional[str] = None
    model:        Optional[str] = None
    cpu:          Optional[str] = None
    cpu_cores:    Optional[int] = None
    ram_gb:       Optional[float] = None
    disks:        Optional[list] = None   # [{name, size_gb, type}]
    os_name:      Optional[str] = None
    os_version:   Optional[str] = None
    os_arch:      Optional[str] = None
    ip_addresses:  Optional[list] = None  # [{iface, ip}]
    agent_os:     Optional[str] = None    # "windows" | "macos" | "linux"
    collected_at: Optional[str] = None
    # ── Phase 3 additions ──────────────────────────────────────────────
    software_checks:     Optional[list] = None
    # [{id, name, installed: bool, version: str|None, method: str}]
    windows_activation:  Optional[dict] = None
    # {status: str, status_code: int, product_name: str, partial_key: str}
