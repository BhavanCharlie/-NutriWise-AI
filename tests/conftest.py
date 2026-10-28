"""Shared test setup. pytest loads this file automatically.

Fixtures marked autouse=True run for EVERY test without being asked for.
"""

import pytest
import requests

from app import storage


@pytest.fixture(autouse=True)
def temp_data_file(tmp_path, monkeypatch):
    """Point storage at a fresh temporary file, so tests never touch your real meal log."""
    path = tmp_path / "meals.json"
    monkeypatch.setattr(storage, "DATA_FILE", path)
    return path


@pytest.fixture(autouse=True)
def no_network(request, monkeypatch):
    """Block real HTTP and Gemini calls (slow, flaky, uses quota). Live tests are exempt."""
    if request.node.get_closest_marker("live"):
        return

    def blocked(*args, **kwargs):
        raise requests.ConnectionError("network is blocked in unit tests")

    monkeypatch.setattr(requests, "get", blocked)
    monkeypatch.setattr(requests, "post", blocked)
    monkeypatch.setattr("app.llm.genai.Client", blocked)


@pytest.fixture
def llm_keys(monkeypatch):
    """Pretend every LLM key is configured (the providers themselves get faked per test)."""
    for key in ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.setenv(key, "test-key")
    monkeypatch.setattr("app.llm.RETRY_DELAYS", [0])  # don't actually sleep in tests
