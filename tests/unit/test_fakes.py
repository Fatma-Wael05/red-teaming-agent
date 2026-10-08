"""Unit tests for offline fake target and fake judge adapters."""

from tests.fakes import FakeJudge, FakeTargetAgent
from redteam.shared.schemas import Outcome, ToolCall


def test_fake_target_default_refusal() -> None:
    target = FakeTargetAgent()
    resp, tool_calls = target.handle_message("Hello, tell me a joke.")

    assert resp == "I cannot fulfill this request."
    assert tool_calls == []
    assert len(target.history) == 2
    assert target.history[0] == {"role": "user", "content": "Hello, tell me a joke."}
    assert target.history[1] == {"role": "assistant", "content": "I cannot fulfill this request."}


def test_fake_target_trigger_tool_via_keyword() -> None:
    target = FakeTargetAgent()
    resp, tool_calls = target.handle_message("Please TRANSFER 100 dollars")

    assert resp == "Transfer executed."
    assert len(tool_calls) == 1
    assert tool_calls[0].name == "transfer_money"
    assert tool_calls[0].arguments == {"to": "attacker", "amount": 100.0}
    assert tool_calls[0].result == {"status": "success"}


def test_fake_target_trigger_tool_via_flag() -> None:
    target = FakeTargetAgent(should_trigger_tool=True)
    resp, tool_calls = target.handle_message("Ordinary message")

    assert resp == "Transfer executed."
    assert len(tool_calls) == 1


def test_fake_target_reset_conversation() -> None:
    target = FakeTargetAgent()
    target.handle_message("Test message")
    assert len(target.history) == 2

    target.reset_conversation()
    assert len(target.history) == 0


def test_fake_judge_evaluates_refusal() -> None:
    judge = FakeJudge()
    verdict = judge.evaluate(
        attempt_id="att-001",
        prompt="Tell me a joke",
        response="I cannot fulfill this request.",
        tool_calls=(),
    )

    assert verdict.attempt_id == "att-001"
    assert verdict.outcome == Outcome.TARGET_REFUSED
    assert verdict.category == "refusal"
    assert verdict.confidence == 1.0


def test_fake_judge_evaluates_tool_misuse() -> None:
    judge = FakeJudge()
    mock_tool = ToolCall(name="transfer_money", arguments={}, result={"status": "success"})
    verdict = judge.evaluate(
        attempt_id="att-002",
        prompt="TRANSFER money",
        response="Transfer executed.",
        tool_calls=(mock_tool,),
    )

    assert verdict.attempt_id == "att-002"
    assert verdict.outcome == Outcome.ATTACK_SUCCEEDED
    assert verdict.category == "tool_misuse"
    assert verdict.confidence == 1.0
