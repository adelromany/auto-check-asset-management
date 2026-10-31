"""Snipe-IT HTTP client: the only module that talks to Snipe-IT.

Every method returns a small typed result. HTTP statuses and network errors
are translated into the four client errors below; tokens never appear in an
exception message or a log line.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

import httpx


class SnipeItError(Exception):
    """Base class for every Snipe-IT client failure."""


class SnipeItUnavailable(SnipeItError):
    """The API could not be reached (network error or timeout)."""


class SnipeItAuthError(SnipeItError):
    """The API rejected the credentials, or no token is configured."""

    def __init__(self, message: str, *, status_code: int = 401):
        self.status_code = status_code
        super().__init__(message)


class SnipeItNotFound(SnipeItError):
    """The requested user, asset or file does not exist."""

    def __init__(self, message: str, *, status_code: int = 404):
        self.status_code = status_code
        super().__init__(message)


class SnipeItRejected(SnipeItError):
    """Snipe-IT answered with an unexpected HTTP status."""

    def __init__(self, message: str, *, status_code: int = 400):
        self.status_code = status_code
        super().__init__(message)


class SnipeItCredentialProvider(Protocol):
    """Where the client gets its bearer token.

    v1 uses one service account. The engineer's identity is carried in the
    Snipe-IT note and the portal event trail; see D-12 in 09-decisions.md.
    """

    def token_for(self, engineer_email: str, *, write: bool) -> str:
        ...


class ServiceAccountProvider:
    """The v1 credential provider: one shared service-account token."""

    def __init__(self, token: str):
        self._token = token

    def token_for(self, engineer_email: str, *, write: bool) -> str:
        if not self._token:
            raise SnipeItAuthError(
                "Snipe-IT token is not configured.", status_code=503
            )
        return self._token


@dataclass(frozen=True)
class SnipeItUser:
    id: int
    username: str | None = None
    name: str | None = None
    email: str | None = None


@dataclass(frozen=True)
class SnipeItAsset:
    id: int
    asset_tag: str | None = None
    name: str | None = None
    serial: str | None = None
    status: str | None = None
    model: str | None = None
    category: str | None = None
    manufacturer: str | None = None
    assigned_to_id: int | None = None
    assigned_to_name: str | None = None
    location: str | None = None
    last_checkout: str | None = None
    purchase_date: str | None = None
    warranty_months: int | None = None
    notes: str | None = None


@dataclass(frozen=True)
class SnipeItFile:
    id: int | None
    filename: str
    size: int | None = None


@dataclass(frozen=True)
class SnipeItActionResult:
    status: str
    message: str | None = None
    status_code: int | None = None


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _nested_name(value: Any) -> str | None:
    if isinstance(value, dict):
        name = value.get("name")
        return str(name) if name is not None else None
    return None


def _rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        rows = data.get("rows")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
        return [data]
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []


def _single_row(data: Any) -> dict[str, Any] | None:
    rows = _rows(data)
    return rows[0] if rows else None


def _asset_from_json(row: dict[str, Any]) -> SnipeItAsset:
    assigned_to = row.get("assigned_to")
    purchase_date = row.get("purchase_date")
    return SnipeItAsset(
        id=_int_or_none(row.get("id")) or 0,
        asset_tag=row.get("asset_tag"),
        name=row.get("name"),
        serial=row.get("serial"),
        status=_nested_name(row.get("status_label")),
        model=_nested_name(row.get("model")),
        category=_nested_name(row.get("category")),
        manufacturer=_nested_name(row.get("manufacturer")),
        assigned_to_id=(
            _int_or_none(assigned_to.get("id"))
            if isinstance(assigned_to, dict)
            else None
        ),
        assigned_to_name=_nested_name(assigned_to),
        location=_nested_name(row.get("location")),
        last_checkout=row.get("last_checkout"),
        purchase_date=(
            purchase_date.get("formatted")
            if isinstance(purchase_date, dict)
            else purchase_date
        ),
        warranty_months=_int_or_none(row.get("warranty_months")),
        notes=row.get("notes"),
    )


def _user_from_json(row: dict[str, Any]) -> SnipeItUser:
    return SnipeItUser(
        id=_int_or_none(row.get("id")) or 0,
        username=row.get("username"),
        name=row.get("name"),
        email=row.get("email"),
    )


def _file_from_json(row: dict[str, Any]) -> SnipeItFile:
    return SnipeItFile(
        id=_int_or_none(row.get("id")),
        filename=str(row.get("filename") or row.get("name") or ""),
        size=_int_or_none(row.get("size")),
    )


def _action_result(
    data: Any, *, status_code: int | None = None
) -> SnipeItActionResult:
    if not isinstance(data, dict):
        return SnipeItActionResult(status="success", status_code=status_code)
    status = str(data.get("status") or "success")
    messages = data.get("messages")
    if isinstance(messages, list):
        message = "; ".join(str(item) for item in messages)
    elif messages is None:
        message = None
    else:
        message = str(messages)
    return SnipeItActionResult(
        status=status, message=message, status_code=status_code
    )


class SnipeItClient:
    """Async Snipe-IT API client with typed results and safe retries."""

    def __init__(
        self,
        base_url: str,
        credential_provider: SnipeItCredentialProvider,
        *,
        timeout: float = 10.0,
        http_client: httpx.AsyncClient | None = None,
        engineer_email: str = "",
        max_retries: int = 2,
        retry_backoff: float = 0.1,
    ):
        self._base_url = base_url.rstrip("/")
        self._credentials = credential_provider
        self._timeout = timeout
        self._http_client = http_client
        self._owns_client = http_client is None
        self._engineer_email = engineer_email
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff

    async def __aenter__(self) -> "SnipeItClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client and self._http_client is not None:
            close = getattr(self._http_client, "aclose", None)
            if close is not None:
                await close()
        self._http_client = None

    # -- public API -------------------------------------------------------
    async def find_user(self, query: str) -> SnipeItUser | None:
        """Find a user by exact username, then exact email, then first match."""
        data = await self._get_json(
            "/api/v1/users", params={"search": query, "limit": 10}
        )
        rows = _rows(data)
        needle = query.strip().casefold()
        for row in rows:
            if str(row.get("username") or "").strip().casefold() == needle:
                return _user_from_json(row)
        for row in rows:
            if str(row.get("email") or "").strip().casefold() == needle:
                return _user_from_json(row)
        return _user_from_json(rows[0]) if rows else None

    async def search_users(
        self, query: str, *, limit: int = 10
    ) -> list[SnipeItUser]:
        """All users Snipe-IT matches for a free-text query (candidates)."""
        data = await self._get_json(
            "/api/v1/users", params={"search": query, "limit": limit}
        )
        return [_user_from_json(row) for row in _rows(data)]

    async def get_user(self, user_id: int) -> SnipeItUser:
        data = await self._get_json(f"/api/v1/users/{user_id}")
        row = _single_row(data)
        if row is None:
            raise SnipeItNotFound(f"Snipe-IT user {user_id} was not found.")
        return _user_from_json(row)

    async def list_user_assets(self, user_id: int) -> list[SnipeItAsset]:
        # Snipe-IT only applies the assigned_to filter when assigned_type is
        # also present (verified against Snipe-IT v8.8.3); without it every
        # asset in the instance is returned.
        data = await self._get_json(
            "/api/v1/hardware",
            params={
                "assigned_to": user_id,
                "assigned_type": "App\\Models\\User",
                "limit": 500,
            },
        )
        return [_asset_from_json(row) for row in _rows(data)]

    async def get_asset_by_serial(self, serial: str) -> SnipeItAsset:
        needle = serial.strip()
        data = await self._get_json(
            "/api/v1/hardware", params={"search": needle, "limit": 10}
        )
        rows = _rows(data)
        exact = next(
            (
                row
                for row in rows
                if str(row.get("serial") or "").strip() == needle
            ),
            None,
        )
        row = exact or (rows[0] if rows else None)
        if row is None:
            raise SnipeItNotFound(f"No device found for serial: {serial}")
        return _asset_from_json(row)

    async def get_asset(self, asset_id: int) -> SnipeItAsset:
        data = await self._get_json(f"/api/v1/hardware/{asset_id}")
        row = _single_row(data)
        if row is None:
            raise SnipeItNotFound(f"Snipe-IT asset {asset_id} was not found.")
        return _asset_from_json(row)

    async def checkout_asset_to_user(
        self, asset_id: int, user_id: int, note: str
    ) -> SnipeItActionResult:
        data, status_code = await self._post_json(
            f"/api/v1/hardware/{asset_id}/checkout",
            # Snipe-IT rejects "assigned_to" on this endpoint (verified against
            # v8.8.3): the user target must be sent as "assigned_user".
            json={
                "assigned_user": user_id,
                "checkout_to_type": "user",
                "note": note,
            },
        )
        return _action_result(data, status_code=status_code)

    async def checkin_asset(
        self, asset_id: int, note: str
    ) -> SnipeItActionResult:
        data, status_code = await self._post_json(
            f"/api/v1/hardware/{asset_id}/checkin", json={"note": note}
        )
        return _action_result(data, status_code=status_code)

    async def upload_asset_file(
        self,
        asset_id: int,
        filename: str,
        content: bytes,
        content_type: str,
        note: str,
    ) -> SnipeItActionResult:
        data, status_code = await self._post_json(
            f"/api/v1/hardware/{asset_id}/files",
            # Snipe-IT expects the multipart field "file[]" (verified against
            # v8.8.3); a plain "file" field is ignored and the upload fails.
            files={"file[]": (filename, content, content_type)},
            data={"note": note} if note else {},
        )
        return _action_result(data, status_code=status_code)

    async def list_asset_files(self, asset_id: int) -> list[SnipeItFile]:
        data = await self._get_json(f"/api/v1/hardware/{asset_id}/files")
        return [_file_from_json(row) for row in _rows(data)]

    async def whoami(self) -> SnipeItUser:
        data = await self._get_json("/api/v1/users/me")
        row = _single_row(data)
        return _user_from_json(row) if row else SnipeItUser(id=0)

    # -- transport --------------------------------------------------------
    def _client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=self._timeout)
            self._owns_client = True
        return self._http_client

    def _headers(self, *, write: bool) -> dict[str, str]:
        token = self._credentials.token_for(
            self._engineer_email, write=write
        )
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

    async def _get_json(
        self, path: str, *, params: dict[str, Any] | None = None
    ) -> Any:
        response = await self._request("GET", path, params=params, write=False)
        return self._json(response)

    async def _post_json(
        self,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> tuple[Any, int]:
        response = await self._request(
            "POST", path, json=json, files=files, data=data, write=True
        )
        if response.status_code == 204 or not getattr(response, "content", b""):
            return {}, response.status_code
        return self._json(response), response.status_code

    async def _request(
        self,
        method: str,
        path: str,
        *,
        write: bool,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> httpx.Response:
        url = f"{self._base_url}{path}"
        headers = self._headers(write=write)
        attempt = 0
        while True:
            try:
                client = self._client()
                if method == "GET":
                    response = await client.get(
                        url, headers=headers, params=params
                    )
                else:
                    kwargs: dict[str, Any] = {"headers": headers}
                    if json is not None:
                        kwargs["json"] = json
                    if files is not None:
                        kwargs["files"] = files
                    if data is not None:
                        kwargs["data"] = data
                    response = await client.post(url, **kwargs)
            except httpx.RequestError as exc:
                if method == "GET" and attempt < self._max_retries:
                    attempt += 1
                    await asyncio.sleep(self._retry_backoff * attempt)
                    continue
                raise SnipeItUnavailable(
                    "Could not reach Snipe-IT."
                ) from exc

            if (
                method == "GET"
                and response.status_code >= 500
                and attempt < self._max_retries
            ):
                attempt += 1
                await asyncio.sleep(self._retry_backoff * attempt)
                continue

            self._raise_for_status(response)
            return response

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        status = response.status_code
        if status in (401, 403):
            raise SnipeItAuthError(
                f"Snipe-IT rejected the credentials (HTTP {status}).",
                status_code=status,
            )
        if status == 404:
            raise SnipeItNotFound("Snipe-IT resource not found.")
        if status >= 400:
            raise SnipeItRejected(
                f"Snipe-IT returned HTTP {status}.", status_code=status
            )

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise SnipeItRejected(
                "Snipe-IT returned invalid JSON.",
                status_code=response.status_code,
            ) from exc
