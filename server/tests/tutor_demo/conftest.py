import pytest


@pytest.fixture(autouse=True)
def isolated_pilot_budget(tmp_path, monkeypatch):
    """Tests never consume the deployed pilot budget or wait for real cooldowns."""
    monkeypatch.setenv("TUTOR_USAGE_DB", str(tmp_path / "usage.sqlite3"))
    monkeypatch.setenv("TUTOR_FAILURE_COOLDOWN_SECONDS", "0")
