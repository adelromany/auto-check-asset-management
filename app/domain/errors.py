"""Typed exceptions shared by services and routers (ARC-04).

The domain has no framework imports; routers translate these into HTTP.
"""


class HandoverError(Exception):
    """Base class for handover workflow errors."""


class HandoverNotFound(HandoverError):
    """No handover exists with that id."""


class HandoverAlreadyExists(HandoverError):
    """An active handover already exists for the device serial."""


class HandoverCancelled(HandoverError):
    """The handover was cancelled and accepts no further work."""


class HandoverCompleted(HandoverError):
    """The handover is completed and accepts no further work."""


class StageNotRunnable(HandoverError):
    """A stage's dependencies have not passed yet."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class ManualStageRequired(HandoverError):
    """The stage is not one an engineer may confirm by hand."""


class InvalidStage(HandoverError):
    """The stage key is not one of the nine fixed stages."""

    def __init__(self, key: str):
        self.key = key
        super().__init__(f"Unknown stage: {key}")
