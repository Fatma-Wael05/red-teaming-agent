import pytest

from redteam.shared.settings import get_settings


def test_settings_load_with_defaults() -> None:
    s = get_settings()
    assert s.llm_provider in {"openai", "anthropic", "groq"}
    assert s.llm_model != ""


def test_settings_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("LLM_MODEL", "some/model")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    s = get_settings()
    assert s.llm_provider == "groq"
    assert s.llm_model == "some/model"
    assert s.groq_api_key == "test-key"
