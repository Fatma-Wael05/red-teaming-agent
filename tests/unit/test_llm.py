import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from redteam.shared.llm import (
    AllModelsFailed,
    LLMClient,
    LLMError,
    MissingKeyError,
    build_client,
    is_retryable,
)
from redteam.shared.schemas import LLMCallLog
from redteam.shared.settings import Settings
from redteam.shared.storage import read_jsonl

MSGS = [{"role": "user", "content": "hi"}]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.startswith("LLM_"):
            monkeypatch.delenv(name)


def _settings(**over: Any) -> Settings:
    base: dict[str, Any] = {
        "llm_provider": "groq",
        "llm_model": "openai/gpt-oss-120b",
        "llm_model_attacker": "qwen/qwen3.8-27b",
        "llm_reasoning_effort_attacker": "none",
        "llm_fallbacks": "openai/gpt-oss-120b",
        "groq_api_key": "test-key",
    }
    base.update(over)
    return Settings(_env_file=None, **base)


def _resp(text: str = "ok", finish: str = "stop", pt: int = 10, ct: int = 5) -> Any:
    message = SimpleNamespace(content=text)
    choice = SimpleNamespace(message=message, finish_reason=finish)
    usage = SimpleNamespace(prompt_tokens=pt, completion_tokens=ct)
    return SimpleNamespace(choices=[choice], usage=usage)


class _HTTPError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"http {status_code}")
        self.status_code = status_code


class _FakeClient:
    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _make(
    script: list[Any],
    *,
    log_path: Path | None = None,
    settings: Settings | None = None,
) -> tuple[LLMClient, _FakeClient, list[float]]:
    fake = _FakeClient(script)
    sleeps: list[float] = []
    llm = LLMClient(
        settings or _settings(),
        log_path,
        client_factory=lambda _provider: fake,
        max_retries=2,
        backoff_s=0.5,
        sleep=sleeps.append,
    )
    return llm, fake, sleeps


def test_role_is_routed_to_its_model_with_reasoning_effort() -> None:
    llm, fake, _ = _make([_resp()])
    result = llm.chat("attacker", MSGS)
    assert result.text == "ok"
    assert fake.calls[0]["model"] == "qwen/qwen3.8-27b"
    assert fake.calls[0]["reasoning_effort"] == "none"
    assert fake.calls[0]["messages"] == MSGS


def test_roles_without_effort_send_none() -> None:
    llm, fake, _ = _make([_resp()])
    llm.chat("judge", MSGS)
    assert fake.calls[0]["model"] == "openai/gpt-oss-120b"
    assert "reasoning_effort" not in fake.calls[0]


def test_call_is_logged_with_notional_cost(tmp_path: Path) -> None:
    path = tmp_path / "llm_calls.jsonl"
    llm, _, _ = _make([_resp(pt=1_000_000, ct=0)], log_path=path)
    llm.chat("judge", MSGS)
    logs = read_jsonl(path, LLMCallLog)
    assert len(logs) == 1
    assert logs[0].input_tokens == 1_000_000
    assert logs[0].cost_usd == pytest.approx(0.15)
    assert logs[0].role == "judge"
    assert logs[0].provider == "groq"


def test_rate_limit_is_retried() -> None:
    llm, fake, sleeps = _make([_HTTPError(429), _resp()])
    assert llm.chat("judge", MSGS).text == "ok"
    assert len(fake.calls) == 2
    assert sleeps == [0.5]


def test_backoff_doubles() -> None:
    llm, _, sleeps = _make([_HTTPError(429), _HTTPError(429), _resp()])
    llm.chat("judge", MSGS)
    assert sleeps == [0.5, 1.0]


def test_falls_back_after_retries_and_drops_reasoning_effort() -> None:
    script = [_HTTPError(429), _HTTPError(429), _HTTPError(429), _resp(text="fallback ok")]
    llm, fake, _ = _make(script)
    result = llm.chat("attacker", MSGS)
    assert result.text == "fallback ok"
    assert result.call.requested_model == "qwen/qwen3.8-27b"
    assert result.call.model == "openai/gpt-oss-120b"
    assert len(fake.calls) == 4
    assert "reasoning_effort" not in fake.calls[3]


def test_non_retryable_error_is_raised_at_once() -> None:
    llm, fake, sleeps = _make([_HTTPError(401)])
    with pytest.raises(_HTTPError):
        llm.chat("judge", MSGS)
    assert len(fake.calls) == 1
    assert sleeps == []


def test_all_models_failing_raises() -> None:
    llm, _, _ = _make([_HTTPError(429)] * 6)
    with pytest.raises(AllModelsFailed):
        llm.chat("attacker", MSGS)


def test_missing_key_is_rejected() -> None:
    with pytest.raises(MissingKeyError):
        build_client("groq", _settings(groq_api_key=""))


def test_placeholder_key_is_rejected() -> None:
    with pytest.raises(MissingKeyError):
        build_client("groq", _settings(groq_api_key="your_actual_groq_api_key_here"))


def test_unsupported_provider_is_rejected() -> None:
    with pytest.raises(LLMError):
        build_client("gemini", _settings())


def test_unknown_price_fails_before_any_call() -> None:
    llm, fake, _ = _make([], settings=_settings(llm_model_judge="no/such-model"))
    with pytest.raises(ValueError):
        llm.chat("judge", MSGS)
    assert fake.calls == []


def test_think_blocks_are_stripped() -> None:
    llm, _, _ = _make([_resp(text="<think>plan it</think>Hello")])
    assert llm.chat("judge", MSGS).text == "Hello"


def test_provider_block_is_logged_not_raised(tmp_path: Path) -> None:
    path = tmp_path / "llm_calls.jsonl"
    llm, _, _ = _make([_resp(text="", finish="content_filter")], log_path=path)
    result = llm.chat("target", MSGS)
    assert result.text == ""
    assert result.finish_reason == "content_filter"
    assert read_jsonl(path, LLMCallLog)[0].finish_reason == "content_filter"


def test_empty_choices_are_handled() -> None:
    empty = SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=7, completion_tokens=0))
    llm, _, _ = _make([empty])
    result = llm.chat("target", MSGS)
    assert result.text == ""
    assert result.finish_reason == "no_choices"
    assert result.call.input_tokens == 7


def test_caller_and_attempt_id_are_recorded() -> None:
    llm, _, _ = _make([_resp()])
    result = llm.chat("attacker", MSGS, caller="specialist:injection", attempt_id="a1")
    assert result.call.role == "specialist:injection"
    assert result.call.attempt_id == "a1"


@pytest.mark.parametrize(
    ("status", "expected"),
    [(408, True), (429, True), (500, True), (503, True), (400, False), (401, False), (404, False)],
)
def test_is_retryable_by_status(status: int, expected: bool) -> None:
    assert is_retryable(_HTTPError(status)) is expected


def test_role_temperature_is_sent_by_default() -> None:
    llm, fake, _ = _make([_resp()], settings=_settings(llm_temperature_attacker=0.7))
    llm.chat("attacker", MSGS)
    assert fake.calls[0]["temperature"] == 0.7


def test_explicit_temperature_overrides_role_setting() -> None:
    llm, fake, _ = _make([_resp()], settings=_settings(llm_temperature_attacker=0.7))
    llm.chat("attacker", MSGS, temperature=0.2)
    assert fake.calls[0]["temperature"] == 0.2


def test_no_temperature_sent_when_unset() -> None:
    llm, fake, _ = _make([_resp()])
    llm.chat("judge", MSGS)
    assert "temperature" not in fake.calls[0]
