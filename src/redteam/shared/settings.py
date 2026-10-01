"""Central configuration, loaded from the environment and .env."""

from pydantic_settings import BaseSettings, SettingsConfigDict

GROQ_BASE_URL = "https://api.groq.com/openai/v1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    anthropic_api_key: str = ""
    groq_api_key: str = ""
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"


def get_settings() -> Settings:
    return Settings()
