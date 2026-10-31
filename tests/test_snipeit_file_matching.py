"""Snipe-IT rewrites uploaded file names; verification uses suffix and size."""

from types import SimpleNamespace

import httpx
import pytest

from app.clients import snipeit
from app.clients.snipeit import SnipeItFile
from app.services.documents import _file_present
from tests.fakes.snipeit_fake import SnipeItFake


@pytest.mark.parametrize(
    ("filename", "size", "expected"),
    [
        ("test-live-upload.pdf", 42, True),
        ("asset-4-a1B2c3D4-test-live-upload.pdf", 42, True),
        ("asset-4-a1B2c3D4-my-sheet-signed.pdf", 42, True),
        ("asset-4-a1B2c3D4-other.pdf", 42, False),
        ("asset-4-a1B2c3D4-test-live-upload.pdf", 41, True),
        ("asset-4-a1B2c3D4-test-live-upload.pdf", None, True),
        ("asset-5-2TYTKKFI-ghlaf.png", None, True),
    ],
)
def test_file_presence_matches_snipeit_sanitized_suffix(
    filename: str, size: int | None, expected: bool
) -> None:
    document = SimpleNamespace(
        original_name=(
            "My_Sheet (Signed).pdf"
            if "my-sheet-signed" in filename
            else "غلاف.png"
            if filename.endswith("ghlaf.png")
            else "TEST-live-upload.pdf"
        ),
        size_bytes=42,
    )

    assert _file_present([SnipeItFile(1, filename, size)], document) is expected


async def test_client_maps_server_renamed_upload_to_original_name() -> None:
    fake = SnipeItFake()
    async with httpx.AsyncClient(transport=fake.transport) as transport:
        client = snipeit.SnipeItClient(
            "http://snipeit.test",
            snipeit.ServiceAccountProvider("test-token"),
            http_client=transport,
        )
        original_name = "TEST-live-upload.pdf"
        content = b"%PDF-1.4 test"

        result = await client.upload_asset_file(
            10, original_name, content, "application/pdf", "TEST- test"
        )
        files = await client.list_asset_files(10)

    assert result.status == "success"
    assert files[0].filename == original_name
    assert fake.files[10][0]["filename"] == original_name
    assert fake.files[10][0]["stored_filename"].endswith(
        "-test-live-upload.pdf"
    )
