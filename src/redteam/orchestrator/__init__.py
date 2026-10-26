"""Orchestrator package: multi-round loop, specialist selection, learnings, recon."""

from redteam.orchestrator.selector import select_specialist, log_selection
from redteam.orchestrator.learnings import summarize_trials, update_learnings, extract_patterns
from redteam.orchestrator.recon import ReconModule, ReconReport, ToolInfo, save_recon_report
from redteam.orchestrator.runner import run_adaptive, run_static_baseline

__all__ = [
    "select_specialist",
    "log_selection",
    "summarize_trials",
    "update_learnings",
    "extract_patterns",
    "ReconModule",
    "ReconReport",
    "ToolInfo",
    "save_recon_report",
    "run_adaptive",
    "run_static_baseline",
]