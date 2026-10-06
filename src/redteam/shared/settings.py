"""Central configuration, loaded from the environment and .env."""

from pydantic import BaseModel, ConfigDict
from pydantic_settings import BaseSettings, SettingsConfigDict

GROQ_BASE_URL = "https://api.groq.com/openai/v1"

ROLES = ("attacker", "judge", "target")


class RoleConfig(BaseModel):
    """What the LLM wrapper needs to know to call the model for one role."""

    model_config = ConfigDict(frozen=True)

    role: str
    provider: str
    model: str
    reasoning_effort: str | None = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    anthropic_api_key: str = ""
    groq_api_key: str = ""
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"  # default for any role without its own model

    llm_model_attacker: str | None = None
    llm_model_judge: str | None = None
    llm_model_target: str | None = None

    llm_reasoning_effort_attacker: str | None = None
    llm_reasoning_effort_judge: str | None = None
    llm_reasoning_effort_target: str | None = None

    llm_fallbacks: str = ""  # comma-separated model IDs, tried in order on failure

    def role_config(self, role: str) -> RoleConfig:
        if role not in ROLES:
            raise ValueError(f"unknown role {role!r}; expected one of {ROLES}")
        model: str = getattr(self, f"llm_model_{role}") or self.llm_model
        effort: str | None = getattr(self, f"llm_reasoning_effort_{role}") or None
        return RoleConfig(
            role=role,
            provider=self.llm_provider,
            model=model,
            reasoning_effort=effort,
        )

    def fallback_models(self) -> tuple[str, ...]:
        return tuple(m.strip() for m in self.llm_fallbacks.split(",") if m.strip())


def get_settings() -> Settings:
    return Settings()
