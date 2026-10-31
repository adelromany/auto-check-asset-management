"""Domain identity parsing for the interactive Windows user."""

import pytest

from app.domain.recipient_identity import detect_recipient


@pytest.mark.parametrize(
    ("report", "expected_sam", "expected_domain", "is_local", "same_engineer"),
    [
        ({"console_user": r"ACME\Alice", "username": "admin", "hostname": "PC"}, "alice", "ACME", False, False),
        ({"console_user": "", "username": "Alice", "user_domain": "ACME", "hostname": "PC"}, "alice", "ACME", False, False),
        ({"username": "PC\\Local", "hostname": "PC"}, "local", None, True, False),
        ({"username": "MOHAMED", "user_domain": "ACME", "hostname": "PC"}, "mohamed", "ACME", False, True),
        ({"username": "", "user_domain": "", "hostname": "PC"}, "", None, True, False),
    ],
)
def test_detect_recipient(report, expected_sam, expected_domain, is_local, same_engineer):
    detected = detect_recipient(report, "Mohamed@example.com")

    assert detected.sam == expected_sam
    assert detected.domain == expected_domain
    assert detected.is_local is is_local
    assert detected.same_as_engineer is same_engineer
