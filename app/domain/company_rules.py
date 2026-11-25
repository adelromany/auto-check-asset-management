"""Pure company matching rules for handover recipients."""

from __future__ import annotations


def normalize_company(name: str | None) -> str:
    """Return a comparable company name containing only letters and digits."""
    if not name:
        return ""
    return "".join(character for character in name.casefold() if character.isalnum())


def company_known(name: str | None) -> bool:
    """Return whether a company name contains a usable company identifier."""
    return bool(normalize_company(name))


def company_conflict(
    device_company: str | None, recipient_company: str | None
) -> bool:
    """Return true only when two known companies are different."""
    device = normalize_company(device_company)
    recipient = normalize_company(recipient_company)
    return bool(device and recipient and device != recipient)
