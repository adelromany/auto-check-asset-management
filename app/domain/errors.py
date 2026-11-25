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
    """Legacy name kept for callers; new code raises :class:`InputMissing`."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class InputMissing(HandoverError):
    """An operation cannot run yet because its own input is missing (422).

    This is not an ordering rule: it only names data this operation needs,
    and every other operation stays available.
    """

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class NotDoneReasonRequired(HandoverError):
    """Marking an operation not done requires a 3–300 character reason."""

    def __init__(self, reason: str = "A reason is required to mark an operation not done."):
        self.reason = reason
        super().__init__(reason)


class OperationNotInKind(HandoverError):
    """The operation key does not belong to this case kind."""

    def __init__(self, operation: str, kind: str):
        self.operation = operation
        self.kind = kind
        super().__init__(f"Operation '{operation}' is not part of a {kind} case.")


class CaseStateConflict(HandoverError):
    """The requested transition is not valid for the case's current status."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class ClosingConfirmationRequired(HandoverError):
    """Closing with gaps needs the explicit confirmation text."""

    def __init__(self, reason: str = "Type CLOSE to confirm closing a case with gaps."):
        self.reason = reason
        super().__init__(reason)


class MaintenanceFieldInvalid(HandoverError):
    """A maintenance field is missing or has an unsupported value."""

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


class DocumentNotFound(HandoverError):
    """No stored document exists for this handover."""


class FormTemplateNotFound(HandoverError):
    """No handover form template exists for the device company."""


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


class DeviceNotInSnipeIt(HandoverError):
    """The serial is unknown to Snipe-IT (422)."""

    def __init__(
        self, reason: str = "Serial not found in Snipe-IT"
    ):
        self.reason = reason
        super().__init__(reason)


class SnipeItUnreachable(HandoverError):
    """Snipe-IT could not be reached (503)."""

    def __init__(self, reason: str = "Snipe-IT is unreachable."):
        self.reason = reason
        super().__init__(reason)


class CompanyMismatch(HandoverError):
    """The recipient company differs from the device company."""

    code = "company_mismatch"

    def __init__(
        self,
        reason: str = "Recipient company differs from the device company",
    ):
        self.reason = reason
        super().__init__(reason)
