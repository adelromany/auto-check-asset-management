"""Pure extraction of a reported interactive recipient identity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DetectedUser:
    sam: str
    domain: str | None
    raw: str
    is_local: bool
    same_as_engineer: bool


def detect_recipient(
    report: dict[str, Any], engineer_email: str
) -> DetectedUser:
    """Prefer the interactive console account, falling back to script identity."""
    console_raw = str(report.get("console_user") or "").strip()
    fallback_sam = str(report.get("username") or "").strip()
    fallback_domain = str(report.get("user_domain") or "").strip()
    hostname = str(report.get("hostname") or "").strip()

    if console_raw:
        raw = console_raw
        if "\\" in raw:
            domain, sam = raw.split("\\", 1)
        elif "/" in raw:
            domain, sam = raw.split("/", 1)
        else:
            domain, sam = fallback_domain, raw
    else:
        raw = fallback_sam
        domain, sam = fallback_domain, fallback_sam

    domain = domain.strip() or None
    sam = sam.strip().rsplit("\\", 1)[-1].casefold()
    engineer_sam = str(engineer_email or "").partition("@")[0].casefold()
    is_local = not domain or domain.casefold() == hostname.casefold()
    return DetectedUser(
        sam=sam,
        domain=domain,
        raw=raw,
        is_local=is_local,
        same_as_engineer=bool(sam and sam == engineer_sam),
    )
