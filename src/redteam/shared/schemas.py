"""Frozen data contracts shared by attacker, target and judge.

Changes here require T1/A4 review. Records are immutable: attach a verdict
by copying (model_copy), never by mutating.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return uuid.uuid4().hex


class Frozen(BaseModel):
    """Immutable base that rejects unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------- enums
class Outcome(StrEnum):
    ATTACK_SUCCEEDED = "attack_succeeded"
    TARGET_REFUSED = "target_refused"
    # The model provider's own safety layer blocked the request.
    # Not the same as the target's guardrails refusing.
    PROVIDER_BLOCKED = "provider_blocked"
    INCONCLUSIVE = "inconclusive"


class Speaker(StrEnum):
    ATTACKER = "attacker"
    TARGET = "target"


class Environment(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    STAGE0 = "stage0"  # never enters metrics (rule #5)


class Condition(StrEnum):
    """Experimental condition: the one difference the research claim is about."""

    STATIC_BASELINE = "static_baseline"  # frozen list, no inner or outer loop
    ADAPTIVE = "adaptive"  # swarm with blackboard feedback loops


# ------------------------------------------------- what the attacker proposes
class AttemptRecord(Frozen):
    """Specialist output. `payload` is the attacker's opening message."""

    attempt_id: str = Field(default_factory=_new_id)
    specialist: str
    attack_category: str
    payload: str
    technique_tags: tuple[str, ...] = ()
    round: int = Field(ge=0)
    parent_id: str | None = None  # set by the compound agent when chaining


# ------------------------------------------------------ what happened (judge)
class Verdict(Frozen):
    """Produced only by the Judge (rule #3)."""

    attempt_id: str
    outcome: Outcome
    category: str
    checker_used: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str

    @property
    def success(self) -> bool:
        return self.outcome == Outcome.ATTACK_SUCCEEDED


# ------------------------------------------------------ what happened (target)
class ToolCall(Frozen):
    name: str
    arguments: dict[str, Any]


class Turn(Frozen):
    speaker: Speaker
    content: str
    tool_calls: tuple[ToolCall, ...] = ()


class Trial(Frozen):
    """One executed attempt: the proposal, the conversation, the verdict."""

    run_id: str
    environment: Environment
    timestamp: datetime = Field(default_factory=_now)
    target_profile: str
    attempt: AttemptRecord
    turns: tuple[Turn, ...] = Field(min_length=1)
    verdict: Verdict | None = None

    @model_validator(mode="after")
    def _verdict_matches_attempt(self) -> "Trial":
        if self.verdict and self.verdict.attempt_id != self.attempt.attempt_id:
            raise ValueError("verdict.attempt_id does not match attempt.attempt_id")
        return self


# ------------------------------------------------ memory carried between rounds
class RunSummary(Frozen):
    """Blackboard memory for the orchestrator (the context-engineering core)."""

    rounds_used: int = Field(ge=0)
    budget_remaining: float = Field(ge=0.0)
    learnings: str = ""
    success_probability: dict[str, float] = Field(default_factory=dict)

    @field_validator("learnings")
    @classmethod
    def _max_200_words(cls, v: str) -> str:
        if len(v.split()) > 200:
            raise ValueError("learnings must be <= 200 words")
        return v


# ------------------------------------------------------- run-level provenance
class RunManifest(Frozen):
    """Reproducibility record for one run."""

    run_id: str = Field(default_factory=_new_id)
    environment: Environment
    condition: Condition
    started_at: datetime = Field(default_factory=_now)
    finished_at: datetime | None = None
    target_profile: str
    provider: str
    model: str
    temperature: float | None = None
    seed: int | None = None
    # Equal budget across conditions is what makes the comparison fair.
    max_attempts: int | None = Field(default=None, ge=1)
    budget_usd: float | None = Field(default=None, ge=0.0)
    # SHA-256 of the frozen baseline list; proves it wasn't edited after freeze.
    frozen_list_sha256: str | None = None
    total_cost_usd: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="after")
    def _baseline_needs_hash(self) -> "RunManifest":
        if self.condition == Condition.STATIC_BASELINE and not self.frozen_list_sha256:
            raise ValueError("static_baseline runs must record frozen_list_sha256")
        return self


# --------------------------------------------------------------- cost logging
class LLMCallLog(Frozen):
    call_id: str = Field(default_factory=_new_id)
    timestamp: datetime = Field(default_factory=_now)
    role: str  # e.g. "specialist:injection", "judge", "target"
    provider: str
    requested_model: str
    model: str  # model that actually answered (may differ on fallback)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0.0)
    latency_s: float = Field(ge=0.0)
    attempt_id: str | None = None
    finish_reason: str | None = None  # e.g. stop, length, content_filter
