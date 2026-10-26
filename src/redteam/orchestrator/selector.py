"""Specialist selection policy for the adaptive orchestrator.

Simple, configurable, logged selection. Reuses RunSummary.success_probability.
"""

from __future__ import annotations

import json
from typing import Literal

from redteam.shared.schemas import RunSummary


SelectionPolicy = Literal["round_robin", "weighted"]


def select_specialist(
    summary: RunSummary,
    available: list[str],
    *,
    policy: SelectionPolicy = "weighted",
    round_num: int = 0,
) -> tuple[str, str]:
    """
    Choose the next specialist to run.

    Args:
        summary: Current RunSummary with success_probability per category
        available: List of specialist names (e.g., ["injection", "tool_hijack"])
        policy: "round_robin" or "weighted" by success_probability
        round_num: Current round number (for round-robin)

    Returns:
        (specialist_name, reason_string)
    """
    if not available:
        raise ValueError("no specialists available")

    if policy == "round_robin":
        idx = round_num % len(available)
        chosen = available[idx]
        reason = f"round_robin: index {idx} of {len(available)}"
        return chosen, reason

    # Weighted by success_probability (default)
    probs = summary.success_probability or {}
    # Default probability for categories not yet seen
    default_prob = 1.0 / len(available) if available else 0.5

    scored = []
    for spec in available:
        prob = probs.get(spec, default_prob)
        scored.append((spec, prob))

    # Sort by probability descending, break ties by name for determinism
    scored.sort(key=lambda x: (-x[1], x[0]))
    chosen = scored[0][0]
    reason = "weighted: " + json.dumps({s: p for s, p in scored}, separators=(",", ":"))

    return chosen, reason


def log_selection(
    run_id: str,
    round_num: int,
    selected: str,
    reason: str,
    log_path: str | None = None,
) -> None:
    """
    Log the specialist selection decision.

    Args:
        run_id: Current run identifier
        round_num: Round number (0-indexed)
        selected: Specialist name that was chosen
        reason: Human-readable reason from select_specialist
        log_path: Optional path to append JSONL log (defaults to data/runs/<run_id>/selections.jsonl)
    """
    if log_path is None:
        from pathlib import Path
        from redteam.shared.storage import run_dir
        log_path = str(run_dir(Path("data"), run_id) / "selections.jsonl")

    from datetime import UTC, datetime
    entry = {
        "run_id": run_id,
        "round": round_num,
        "selected": selected,
        "reason": reason,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    from pathlib import Path
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    with Path(log_path).open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")