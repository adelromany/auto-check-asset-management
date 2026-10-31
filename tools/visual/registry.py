"""The ordered list of committed visual artifacts.

Part 1 registers nothing; later branches append the principle, graph and
handover artifacts.  Keeping the registry here means the build/check entry
point never needs to know how a particular diagram is authored.
"""

from __future__ import annotations

from .artifacts import Artifact

ARTIFACTS: list[Artifact] = []
