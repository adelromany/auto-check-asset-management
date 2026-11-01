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


class PrintConflict(HandoverError):
    """A print action is not valid in the current state (409)."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class PrintUnavailable(HandoverError):
    """The print pipeline cannot run on this host (503)."""


class PrintDocumentMissing(HandoverError):
    """No rendered PDF is stored for this handover (404)."""


class InvalidStage(HandoverError):
    """The stage key is not one of the nine fixed stages."""

    def __init__(self, key: str):
        self.key = key
        super().__init__(f"Unknown stage: {key}")


class DocumentNotFound(HandoverError):
    """No stored document exists for this handover."""


class DocumentTooLarge(HandoverError):
    """The uploaded document exceeds DOCUMENT_MAX_BYTES."""


class UnsupportedDocumentType(HandoverError):
    """The uploaded bytes are not a PDF, PNG or JPEG."""


class AgentReportNotFound(HandoverError):
    """The printable report needs a stored agent report first."""


class SoftwareCheckConflict(HandoverError):
    """The software-check command is not valid in its current state."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class RecipientConfirmationConflict(HandoverError):
    """A reported identity requires an explicit engineer acknowledgement."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)
