"""Learnings summarizer for the adaptive orchestrator.

Compresses trial history into ≤200 words for RunSummary.learnings.
Reuses the existing RunSummary.learnings field (has 200-word validator).
"""

from __future__ import annotations

from typing import Literal

from redteam.shared.schemas import Trial, Verdict, Outcome


def _verdict_short(v: Verdict | None) -> str:
    if v is None:
        return "no_verdict"
    return v.outcome.value


def _category(t: Trial) -> str:
    return t.attempt.attack_category


def _technique(t: Trial) -> str:
    tags = t.attempt.technique_tags
    return tags[0] if tags else "unknown"


def _payload_preview(t: Trial, max_len: int = 60) -> str:
    p = t.attempt.payload.strip()
    if len(p) > max_len:
        return p[:max_len - 1] + "…"
    return p


def summarize_trials(
    trials: list[Trial],
    *,
    max_words: int = 200,
    style: Literal["compact", "detailed"] = "compact",
) -> str:
    """
    Summarize a list of trials into a compact learnings string.

    Args:
        trials: List of completed Trial records (with verdicts)
        max_words: Hard cap (RunSummary validator enforces ≤200)
        style: "compact" = one line per round; "detailed" = more context

    Returns:
        String ≤ max_words, suitable for RunSummary.learnings
    """
    if not trials:
        return "No rounds completed yet."

    lines: list[str] = []
    for i, t in enumerate(trials, 1):
        verdict = _verdict_short(t.verdict)
        cat = _category(t)
        tech = _technique(t)
        payload = _payload_preview(t)

        if style == "compact":
            line = f"R{i}: {cat}/{tech} -> {verdict} | {payload}"
        else:
            # Detailed includes tool calls if any
            tool_names = [tc.name for turn in t.turns for tc in turn.tool_calls]
            tools = f" tools:{tool_names}" if tool_names else ""
            line = f"Round {i} [{cat}/{tech}] {verdict}{tools}: {payload}"

        lines.append(line)

    summary = "; ".join(lines)

    # Enforce word limit
    words = summary.split()
    if len(words) > max_words:
        summary = " ".join(words[:max_words]) + "…"

    return summary


def update_learnings(
    current_learnings: str,
    new_trial: Trial,
    *,
    max_words: int = 200,
) -> str:
    """
    Incrementally update learnings with a new trial (for streaming use).

    Args:
        current_learnings: Existing learnings string
        new_trial: The just-completed trial
        max_words: Hard cap

    Returns:
        Updated learnings string
    """
    verdict = _verdict_short(new_trial.verdict)
    cat = _category(new_trial)
    tech = _technique(new_trial)
    payload = _payload_preview(new_trial)

    new_entry = f"{cat}/{tech}->{verdict}: {payload}"

    if not current_learnings:
        return new_entry

    combined = current_learnings + "; " + new_entry
    words = combined.split()
    if len(words) > max_words:
        # Keep most recent entries, drop oldest
        combined = " ".join(words[-max_words:])

    return combined


def extract_patterns(trials: list[Trial]) -> dict[str, list[str]]:
    """
    Extract observed patterns for potential future use (not part of learnings string).

    Returns:
        Dict with keys: successful_techniques, failed_techniques, refusal_patterns, tool_patterns
    """
    successful = []
    failed = []
    refusals = []
    tools = []

    for t in trials:
        if t.verdict is None:
            continue
        tech = _technique(t)
        if t.verdict.outcome == Outcome.ATTACK_SUCCEEDED:
            successful.append(tech)
        else:
            failed.append(tech)

        # Collect refusal phrases from target replies
        for turn in t.turns:
            if turn.speaker.value == "target":
                content = turn.content.lower()
                if any(w in content for w in ["cannot", "unable", "sorry", "blocked", "refuse", "not allowed"]):
                    # Extract sentence around refusal
                    for sent in content.split("."):
                        if any(w in sent for w in ["cannot", "unable", "sorry", "blocked", "refuse", "not allowed"]):
                            refusals.append(sent.strip()[:100])
                            break

        # Collect tool call patterns
        for turn in t.turns:
            for tc in turn.tool_calls:
                tools.append(f"{tc.name}({list(tc.arguments.keys())})")

    return {
        "successful_techniques": list(dict.fromkeys(successful)),
        "failed_techniques": list(dict.fromkeys(failed)),
        "refusal_patterns": list(dict.fromkeys(refusals))[:5],
        "tool_patterns": list(dict.fromkeys(tools))[:10],
    }