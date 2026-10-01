from redteam.shared.settings import get_settings


def test_settings_load_with_defaults() -> None:
    s = get_settings()
    assert s.llm_provider in {"openai", "anthropic", "groq"}
    assert s.llm_model != ""


def test_groq_config_present() -> None:
    s = get_settings()
    if s.llm_provider == "groq":
        assert s.groq_api_key != ""
