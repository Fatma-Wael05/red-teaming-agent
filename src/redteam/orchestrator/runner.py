"""Main multi-round adaptive runner.

Orchestrates: recon → loop(rounds) → manifest.
Wires: selector → specialist → run_round → blackboard update.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from redteam.loop.runner import run_round, TargetPort, JudgePort
from redteam.shared.llm import LLMClient
from redteam.shared.schemas import (
    RunSummary,
    RunManifest,
    Environment,
    Trial,
    Verdict,
    Outcome,
    Condition,
)
from redteam.shared.settings import get_settings
from redteam.shared.storage import run_dir, append_jsonl, write_manifest
from redteam.attacker.injection import InjectionSpecialist
from redteam.attacker.tool_hijack import ToolHijackSpecialist

from redteam.orchestrator.selector import select_specialist, log_selection
from redteam.orchestrator.learnings import summarize_trials, update_learnings
from redteam.orchestrator.recon import ReconModule, save_recon_report


SPECIALIST_MAP = {
    "injection": InjectionSpecialist,
    "tool_hijack": ToolHijackSpecialist,
}


def _estimate_trial_cost(trial: Trial) -> float:
    """Estimate cost of a trial from its turns (placeholder - real cost from llm_calls.jsonl)."""
    # In practice, cost is tracked via LLMCallLog. This is a fallback.
    return 0.0


def _update_success_probability(
    current: dict[str, float],
    trial: Trial,
) -> dict[str, float]:
    """Update category success probability with exponential moving average."""
    if trial.verdict is None:
        return current

    cat = trial.attempt.attack_category
    success = 1.0 if trial.verdict.outcome == Outcome.ATTACK_SUCCEEDED else 0.0
    alpha = 0.3  # smoothing factor

    old = current.get(cat, 0.5)
    current[cat] = alpha * success + (1 - alpha) * old
    return current


from typing import Protocol

class ChatLike(Protocol):
    """Protocol for LLM client - matches what specialists need."""
    def chat(
        self,
        role: str,
        messages: list[dict[str, Any]],
        *,
        caller: str | None = None,
        max_tokens: int | None = None,
    ) -> Any: ...


def run_adaptive(
    *,
    target: TargetPort,
    judge: JudgePort,
    run_id: str,
    environment: Environment = Environment.CLOSED,
    target_profile: str = "banking",
    max_rounds: int = 10,
    budget_usd: float = 1.0,
    selection_policy: str = "weighted",
    data_root: Path = Path("data"),
    provider: str = "groq",
    model: str | None = None,
    llm: ChatLike | None = None,  # Optional: inject fake LLM for testing
) -> RunManifest:
    """
    Run the adaptive multi-round red-teaming loop.

    Args:
        target: TargetPort implementation (TargetAdapter or FakeTarget)
        judge: JudgePort implementation
        run_id: Unique identifier for this run
        environment: CLOSED, OPEN, or STAGE0
        target_profile: Description of target (for manifest)
        max_rounds: Maximum rounds to execute
        budget_usd: Notional budget limit
        selection_policy: "round_robin" or "weighted"
        data_root: Root directory for run data
        provider: LLM provider for attacker (default: groq)
        model: Specific model override for attacker
        llm: Optional LLM client (ChatLike). If None, creates LLMClient from settings.

    Returns:
        Final RunManifest with complete run provenance
    """
    # Paths for this run
    folder = run_dir(data_root, run_id)
    trials_path = folder / "trials.jsonl"
    llm_log_path = folder / "llm_calls.jsonl"
    manifest_path = folder / "manifest.json"
    recon_path = folder / "recon_report.json"
    selections_path = folder / "selections.jsonl"

    # Get settings for manifest (always needed)
    settings = get_settings()

    # 1. Initialize LLM client for attacker
    if llm is None:
        llm = LLMClient(settings, llm_log_path)

    # 2. Run reconnaissance
    recon = ReconModule(target, test_canary=True)
    recon_report = recon.run()
    save_recon_report(recon_report, str(recon_path))

    # 3. Initialize RunSummary (blackboard)
    summary = RunSummary(
        rounds_used=0,
        budget_remaining=budget_usd,
        learnings="",
        success_probability={},
    )

    # 4. Initialize RunManifest
    manifest = RunManifest(
        run_id=run_id,
        environment=environment,
        condition=Condition.ADAPTIVE,
        target_profile=target_profile,
        provider=provider,
        model=model or settings.llm_model_attacker or settings.llm_model,
        temperature=settings.llm_temperature_attacker,
        max_attempts=max_rounds,
        budget_usd=budget_usd,
    )
    write_manifest(manifest_path, manifest)

    # 5. Initialize specialists
    specialists = {
        name: cls(llm)
        for name, cls in SPECIALIST_MAP.items()
    }
    available_specialists = list(specialists.keys())

    trials: list[Trial] = []
    used_payloads: set[str] = set()

    # 6. Main loop
    for round_num in range(max_rounds):
        if summary.budget_remaining <= 0:
            print(f"Budget exhausted at round {round_num}")
            break

        # Select specialist
        selected_name, reason = select_specialist(
            summary,
            available_specialists,
            policy=selection_policy,
            round_num=round_num,
        )
        log_selection(run_id, round_num, selected_name, reason, str(selections_path))
        print(f"Round {round_num}: selected {selected_name} ({reason})")

        # Generate attempt
        specialist = specialists[selected_name]
        attempts = specialist.generate(
            1,
            round_num=round_num,
            learnings=summary.learnings,
            avoid=list(used_payloads),
        )

        if not attempts:
            print(f"  No valid attempts generated, skipping round")
            continue

        attempt = attempts[0]
        used_payloads.add(attempt.payload.strip().lower())

        # Run the round
        trial = run_round(
            attempt,
            target=target,
            judge=judge,
            run_id=run_id,
            environment=environment,
            target_profile=target_profile,
            trials_path=trials_path,
        )
        trials.append(trial)

        # Update blackboard
        summary = RunSummary(
            rounds_used=round_num + 1,
            budget_remaining=max(0.0, summary.budget_remaining - _estimate_trial_cost(trial)),
            learnings=update_learnings(summary.learnings, trial),
            success_probability=_update_success_probability(
                summary.success_probability, trial
            ),
        )

        # Update manifest
        manifest = RunManifest(
            run_id=run_id,
            environment=environment,
            condition=Condition.ADAPTIVE,
            target_profile=target_profile,
            provider=provider,
            model=model or settings.llm_model_attacker or settings.llm_model,
            temperature=settings.llm_temperature_attacker,
            max_attempts=max_rounds,
            budget_usd=budget_usd,
            total_cost_usd=budget_usd - summary.budget_remaining,
        )
        write_manifest(manifest_path, manifest)

        # Print round result
        verdict = trial.verdict
        if verdict:
            print(f"  {verdict.outcome.value} ({verdict.category}/{trial.attempt.technique_tags})")
        else:
            print(f"  No verdict")

        # Early stop if attack succeeded (optional)
        if verdict and verdict.outcome == Outcome.ATTACK_SUCCEEDED:
            print(f"  Attack succeeded! Continuing to explore other categories...")

    # Final manifest update
    manifest = RunManifest(
        run_id=run_id,
        environment=environment,
        condition=Condition.ADAPTIVE,
        target_profile=target_profile,
        provider=provider,
        model=model or settings.llm_model_attacker or settings.llm_model,
        temperature=settings.llm_temperature_attacker,
        max_attempts=max_rounds,
        budget_usd=budget_usd,
        total_cost_usd=budget_usd - summary.budget_remaining,
        finished_at=None,  # Will be set by model default
    )
    write_manifest(manifest_path, manifest)

    print(f"\nRun {run_id} complete: {summary.rounds_used} rounds, ${summary.budget_remaining:.4f} budget remaining")
    print(f"Saved to {folder}")
    return manifest


def run_static_baseline(
    *,
    target: TargetPort,
    judge: JudgePort,
    run_id: str,
    attack_list: list[str],
    environment: Environment = Environment.CLOSED,
    target_profile: str = "banking",
    data_root: Path = Path("data"),
    provider: str = "groq",
) -> RunManifest:
    """
    Run static baseline: fixed attack list, no adaptation, no recon.
    Used for comparison with adaptive condition.
    """
    from redteam.shared.schemas import AttemptRecord

    folder = run_dir(data_root, run_id)
    trials_path = folder / "trials.jsonl"
    llm_log_path = folder / "llm_calls.jsonl"
    manifest_path = folder / "manifest.json"

    settings = get_settings()
    llm = LLMClient(settings, llm_log_path)

    # No recon for baseline
    manifest = RunManifest(
        run_id=run_id,
        environment=environment,
        condition=Condition.STATIC_BASELINE,
        target_profile=target_profile,
        provider=provider,
        model=settings.llm_model_attacker or settings.llm_model,
        temperature=settings.llm_temperature_attacker,
        max_attempts=len(attack_list),
        budget_usd=0.0,
        frozen_list_sha256=_sha256_of_list(attack_list),
    )
    write_manifest(manifest_path, manifest)

    for i, payload in enumerate(attack_list):
        attempt = AttemptRecord(
            specialist="baseline",
            attack_category="static",
            payload=payload,
            round=i,
        )
        trial = run_round(
            attempt,
            target=target,
            judge=judge,
            run_id=run_id,
            environment=environment,
            target_profile=target_profile,
            trials_path=trials_path,
        )

    manifest = RunManifest(
        run_id=run_id,
        environment=environment,
        condition=Condition.STATIC_BASELINE,
        target_profile=target_profile,
        provider=provider,
        model=settings.llm_model_attacker or settings.llm_model,
        temperature=settings.llm_temperature_attacker,
        max_attempts=len(attack_list),
        budget_usd=0.0,
        frozen_list_sha256=_sha256_of_list(attack_list),
    )
    write_manifest(manifest_path, manifest)
    return manifest


def _sha256_of_list(items: list[str]) -> str:
    import hashlib
    content = "\n".join(items).encode("utf-8")
    return hashlib.sha256(content).hexdigest()