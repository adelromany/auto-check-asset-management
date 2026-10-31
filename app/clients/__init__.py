"""External-system clients. All Snipe-IT HTTP lives in this package."""

from app.clients.snipeit import (
    ServiceAccountProvider,
    SnipeItActionResult,
    SnipeItAsset,
    SnipeItAuthError,
    SnipeItClient,
    SnipeItCredentialProvider,
    SnipeItError,
    SnipeItFile,
    SnipeItNotFound,
    SnipeItRejected,
    SnipeItUnavailable,
    SnipeItUser,
)

__all__ = [
    "ServiceAccountProvider",
    "SnipeItActionResult",
    "SnipeItAsset",
    "SnipeItAuthError",
    "SnipeItClient",
    "SnipeItCredentialProvider",
    "SnipeItError",
    "SnipeItFile",
    "SnipeItNotFound",
    "SnipeItRejected",
    "SnipeItUnavailable",
    "SnipeItUser",
]
