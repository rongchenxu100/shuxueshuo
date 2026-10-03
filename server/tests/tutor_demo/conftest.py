import pytest


@pytest.fixture(autouse=True)
def isolated_pilot_budget(monkeypatch):
    """Tests never consume the deployed pilot budget or wait for real cooldowns."""
    monkeypatch.setenv("TUTOR_FAILURE_COOLDOWN_SECONDS", "0")
