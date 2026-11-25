"""Configuration defaults used by the V2 workflows."""

from app import config


def test_maintenance_and_ready_status_defaults() -> None:
    assert config.SNIPEIT_STATUS_MAINTENANCE == "Maintenance"
    assert config.SNIPEIT_STATUS_READY == "Ready to deploy"
