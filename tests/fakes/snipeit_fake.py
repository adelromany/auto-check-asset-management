"""A stateful Snipe-IT fake built on ``httpx.MockTransport``.

Tests never call a real Snipe-IT. The fake implements exactly the endpoints
the client uses and records every call so tests can assert retry behavior.
"""

from __future__ import annotations

import json
from email.parser import BytesParser
from email.policy import default
from typing import Any

import httpx


class SnipeItFake:
    """In-memory users, assets and files behind a MockTransport."""

    def __init__(self, token: str = "test-token"):
        self.token = token
        self.calls: list[tuple[str, str, dict[str, str]]] = []
        self.fail_get_statuses: list[int] = []
        self.fail_post_statuses: list[int] = []
        self.users: dict[int, dict[str, Any]] = {
            1: {
                "id": 1,
                "username": "alice",
                "name": "Alice",
                "email": "alice@example.com",
            },
            2: {
                "id": 2,
                "username": "bob",
                "name": "Bob",
                "email": "bob@example.com",
            },
        }
        self.assets: dict[int, dict[str, Any]] = {
            10: self._asset(10, "A-10", "SN-10", assigned_to=None),
            11: self._asset(
                11,
                "A-11",
                "SN-11",
                assigned_to={"id": 1, "name": "Alice", "username": "alice"},
            ),
        }
        self.files: dict[int, list[dict[str, Any]]] = {10: [], 11: []}
        self._next_file_id = 100

    @staticmethod
    def _asset(
        asset_id: int,
        asset_tag: str,
        serial: str,
        *,
        assigned_to: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "id": asset_id,
            "asset_tag": asset_tag,
            "name": f"Laptop {asset_id}",
            "serial": serial,
            "status_label": {"name": "Ready"},
            "model": {"name": "ThinkPad T14"},
            "category": {"name": "Laptops"},
            "manufacturer": {"name": "Lenovo"},
            "assigned_to": assigned_to,
            "location": {"name": "HQ"},
            "last_checkout": None,
            "purchase_date": {"formatted": "2024-01-01"},
            "warranty_months": 36,
            "notes": "ok",
        }

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(
            (request.method, request.url.path, dict(request.url.params))
        )

        if request.headers.get("Authorization") != f"Bearer {self.token}":
            return httpx.Response(
                401, json={"status": "error", "messages": ["Unauthorized"]}
            )

        if request.method == "GET" and self.fail_get_statuses:
            status = self.fail_get_statuses.pop(0)
            return httpx.Response(status, json={"status": "error"})
        if request.method == "POST" and self.fail_post_statuses:
            status = self.fail_post_statuses.pop(0)
            return httpx.Response(status, json={"status": "error"})

        parts = [part for part in request.url.path.strip("/").split("/") if part]
        if parts[:3] == ["api", "v1", "users"]:
            return self._users(request, parts)
        if parts[:3] == ["api", "v1", "hardware"]:
            return self._hardware(request, parts)
        return httpx.Response(404, json={"status": "error"})

    # -- endpoints --------------------------------------------------------
    def _users(
        self, request: httpx.Request, parts: list[str]
    ) -> httpx.Response:
        if len(parts) == 4 and parts[3] == "me":
            return httpx.Response(200, json=self.users[1])
        if len(parts) == 3:
            query = request.url.params.get("search", "").casefold()
            rows = [
                user
                for user in self.users.values()
                if not query
                or query
                in f"{user['username']} {user['email']} {user['name']}".casefold()
            ]
            return httpx.Response(200, json={"rows": rows})
        user = self.users.get(int(parts[3]))
        if user is None:
            return httpx.Response(404, json={"status": "error"})
        return httpx.Response(200, json=user)

    def _hardware(
        self, request: httpx.Request, parts: list[str]
    ) -> httpx.Response:
        if len(parts) == 3:
            rows = list(self.assets.values())
            search = request.url.params.get("search")
            assigned_to = request.url.params.get("assigned_to")
            if search is not None:
                needle = search.casefold()
                rows = [
                    asset
                    for asset in rows
                    if needle
                    in f"{asset['serial']} {asset['asset_tag']} {asset['name']}".casefold()
                ]
            elif assigned_to is not None:
                user_id = int(assigned_to)
                rows = [
                    asset
                    for asset in rows
                    if (asset["assigned_to"] or {}).get("id") == user_id
                ]
            return httpx.Response(200, json={"rows": rows})

        asset = self.assets.get(int(parts[3]))
        if asset is None:
            return httpx.Response(404, json={"status": "error"})
        if len(parts) == 4:
            return httpx.Response(200, json=asset)

        action = parts[4]
        if action == "checkout":
            body = json.loads(request.content or b"{}")
            user = self.users.get(int(body["assigned_to"]))
            if user is None:
                return httpx.Response(404, json={"status": "error"})
            asset["assigned_to"] = {
                "id": user["id"],
                "name": user["name"],
                "username": user["username"],
            }
            return httpx.Response(
                200, json={"status": "success", "messages": "Checked out"}
            )
        if action == "checkin":
            asset["assigned_to"] = None
            return httpx.Response(
                200, json={"status": "success", "messages": "Checked in"}
            )
        if action == "files":
            if request.method == "GET":
                return httpx.Response(
                    200, json={"rows": self.files.get(asset["id"], [])}
                )
            filename, payload = self._multipart_file(request)
            record = {
                "id": self._next_file_id,
                "filename": filename,
                "size": len(payload),
            }
            self._next_file_id += 1
            self.files.setdefault(asset["id"], []).append(record)
            return httpx.Response(
                200, json={"status": "success", "messages": "Uploaded"}
            )
        return httpx.Response(404, json={"status": "error"})

    @staticmethod
    def _multipart_file(request: httpx.Request) -> tuple[str, bytes]:
        content_type = request.headers.get("content-type", "")
        raw = (
            b"Content-Type: "
            + content_type.encode()
            + b"\r\nMIME-Version: 1.0\r\n\r\n"
            + request.content
        )
        message = BytesParser(policy=default).parsebytes(raw)
        for part in message.iter_parts():
            if part.get_param("name", header="content-disposition") == "file":
                return (
                    part.get_filename() or "upload.bin",
                    part.get_payload(decode=True) or b"",
                )
        return "upload.bin", b""

    # -- assertions helpers ----------------------------------------------
    def write_calls(self) -> list[tuple[str, str, dict[str, str]]]:
        return [call for call in self.calls if call[0] == "POST"]
