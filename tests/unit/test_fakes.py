from redteam.shared.schemas import (
    AttemptRecord,
    Environment,
    Outcome,
    Speaker,
    ToolCall,
    Trial,
    Turn,
)
from tests.fakes import FakeJudge, FakeTarget


def _trial(*tool_calls: ToolCall) -> Trial:
    attempt = AttemptRecord(specialist="s", attack_category="c", payload="p", round=0)
    return Trial(
        run_id="r",
        environment=Environment.CLOSED,
        target_profile="t",
        attempt=attempt,
        turns=(
            Turn(speaker=Speaker.ATTACKER, content="p"),
            Turn(speaker=Speaker.TARGET, content="x", tool_calls=tuple(tool_calls)),
        ),
    )


def test_fake_target_refuses_by_default() -> None:
    reply, log = FakeTarget().handle_message("Tell me a joke.")
    assert reply == "I cannot fulfill this request."
    assert log == []


def test_fake_target_logs_tool_calls_in_the_real_target_format() -> None:
    _, log = FakeTarget().handle_message("Please TRANSFER 100 dollars")
    assert set(log[0]) == {"function", "arguments", "result"}
    assert log[0]["function"] == "transfer_money"
    assert log[0]["result"]["status"] == "success"


def test_fake_target_overlimit_transfer_is_blocked() -> None:
    _, log = FakeTarget().handle_message("OVERLIMIT TRANSFER")
    assert log[0]["result"]["blocked"] is True


def test_fake_target_reset_clears_history_and_counts() -> None:
    target = FakeTarget()
    target.handle_message("hello")
    assert len(target.history) == 2
    target.reset_conversation()
    assert target.history == []
    assert target.resets == 1


def test_fake_judge_flags_successful_tool_call() -> None:
    call = ToolCall(name="transfer_money", arguments={}, result={"status": "success"})
    assert FakeJudge().evaluate(_trial(call)).outcome == Outcome.ATTACK_SUCCEEDED


def test_fake_judge_refuses_when_no_tool_call() -> None:
    assert FakeJudge().evaluate(_trial()).outcome == Outcome.TARGET_REFUSED


def test_fake_judge_treats_blocked_tool_call_as_refusal() -> None:
    call = ToolCall(name="transfer_money", arguments={}, result={"error": "x", "blocked": True})
    assert FakeJudge().evaluate(_trial(call)).outcome == Outcome.TARGET_REFUSED
