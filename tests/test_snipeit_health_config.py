"""Configuration feedback for the Snipe-IT health indicator."""


def test_health_reports_missing_token_without_secret(make_client):
    client, _ = make_client(SNIPEIT_URL="http://snipeit.test", SNIPEIT_TOKEN="")
    result = client.get("/api/snipeit/health").json()

    assert result["connected"] is False
    assert result["reason"] == "token_not_configured"
    assert set(result) == {"connected", "reason"}


def test_health_reports_missing_url_without_secret(make_client):
    client, _ = make_client(SNIPEIT_URL="", SNIPEIT_TOKEN="unused-placeholder")
    result = client.get("/api/snipeit/health").json()

    assert result["connected"] is False
    assert result["reason"] == "not_configured"
    assert result["message"] == "Snipe-IT is not configured."
    assert "unused-placeholder" not in str(result)
