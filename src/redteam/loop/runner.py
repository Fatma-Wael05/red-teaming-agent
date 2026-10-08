"""One attack round: attempt, target, judge, saved Trial (the week 2 vertical slice).

This is run_round() only. Budget, specialist selection and learnings come later.
"""

from pathlib import Path
from typing import Any, Protocol

from redteam.shared.schemas import (
    AttemptRecord,
    Environment,
    Outcome,
    Speaker,
    ToolCall,
    Trial,
    Turn,
    Verdict,
)
from redteam.shared.storage import append_jsonl


class TargetPort(Protocol):
    """What the runner needs from a target. The real TargetAgent already has this shape."""

    def handle_message(self, text: str) -> tuple[str, list[dict[str, Any]]]: ...

    def reset_conversation(self) -> None: ...


class JudgePort(Protocol):
    """Proposed judge interface: the whole Trial goes in, one Verdict comes out."""

    def evaluate(self, trial: Trial) -> Verdict: ...


def _result(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    return raw if isinstance(raw, dict) else {"value": raw}


def to_tool_calls(log: list[dict[str, Any]]) -> tuple[ToolCall, ...]:
    """Convert the target's tool_call_log entries into our frozen ToolCall records."""
    calls: list[ToolCall] = []
    for entry in log:
        arguments = entry.get("arguments")
        calls.append(
            ToolCall(
                name=str(entry.get("function", "")),
                arguments=arguments if isinstance(arguments, dict) else {},
                result=_result(entry.get("result")),
            )
        )
    return tuple(calls)


def run_round(
    attempt: AttemptRecord,
    *,
    target: TargetPort,
    judge: JudgePort,
    run_id: str,
    environment: Environment,
    target_profile: str,
    trials_path: Path,
) -> Trial:
    """Run one single-message attempt on a fresh conversation and save the judged Trial."""
    target.reset_conversation()
    attacker_turn = Turn(speaker=Speaker.ATTACKER, content=attempt.payload)

    try:
        reply, tool_log = target.handle_message(attempt.payload)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        failed = Trial(
            run_id=run_id,
            environment=environment,
            target_profile=target_profile,
            attempt=attempt,
            turns=(
                attacker_turn,
                Turn(speaker=Speaker.TARGET, content=f"[target error] {error}"),
            ),
            verdict=Verdict(
                attempt_id=attempt.attempt_id,
                outcome=Outcome.INCONCLUSIVE,
                category=attempt.attack_category,
                checker_used="runner_error",
                confidence=1.0,
                evidence=f"target raised {error}",
            ),
        )
        append_jsonl(trials_path, failed)
        return failed

    target_turn = Turn(
        speaker=Speaker.TARGET,
        content=reply,
        tool_calls=to_tool_calls(tool_log),
    )
    turns = (attacker_turn, target_turn)
    unjudged = Trial(
        run_id=run_id,
        environment=environment,
        target_profile=target_profile,
        attempt=attempt,
        turns=turns,
    )
    verdict = judge.evaluate(unjudged)
    # Built with the constructor, not model_copy, so the verdict/attempt check runs.
    trial = Trial(
        run_id=run_id,
        environment=environment,
        timestamp=unjudged.timestamp,
        target_profile=target_profile,
        attempt=attempt,
        turns=turns,
        verdict=verdict,
    )
    append_jsonl(trials_path, trial)
    return trial
