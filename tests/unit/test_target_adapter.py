from pathlib import Path
from typing import Any

import pytest

from redteam.loop.runner import run_round
from redteam.loop.target_adapter import TargetAdapter
from redteam.shared.schemas import AttemptRecord, Environment, LLMCallLog
from redteam.shared.storage import read_jsonl
from tests.fakes import FakeJudge


class _FakeRealAgent:
    """Copies the parts of the real TargetAgent the adapter touches: a cumulative call_log
    that survives reset_conversation()."""

    def __init__(self, model: str = "openai/gpt-oss-120b", calls_per_message: int = 1) -> None:
        self.model = model
        self.calls_per_message = calls_per_message
        self.call_log: list[dict[str, Any]] = []
        self.attempt_id: str | None = None

    def handle_message(self, text: str) -> tuple[str, list[dict[str, Any]]]:
        for _ in range(self.calls_per_message):
            self.call_log.append(
                {
                    "model": self.model,
                    "input_tokens": 1_000_000,
                    "output_tokens": 0,
                    "cost_usd": 0.0,
                    "duration_sec": 0.5,
                }
            )
        tool_log = [
            {
                "function": "get_balance",
                "arguments": {"account_id": "ACC001"},
                "result": {"balance": 1.0},
            }
        ]
        return "reply", tool_log

    def reset_conversation(self) -> None:
        pass  # like the real agent: history is cleared, call_log is kept


class _BareAgent:
    def handle_message(self, text: str) -> tuple[str, list[dict[str, Any]]]:
        return "bare", []

    def reset_conversation(self) -> None:
        pass


def test_handle_message_passes_the_agent_output_through() -> None:
    reply, log = TargetAdapter(_FakeRealAgent()).handle_message("hi")
    assert reply == "reply"
    assert log[0]["function"] == "get_balance"


def test_calls_are_logged_with_attempt_id_and_notional_cost(tmp_path: Path) -> None:
    path = tmp_path / "llm_calls.jsonl"
    adapter = TargetAdapter(_FakeRealAgent(), llm_log_path=path)
    adapter.begin_attempt("att-1")
    adapter.handle_message("hi")
    logs = read_jsonl(path, LLMCallLog)
    assert len(logs) == 1
    assert logs[0].role == "target"
    assert logs[0].provider == "groq"
    assert logs[0].attempt_id == "att-1"
    assert logs[0].requested_model == logs[0].model == "openai/gpt-oss-120b"
    assert logs[0].cost_usd == pytest.approx(0.15)
    assert logs[0].latency_s == 0.5


def test_only_new_calls_are_logged_across_messages_and_resets(tmp_path: Path) -> None:
    path = tmp_path / "llm_calls.jsonl"
    adapter = TargetAdapter(_FakeRealAgent(calls_per_message=2), llm_log_path=path)
    adapter.handle_message("one")
    adapter.reset_conversation()
    adapter.handle_message("two")
    assert len(read_jsonl(path, LLMCallLog)) == 4


def test_calls_made_before_the_adapter_existed_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "llm_calls.jsonl"
    agent = _FakeRealAgent()
    agent.handle_message("earlier")
    adapter = TargetAdapter(agent, llm_log_path=path)
    adapter.handle_message("now")
    assert len(read_jsonl(path, LLMCallLog)) == 1


def test_logging_can_be_switched_off(tmp_path: Path) -> None:
    path = tmp_path / "llm_calls.jsonl"
    TargetAdapter(_FakeRealAgent(), llm_log_path=path, log_agent_calls=False).handle_message("hi")
    assert not path.exists()


def test_agent_without_a_call_log_is_fine(tmp_path: Path) -> None:
    path = tmp_path / "llm_calls.jsonl"
    agent = _BareAgent()
    adapter = TargetAdapter(agent, llm_log_path=path)
    adapter.begin_attempt("a1")
    assert adapter.handle_message("hi") == ("bare", [])
    assert not path.exists()
    assert not hasattr(agent, "attempt_id")


def test_attempt_id_is_forwarded_to_agents_that_accept_it() -> None:
    agent = _FakeRealAgent()
    TargetAdapter(agent).begin_attempt("a9")
    assert agent.attempt_id == "a9"


def test_unknown_model_price_fails_loudly(tmp_path: Path) -> None:
    path = tmp_path / "llm_calls.jsonl"
    adapter = TargetAdapter(_FakeRealAgent(model="no/such-model"), llm_log_path=path)
    with pytest.raises(ValueError):
        adapter.handle_message("hi")
    assert not path.exists()


def test_run_round_links_cost_lines_to_the_trial(tmp_path: Path) -> None:
    llm_path = tmp_path / "llm_calls.jsonl"
    attempt = AttemptRecord(
        specialist="injection",
        attack_category="prompt_injection",
        payload="What is my balance?",
        round=0,
    )
    trial = run_round(
        attempt,
        target=TargetAdapter(_FakeRealAgent(), llm_log_path=llm_path),
        judge=FakeJudge(),
        run_id="r1",
        environment=Environment.CLOSED,
        target_profile="banking-v1",
        trials_path=tmp_path / "trials.jsonl",
    )
    logs = read_jsonl(llm_path, LLMCallLog)
    assert [log.attempt_id for log in logs] == [attempt.attempt_id]
    assert trial.turns[1].tool_calls[0].name == "get_balance"
