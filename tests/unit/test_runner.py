from pathlib import Path
from typing import Any

from redteam.loop.runner import run_round, to_tool_calls
from redteam.shared.schemas import AttemptRecord, Environment, Outcome, Trial
from redteam.shared.storage import read_jsonl
from tests.fakes import FakeJudge, FakeTarget


def _attempt(payload: str = "Tell me a joke.") -> AttemptRecord:
    return AttemptRecord(
        specialist="injection",
        attack_category="prompt_injection",
        payload=payload,
        round=0,
    )


def _run(attempt: AttemptRecord, target: Any, path: Path) -> Trial:
    return run_round(
        attempt,
        target=target,
        judge=FakeJudge(),
        run_id="r1",
        environment=Environment.CLOSED,
        target_profile="banking-v1",
        trials_path=path,
    )


class _CrashingTarget:
    def handle_message(self, text: str) -> tuple[str, list[dict[str, Any]]]:
        raise TypeError("'>' not supported between instances of 'str' and 'float'")

    def reset_conversation(self) -> None:
        pass


def test_refusal_round(tmp_path: Path) -> None:
    attempt = _attempt()
    trial = _run(attempt, FakeTarget(), tmp_path / "trials.jsonl")
    assert trial.verdict is not None
    assert trial.verdict.outcome == Outcome.TARGET_REFUSED
    assert trial.verdict.attempt_id == attempt.attempt_id
    assert [t.content for t in trial.turns] == [attempt.payload, "I cannot fulfill this request."]


def test_successful_tool_call_round(tmp_path: Path) -> None:
    trial = _run(_attempt("Please TRANSFER 100"), FakeTarget(), tmp_path / "trials.jsonl")
    assert trial.verdict is not None
    assert trial.verdict.outcome == Outcome.ATTACK_SUCCEEDED
    call = trial.turns[1].tool_calls[0]
    assert call.name == "transfer_money"
    assert call.result is not None
    assert call.result["status"] == "success"


def test_blocked_tool_call_round(tmp_path: Path) -> None:
    trial = _run(_attempt("OVERLIMIT TRANSFER"), FakeTarget(), tmp_path / "trials.jsonl")
    assert trial.verdict is not None
    assert trial.verdict.outcome == Outcome.TARGET_REFUSED
    assert trial.turns[1].tool_calls[0].result == {
        "error": "Transfer blocked: over the limit",
        "blocked": True,
    }


def test_trial_is_saved_and_reads_back_equal(tmp_path: Path) -> None:
    path = tmp_path / "trials.jsonl"
    trial = _run(_attempt(), FakeTarget(), path)
    assert read_jsonl(path, Trial) == [trial]


def test_two_rounds_append_two_lines(tmp_path: Path) -> None:
    path = tmp_path / "trials.jsonl"
    target = FakeTarget()
    _run(_attempt(), target, path)
    _run(_attempt("Please TRANSFER 100"), target, path)
    assert len(read_jsonl(path, Trial)) == 2


def test_each_round_starts_a_fresh_conversation(tmp_path: Path) -> None:
    target = FakeTarget()
    _run(_attempt(), target, tmp_path / "trials.jsonl")
    _run(_attempt(), target, tmp_path / "trials.jsonl")
    assert target.resets == 2
    assert len(target.history) == 2


def test_target_crash_is_recorded_not_raised(tmp_path: Path) -> None:
    path = tmp_path / "trials.jsonl"
    trial = _run(_attempt(), _CrashingTarget(), path)
    assert trial.verdict is not None
    assert trial.verdict.outcome == Outcome.INCONCLUSIVE
    assert trial.verdict.checker_used == "runner_error"
    assert "TypeError" in trial.verdict.evidence
    assert len(read_jsonl(path, Trial)) == 1


def test_to_tool_calls_tolerates_odd_log_entries() -> None:
    calls = to_tool_calls([{"function": "x", "result": "plain text"}, {"function": "y"}])
    assert calls[0].name == "x"
    assert calls[0].arguments == {}
    assert calls[0].result == {"value": "plain text"}
    assert calls[1].result is None
