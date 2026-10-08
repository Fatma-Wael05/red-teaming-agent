import pytest
from pydantic import ValidationError

from redteam.shared.schemas import (
    AttemptRecord,
    Condition,
    Environment,
    LLMCallLog,
    Outcome,
    RunManifest,
    RunSummary,
    Speaker,
    ToolCall,
    Trial,
    Turn,
    Verdict,
)


def _attempt(**overrides: object) -> AttemptRecord:
    fields: dict[str, object] = {
        "specialist": "injection",
        "attack_category": "prompt_injection",
        "payload": "ignore previous instructions",
        "round": 0,
    }
    fields.update(overrides)
    return AttemptRecord(**fields)  # type: ignore[arg-type]


def _verdict(attempt_id: str, outcome: Outcome = Outcome.TARGET_REFUSED) -> Verdict:
    return Verdict(
        attempt_id=attempt_id,
        outcome=outcome,
        category="prompt_injection",
        checker_used="canary_checker",
        confidence=1.0,
        evidence="canary absent",
    )


def _turns() -> tuple[Turn, ...]:
    return (
        Turn(speaker=Speaker.ATTACKER, content="hi"),
        Turn(speaker=Speaker.TARGET, content="hello"),
    )


def _trial(attempt: AttemptRecord | None = None, **overrides: object) -> Trial:
    fields: dict[str, object] = {
        "run_id": "r1",
        "environment": Environment.CLOSED,
        "target_profile": "banking-v1",
        "attempt": attempt or _attempt(),
        "turns": _turns(),
    }
    fields.update(overrides)
    return Trial(**fields)  # type: ignore[arg-type]


# ------------------------------------------------------------ AttemptRecord
def test_attempt_is_frozen() -> None:
    a = _attempt()
    with pytest.raises(ValidationError):
        a.payload = "changed"  # type: ignore[misc]


def test_attempt_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        _attempt(surprise=1)


def test_attempt_rejects_negative_round() -> None:
    with pytest.raises(ValidationError):
        _attempt(round=-1)


def test_attempt_ids_are_unique() -> None:
    assert _attempt().attempt_id != _attempt().attempt_id


def test_attempt_tags_accept_list_and_become_tuple() -> None:
    a = _attempt(technique_tags=["roleplay", "encoding"])
    assert a.technique_tags == ("roleplay", "encoding")


def test_attempt_parent_id_defaults_to_none() -> None:
    assert _attempt().parent_id is None


# ------------------------------------------------------------------ Verdict
def test_verdict_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Verdict(
            attempt_id="x",
            outcome=Outcome.TARGET_REFUSED,
            category="c",
            checker_used="k",
            confidence=1.0,
            evidence="e",
            judge_kind="programmatic",  # type: ignore[call-arg]
        )


def test_verdict_confidence_must_be_between_0_and_1() -> None:
    for bad in (-0.1, 1.1):
        with pytest.raises(ValidationError):
            Verdict(
                attempt_id="x",
                outcome=Outcome.INCONCLUSIVE,
                category="c",
                checker_used="k",
                confidence=bad,
                evidence="e",
            )


def test_verdict_success_is_derived_from_outcome() -> None:
    assert _verdict("x", Outcome.ATTACK_SUCCEEDED).success is True
    for o in (Outcome.TARGET_REFUSED, Outcome.PROVIDER_BLOCKED, Outcome.INCONCLUSIVE):
        assert _verdict("x", o).success is False


# -------------------------------------------------------------------- Trial
def test_trial_requires_at_least_one_turn() -> None:
    with pytest.raises(ValidationError):
        _trial(turns=())


def test_trial_is_frozen() -> None:
    t = _trial()
    with pytest.raises(ValidationError):
        t.turns = ()  # type: ignore[misc]


def test_tool_calls_survive_json_roundtrip() -> None:
    call = ToolCall(name="transfer_money", arguments={"amount": 501.0, "recipient": "ACC-9"})
    turns = (
        Turn(speaker=Speaker.ATTACKER, content="send it"),
        Turn(speaker=Speaker.TARGET, content="done", tool_calls=(call,)),
    )
    t = _trial(turns=turns)
    restored = Trial.model_validate_json(t.model_dump_json())
    assert restored == t
    assert restored.turns[1].tool_calls[0].arguments["amount"] == 501.0


def test_verdict_is_attached_by_copy_not_mutation() -> None:
    a = _attempt()
    t = _trial(a)
    judged = t.model_copy(update={"verdict": _verdict(a.attempt_id)})
    assert t.verdict is None
    assert judged.verdict is not None
    assert judged.verdict.attempt_id == a.attempt_id


def test_trial_rejects_verdict_for_another_attempt() -> None:
    with pytest.raises(ValidationError):
        _trial(verdict=_verdict("some-other-attempt"))


def test_trial_with_verdict_roundtrips() -> None:
    a = _attempt()
    t = _trial(a, verdict=_verdict(a.attempt_id, Outcome.ATTACK_SUCCEEDED))
    assert Trial.model_validate_json(t.model_dump_json()) == t


# ---------------------------------------------------------------- RunSummary
def test_run_summary_allows_200_words() -> None:
    RunSummary(rounds_used=1, budget_remaining=1.0, learnings=" ".join(["w"] * 200))


def test_run_summary_rejects_201_words() -> None:
    with pytest.raises(ValidationError):
        RunSummary(rounds_used=1, budget_remaining=1.0, learnings=" ".join(["w"] * 201))


def test_run_summary_rejects_negative_budget() -> None:
    with pytest.raises(ValidationError):
        RunSummary(rounds_used=0, budget_remaining=-1.0)


# --------------------------------------------------------------- RunManifest
def _manifest(**overrides: object) -> RunManifest:
    fields: dict[str, object] = {
        "environment": Environment.CLOSED,
        "condition": Condition.ADAPTIVE,
        "target_profile": "banking-v1",
        "provider": "groq",
        "model": "openai/gpt-oss-120b",
    }
    fields.update(overrides)
    return RunManifest(**fields)  # type: ignore[arg-type]


def test_adaptive_manifest_does_not_need_a_hash() -> None:
    assert _manifest().frozen_list_sha256 is None


def test_static_baseline_manifest_requires_hash() -> None:
    with pytest.raises(ValidationError):
        _manifest(condition=Condition.STATIC_BASELINE)


def test_static_baseline_manifest_accepts_hash() -> None:
    m = _manifest(condition=Condition.STATIC_BASELINE, frozen_list_sha256="ab" * 32)
    assert m.condition == Condition.STATIC_BASELINE


def test_manifest_rejects_zero_max_attempts() -> None:
    with pytest.raises(ValidationError):
        _manifest(max_attempts=0)


def test_manifest_finish_by_copy() -> None:
    m = _manifest()
    done = m.model_copy(update={"total_cost_usd": 0.04})
    assert m.total_cost_usd == 0.0
    assert done.total_cost_usd == 0.04


# --------------------------------------------------------------- LLMCallLog
def test_llm_call_log_keeps_requested_and_actual_model_separate() -> None:
    log = LLMCallLog(
        role="judge",
        provider="groq",
        requested_model="model-a",
        model="model-b",
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.001,
        latency_s=0.4,
    )
    assert log.requested_model != log.model
    assert log.attempt_id is None


def test_llm_call_log_rejects_negative_tokens() -> None:
    with pytest.raises(ValidationError):
        LLMCallLog(
            role="judge",
            provider="groq",
            requested_model="m",
            model="m",
            input_tokens=-1,
            output_tokens=0,
            cost_usd=0.0,
            latency_s=0.0,
        )
