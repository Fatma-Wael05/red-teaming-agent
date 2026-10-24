"""One attack round: attempt, target, judge, saved Trial (the week 2 vertical slice).

run_round() runs one attempt. run_static_baseline() replays a specialist's whole
frozen refdb list through run_round() under Condition.STATIC_BASELINE — no LLM
call for the attacker, no inner/outer loop. Budget, specialist selection and
learnings for Condition.ADAPTIVE come later.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from redteam.attacker.specialist import Specialist
from redteam.shared.schemas import (
    AttemptRecord,
    Condition,
    Environment,
    LLMCallLog,
    Outcome,
    RunManifest,
    Speaker,
    ToolCall,
    Trial,
    Turn,
    Verdict,
)
from redteam.shared.storage import append_jsonl, read_jsonl, write_manifest


class TargetPort(Protocol):
    """What the runner needs from a target."""

    def handle_message(self, text: str) -> tuple[str, list[dict[str, Any]]]: ...

    def reset_conversation(self) -> None: ...


@runtime_checkable
class AttemptAware(Protocol):
    """Optional: targets that want to know which attempt is running (for cost tracing)."""

    def begin_attempt(self, attempt_id: str) -> None: ...


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


def _guardrails(target: object) -> tuple[str, ...]:
    """Guardrails the target says fired on its last message (empty if it does not report)."""
    reported = getattr(target, "last_guardrails", None) or ()
    return tuple(str(name) for name in reported)


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
    if isinstance(target, AttemptAware):
        target.begin_attempt(attempt.attempt_id)
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
        guardrails=_guardrails(target),
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


def run_static_baseline(
    specialist_cls: type[Specialist],
    *,
    target: TargetPort,
    judge: JudgePort,
    run_id: str,
    environment: Environment,
    target_profile: str,
    provider: str,
    model: str,
    trials_path: Path,
    manifest_path: Path,
    temperature: float | None = None,
    seed: int | None = None,
    llm_log_path: Path | None = None,
) -> RunManifest:
    """Condition.STATIC_BASELINE for one specialist: replay its whole frozen refdb
    list through run_round(), one attempt per call, with no LLM call for the
    attacker and no inner/outer loop.

    Attempts and the manifest's frozen_list_sha256 come from ONE file read
    (`specialist_cls.load_static_with_hash`), so the hash recorded in the
    manifest is guaranteed to match what was actually run, even if someone
    edits the refdb file a moment later.

    The manifest is written twice: once before the loop starts (so a crash
    mid-run still leaves a manifest recording what was *attempted*, with
    finished_at=None), and once after, with finished_at set. Trial records are
    appended by run_round() as each attempt finishes, not batched at the end.

    `llm_log_path`, if given, is the llm_calls.jsonl this run's LLMCallLog rows
    were written to — by the judge's own LLMClient (role="judge") and, for a
    real TargetAgent, by TargetAdapter forwarding the agent's call_log (role=
    "target"), both pointed at the SAME file for this to work. attempt_id on
    each row is what links it to this run: attempt ids are uuids minted per
    AttemptRecord, so they're unique across the whole project, which means
    filtering by "attempt_id in this run's attempts" is correct even if the
    file accumulates rows from other runs too (no run_id field needed on
    LLMCallLog itself). If this is omitted, total_cost_usd stays 0.0 — the
    manifest still records what ran, just not what it cost.
    """
    attempts, digest = specialist_cls.load_static_with_hash()
    manifest = RunManifest(
        run_id=run_id,
        environment=environment,
        condition=Condition.STATIC_BASELINE,
        target_profile=target_profile,
        provider=provider,
        model=model,
        temperature=temperature,
        seed=seed,
        max_attempts=len(attempts),
        frozen_list_sha256=digest,
    )
    write_manifest(manifest_path, manifest)

    for attempt in attempts:
        run_round(
            attempt,
            target=target,
            judge=judge,
            run_id=run_id,
            environment=environment,
            target_profile=target_profile,
            trials_path=trials_path,
        )

    # RunManifest is frozen: model_copy, not mutation, per this module's own rule.
    update: dict[str, Any] = {"finished_at": datetime.now(UTC)}
    if llm_log_path is not None and llm_log_path.exists():
        attempt_ids = {attempt.attempt_id for attempt in attempts}
        logs = read_jsonl(llm_log_path, LLMCallLog)
        update["total_cost_usd"] = sum(
            log.cost_usd for log in logs if log.attempt_id in attempt_ids
        )
    manifest = manifest.model_copy(update=update)
    write_manifest(manifest_path, manifest)
    return manifest
