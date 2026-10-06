import pytest

from redteam.shared.pricing import notional_cost_usd
from redteam.shared.settings import Settings

_VARS = [
    "LLM_PROVIDER",
    "LLM_MODEL",
    "LLM_MODEL_ATTACKER",
    "LLM_MODEL_JUDGE",
    "LLM_MODEL_TARGET",
    "LLM_REASONING_EFFORT_ATTACKER",
    "LLM_REASONING_EFFORT_JUDGE",
    "LLM_REASONING_EFFORT_TARGET",
    "LLM_FALLBACKS",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _VARS:
        monkeypatch.delenv(name, raising=False)


def _settings(**kwargs: object) -> Settings:
    return Settings(_env_file=None, **kwargs)


def test_role_falls_back_to_default_model() -> None:
    s = _settings(llm_model="default/model")
    assert s.role_config("judge").model == "default/model"


def test_role_override_is_used() -> None:
    s = _settings(llm_model="default/model", llm_model_attacker="qwen/x")
    assert s.role_config("attacker").model == "qwen/x"
    assert s.role_config("judge").model == "default/model"


def test_unknown_role_is_rejected() -> None:
    with pytest.raises(ValueError):
        _settings().role_config("hacker")


def test_reasoning_effort_defaults_to_none() -> None:
    assert _settings().role_config("attacker").reasoning_effort is None


def test_reasoning_effort_is_per_role() -> None:
    s = _settings(llm_reasoning_effort_attacker="low")
    assert s.role_config("attacker").reasoning_effort == "low"
    assert s.role_config("target").reasoning_effort is None


def test_fallback_models_are_parsed() -> None:
    s = _settings(llm_fallbacks="a/one, b/two,")
    assert s.fallback_models() == ("a/one", "b/two")


def test_no_fallbacks_when_empty() -> None:
    assert _settings().fallback_models() == ()


def test_price_for_known_models() -> None:
    assert notional_cost_usd("openai/gpt-oss-120b", 1_000_000, 1_000_000) == pytest.approx(0.75)
    assert notional_cost_usd("qwen/qwen3.8-27b", 1_000_000, 1_000_000) == pytest.approx(4.80)


def test_zero_tokens_cost_nothing() -> None:
    assert notional_cost_usd("openai/gpt-oss-120b", 0, 0) == 0


def test_unknown_model_price_raises() -> None:
    with pytest.raises(ValueError):
        notional_cost_usd("no/such-model", 10, 10)


def test_temperature_is_per_role() -> None:
    s = _settings(llm_temperature_attacker=0.7)
    assert s.role_config("attacker").temperature == 0.7
    assert s.role_config("judge").temperature is None
