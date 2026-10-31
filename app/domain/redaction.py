"""Redaction of agent payloads before storage (SEC-19).

The Windows partial product key is never stored and never logged.
"""

from __future__ import annotations

import copy
from typing import Any


def redact_agent_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a deep copy of ``payload`` without the activation partial key."""
    redacted = copy.deepcopy(payload)
    activation = redacted.get("windows_activation")
    if isinstance(activation, dict):
        activation.pop("partial_key", None)
    return redacted
