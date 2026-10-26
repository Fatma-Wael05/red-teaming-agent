# Autonomous Adaptive Red-Teaming Agent — Project Documentation

> **Owner:** George | **Main Ownership:** Adaptive Orchestration & Recon  
> **Project:** Graduation Project — "An Autonomous Adaptive Red-Teaming Agent for Agentic AI Systems"  
> **Last Updated:** 2026-10-24  
> **Purpose:** Complete project reference — if this chat is deleted, you can resume from this document.

---

## 1. Project Overview

### Goal
Build an **autonomous adaptive red-teaming agent** that discovers application-layer vulnerabilities in AI agents (system prompt weaknesses, guardrail bypasses, tool-call hijacking) through adaptive, reasoning-based attack refinement — improving on static checklist-based approaches.

### Key Concept (from Proposal)
```
┌──────────────────────┐
│ Attacker Agent       │
│ (adaptive, reasons  │
│ over prior attempts) │
└──────────┬────────────┘
           │ attack attempt
           ▼
┌──────────────────────┐
│ Target Agent         │
│ LLM + System Prompt  │
│ + Tools              │
└──────────┬────────────┘
           │ response
           ▼
┌──────────────────────┐
│ The Judge            │
│ programmatic checks  │
│ + LLM (fuzzy cases)  │
└──────────┬────────────┘
           │ verdict
           ▼
      feeds back into
      Attacker Agent
      for next refined attempt
```

### Attack Taxonomy (4 Categories)
| Category | Description | Verification |
|----------|-------------|--------------|
| **Prompt Injection** | Instructions in user input override agent rules | Canary-string disclosure check |
| **Guardrail Bypass** | Agent induced to violate behavioral/numeric rules | Programmatic check of value vs rule |
| **Tool-Call Hijacking** | Agent induced to call tool with attacker-controlled args | Programmatic verification of function call + args |
| **System Prompt Disclosure** | Agent reveals hidden system instructions | Canary-string substring match |

---

## 2. Architecture

### Directory Structure
```
red-teaming-agent/
├── .env                          # API keys (GROQ_API_KEY) — gitignored
├── .env.example                  # Template
├── DECISIONS.md                  # Architecture decision log
├── pyproject.toml                # Dependencies, tool config
├── PROJECT_DOCUMENTATION.md      # THIS FILE
├── README.md                     # Quick start
├── scripts/
│   ├── run_adaptive.py           # Main demo: recon → multi-round adaptive loop
│   ├── run_real_round.py         # Single round with real TargetAgent
│   └── try_specialist.py         # Offline specialist testing
├── src/
│   └── redteam/
│       ├── __init__.py
│       ├── py.typed
│       ├── shared/               # CORE: schemas, config, LLM wrapper, cost, storage
│       │   ├── __init__.py
│       │   ├── schemas.py        # Frozen Pydantic models (AttemptRecord, Trial, Verdict, RunSummary, RunManifest, LLMCallLog)
│       │   ├── settings.py       # Settings from .env (per-role models)
│       │   ├── llm.py            # LLMClient — single entry point for ALL LLM calls
│       │   ├── pricing.py        # Notional cost per model (fails on unknown)
│       │   └── storage.py        # JSONL append/read + manifest I/O
│       ├── attacker/             # Specialist agents
│       │   ├── __init__.py
│       │   ├── specialist.py     # Base Specialist class + JSON extraction
│       │   ├── injection.py      # A2: Prompt injection & disclosure
│       │   └── tool_hijack.py    # A3: Tool hijack & guardrail bypass
│       ├── loop/                 # Execution engine
│       │   ├── __init__.py
│       │   ├── runner.py         # run_round(): attempt → target → judge → Trial
│       │   └── target_adapter.py # Bridge external TargetAgent → runner
│       └── orchestrator/         # YOUR OWNERSHIP: Multi-round loop, selection, learnings, recon
│           ├── __init__.py
│           ├── selector.py       # Specialist selection policy (round_robin / weighted)
│           ├── learnings.py      # Trial summarization (≤200 words for RunSummary)
│           ├── recon.py          # Authorized probes → ReconReport
│           └── runner.py         # run_adaptive(): main multi-round orchestrator
├── tests/
│   ├── __init__.py
│   ├── fakes.py                  # FakeTarget, FakeJudge for offline testing
│   └── unit/
│       ├── test_orchestrator.py  # 20 tests for orchestrator components
│       └── ... (9 other test files)
└── data/                         # Gitignored — run outputs
    └── runs/<run_id>/
        ├── manifest.json
        ├── trials.jsonl
        ├── selections.jsonl
        ├── recon_report.json
        └── llm_calls.jsonl
```

### Core Data Contracts (`src/redteam/shared/schemas.py`)
All records are **immutable** (`frozen=True`, `extra="forbid"`):

| Schema | Purpose |
|--------|---------|
| `AttemptRecord` | Specialist's proposed attack (payload, category, tags, round) |
| `Verdict` | Judge's evaluation (outcome, confidence, evidence) |
| `Turn` | One message in conversation (speaker, content, tool_calls, guardrails) |
| `Trial` | Complete executed attempt (attempt + turns + verdict) |
| `RunManifest` | Reproducibility record (condition, model, budget, hash) |
| `RunSummary` | **Blackboard** — rounds_used, budget_remaining, learnings (≤200 words), success_probability |
| `LLMCallLog` | Cost logging per LLM call (tokens, cost, latency, attempt_id) |

**Enums:**
- `Outcome`: `attack_succeeded`, `target_refused`, `provider_blocked`, `inconclusive`
- `Condition`: `static_baseline` (frozen list), `adaptive` (swarm with feedback)
- `Environment`: `closed`, `open`, `stage0`

---

## 3. What Was Implemented This Session (Weekly Plan)

### Deliverables Completed ✅

| # | Component | File | Description |
|---|-----------|------|-------------|
| 1 | **Multi-round Runner** | `src/redteam/orchestrator/runner.py` | `run_adaptive()` — budget/round limits, specialist selection, blackboard updates |
| 2 | **Blackboard/RunSummary** | `src/redteam/orchestrator/learnings.py` | `summarize_trials()`, `update_learnings()`, `extract_patterns()` — feeds next round |
| 3 | **Adaptive Selector** | `src/redteam/orchestrator/selector.py` | `round_robin` & `weighted` (by `success_probability`) policies + `log_selection()` |
| 4 | **Recon Module** | `src/redteam/orchestrator/recon.py` | `ReconModule.run()` → `ReconReport` (tools, guardrails, refusals, canary test) |
| 5 | **Tests + Demo** | `tests/unit/test_orchestrator.py` (20 tests) + `scripts/run_adaptive.py` | All passing; demo works with fake & real LLM |

### Data Flow (Implemented)
```
recon (ReconModule)
    │
    ▼
RunSummary (rounds=0, budget=$X, learnings="", probs={})
    │
    ├───► select_specialist(summary, available, policy) ──► specialist name + reason
    │
    ├───► specialist.generate(count=1, learnings=summary.learnings, avoid=used_payloads)
    │
    ├───► run_round(attempt, target, judge) ──► Trial (with Verdict)
    │
    ├───► Update RunSummary:
    │       rounds_used++
    │       budget_remaining -= cost
    │       learnings = update_learnings(learnings, trial)
    │       success_probability = _update_success_probability(probs, trial)
    │
    ├───► Log selection to selections.jsonl
    │
    └───► Write RunManifest
    │
    └───► Repeat until rounds/budget exhausted
```

---

## 4. Key Files Reference

### Orchestrator (Your Ownership)
| File | Exports | Purpose |
|------|---------|---------|
| `selector.py` | `select_specialist()`, `log_selection()` | Policy + JSONL logging |
| `learnings.py` | `summarize_trials()`, `update_learnings()`, `extract_patterns()` | ≤200-word compression |
| `recon.py` | `ReconModule`, `ReconReport`, `ToolInfo`, `save_recon_report()` | Structured recon |
| `runner.py` | `run_adaptive()`, `run_static_baseline()` | Main loop + baseline |

### Shared (Team Core)
| File | Key Classes/Functions |
|------|----------------------|
| `schemas.py` | `AttemptRecord`, `Trial`, `Verdict`, `RunSummary`, `RunManifest`, `LLMCallLog`, enums |
| `llm.py` | `LLMClient.chat()` — **all LLM calls go here** (cost, retry, fallback) |
| `settings.py` | `Settings()` — per-role model/temp/effort from .env |
| `pricing.py` | `notional_cost_usd(model, in, out)` — fails on unknown model |
| `storage.py` | `run_dir()`, `append_jsonl()`, `write_manifest()`, `read_jsonl()` |

### Attacker Specialists
| File | Specialist | Categories |
|------|------------|------------|
| `injection.py` | `InjectionSpecialist` | `prompt_injection`, `disclosure` |
| `tool_hijack.py` | `ToolHijackSpecialist` | `tool_hijack`, `guardrail_bypass` |

### Loop / Target
| File | Purpose |
|------|---------|
| `loop/runner.py` | `run_round(attempt, target, judge, ...)` — single round execution |
| `loop/target_adapter.py` | `TargetAdapter` — bridges external TargetAgent to runner protocol |

---

## 5. How to Run

### Prerequisites
```bash
# Install uv if not present
pip install uv

# Clone & setup
git clone https://github.com/Fatma-Wael05/red-teaming-agent.git
cd red-teaming-agent
uv sync

# Copy env template and add your key
cp .env.example .env
# Edit .env → add GROQ_API_KEY=gsk_xxxxx...
```

### Demo Commands

#### With Fake LLM (No API Key Needed)
```bash
uv run python scripts/run_adaptive.py --rounds 5 --budget 1.0 --policy round_robin --fake
```

#### With Real Groq LLM (Requires .env with GROQ_API_KEY)
```bash
uv run python scripts/run_adaptive.py --rounds 3 --budget 0.50 --policy weighted
```

#### Other Scripts
```bash
# Single real round with TargetAgent_GP (if you have the repo)
uv run python scripts/run_real_round.py --specialist injection --n 3 --target-path ~/Documents/TargetAgent_GP

# Offline specialist testing
uv run python scripts/try_specialist.py --specialist injection --n 5
```

### Run Tests
```bash
# All tests
uv run pytest

# Orchestrator tests only
uv run pytest tests/unit/test_orchestrator.py -v

# Lint / type check
uv run ruff check
uv run mypy src
```

---

## 6. Output Files (Per Run)

Each run creates `data/runs/<run_id>/`:

| File | Content |
|------|---------|
| `manifest.json` | Run provenance: run_id, condition, model, budget, timestamps, total_cost_usd |
| `trials.jsonl` | Full Trial records (attempt, turns, verdict) — one per line |
| `selections.jsonl` | Specialist selection log: `{"round":0,"selected":"injection","reason":"weighted: {...}"}` |
| `recon_report.json` | Structured recon: tools, guardrails, refusals, canary test |
| `llm_calls.jsonl` | Cost tracking: every LLM call with tokens, cost, latency |

---

## 7. API Key Setup (Groq)

### .env File (Already Created)
```bash
# LLM Provider Settings
LLM_PROVIDER=groq
GROQ_API_KEY=your_groq_api_key_here

# Per-role models (from DECISIONS.md)
LLM_MODEL_ATTACKER=qwen/qwen3.8-27b
LLM_MODEL_JUDGE=openai/gpt-oss-120b
LLM_MODEL_TARGET=openai/gpt-oss-120b

# Temperature (attacker needs 0.7 for Qwen on Groq)
LLM_TEMPERATURE_ATTACKER=0.7
LLM_TEMPERATURE_JUDGE=0.0
LLM_TEMPERATURE_TARGET=0.0

# Fallback models
LLM_FALLBACKS=openai/gpt-oss-120b,qwen/qwen3.8-27b
```

### Pricing (src/redteam/shared/pricing.py)
```python
PRICES = {
    "openai/gpt-oss-120b": ModelPrice(input_per_million=0.15, output_per_million=0.60),
    "qwen/qwen3.8-27b": ModelPrice(input_per_million=0.80, output_per_million=4.00),
    "gpt-4o-mini": ModelPrice(input_per_million=0.15, output_per_million=0.60),
}
```
> Notional cost logged even on free tier. Unknown model → hard error (no silent $0).

---

## 8. Integration Boundaries (Team Coordination)

| Your Component | Receives From | Sends To |
|----------------|---------------|----------|
| **Selector** | `RunSummary.success_probability` (S1/J1) | Specialist name + reason |
| **Learnings** | `Trial` list (from runner) | `RunSummary.learnings` |
| **Recon** | `TargetPort` (T2 owns TargetAgent) | `ReconReport` → both specialists |
| **Runner** | `JudgePort` (J1 owns Judge) | `RunManifest`, `Trial` logs |

> **Do NOT modify:** `target/agent.py`, `judge/`, `attacker/*.py` prompts, static baseline logic.

---

## 9. What Works Now (Verified)

| Feature | Status | Verified |
|---------|--------|----------|
| Multi-round adaptive loop | ✅ | Demo runs 3+ rounds |
| Budget & round limits | ✅ | Stops when exhausted |
| Specialist selection (2 policies) | ✅ | round_robin / weighted |
| Blackboard updates per round | ✅ | rounds, budget, learnings, probs |
| Learnings compression (≤200 words) | ✅ | `update_learnings()` + validator |
| Recon module | ✅ | Tools, guardrails, refusals, canary |
| Selection logging | ✅ | `selections.jsonl` with reasons |
| Cost tracking | ✅ | `llm_calls.jsonl` with real Groq tokens |
| Unit tests (20) | ✅ | All passing |
| Real LLM integration | ✅ | qwen/qwen3.8-27b on Groq working |

---

## 10. Current Limitations (Documented)

| Component | Status | Notes |
|-----------|--------|-------|
| **Judge** | ⚠️ Fake only | `FakeJudge` in tests — only checks if tool call unblocked. Real judge module needed (`src/redteam/judge/`) |
| **TargetAgent** | ⚠️ External | Uses `TargetAdapter` to bridge `TargetAgent_GP` repo. Local target not implemented. |
| **Static Baseline** | ⚠️ Partial | `run_static_baseline()` exists but not integrated into comparison workflow. |
| **Dashboard** | ❌ Not started | Streamlit/Gradio for live monitoring — future work. |
| **Success Probability Display** | ⚠️ Empty | Weighted policy works but `success_probability` stays `{}` because `_update_success_probability` not wired in demo script. |

---

## 11. Next Steps (Priority Order)

### Immediate (This Sprint)
1. **Judge Module** — `src/redteam/judge/` with programmatic checkers + LLM fallback
   - Canary match, tool arg bounds, guardrail values
   - Ground-truth labeling + precision/recall measurement
2. **Static Baseline Comparison** — Frozen attack list + SHA-256 + equal-budget runner
3. **Wire `success_probability`** — Update demo script to call `_update_success_probability()`

### Short Term
4. **Integration Tests** — `tests/integration/` with real TargetAgent + Judge
5. **Dashboard** — Streamlit/Gradio: live round view, budget, selection reason, recon report
6. **Cost Engineering** — Context summarization, prompt caching, naive vs optimized comparison

### Documentation
7. **Final Report** — Evaluation metrics (success rate, efficiency, coverage, generalization)
8. **Live Demo Prep** — Pre-recorded fallback + local model option

---

## 12. Key Architectural Decisions (from DECISIONS.md)

| Date | Decision |
|------|----------|
| 2026-09-29 | Python 3.12 + uv. Docker POSTPONED (trigger: open-env milestone). Groq = dev provider. Every LLM call through cost wrapper. |
| 2026-10-02 | `llama-3.3-70b` shut down → switched to `openai/gpt-oss-120b`. |
| 2026-10-05 | Per-role models: attacker=`qwen/qwen3.8-27b`, judge/target=`openai/gpt-oss-120b` (temporary share). |
| 2026-10-06 | Attacker temp=0.7 fixes Qwen off-instruction output. Reasoning effort=none (10x cost). |
| 2026-10-09 | TargetAdapter copies target's call_log to llm_calls.jsonl until target uses injected client. |
| 2026-10-17 | Target now accepts injected LLM client. Adapter auto-disables duplicate logging. |

---

## 13. Resume Instructions (If Chat Deleted)

1. **Read this file** (`PROJECT_DOCUMENTATION.md`)
2. **Check `.env` exists** with `GROQ_API_KEY`
3. **Run tests** to verify environment:
   ```bash
   uv run pytest tests/unit/test_orchestrator.py -v
   ```
4. **Run demo** to verify end-to-end:
   ```bash
   uv run python scripts/run_adaptive.py --rounds 3 --fake
   uv run python scripts/run_adaptive.py --rounds 3  # with real LLM
   ```
5. **Continue from "Next Steps" (Section 11)**

---

## 14. Team Contacts & Repos

| Role | Owner | Repo/Notes |
|------|-------|------------|
| **Orchestration & Recon** | **George** | This repo (`red-teaming-agent`) |
| Target Agent | T2/J1 | `TargetAgent_GP` (separate repo) |
| Attack Specialists | A2/A3 | `injection.py`, `tool_hijack.py` (this repo) |
| Judge & Evaluation | J1 | `src/redteam/judge/` (to be created) |
| Static Baseline | S1 | `run_static_baseline()` (this repo) |

---

## 15. Quick Troubleshooting

| Issue | Fix |
|-------|-----|
| `provider 'openai' not supported` | Set `LLM_PROVIDER=groq` in .env; ensure `GROQ_API_KEY` set |
| `no price recorded for model` | Add model to `src/redteam/shared/pricing.py` PRICES dict |
| `ModuleNotFoundError: tests` | Run from project root: `uv run pytest` (adds root to path) |
| Demo uses fake LLM despite .env | Script loads `.env` via `python-dotenv` — ensure package installed or set env var manually |
| `UnboundLocalError: settings` | Fixed in runner.py — `settings = get_settings()` now outside conditional |

---

**End of Documentation** — This file contains everything needed to understand, run, and extend the adaptive orchestration & recon system. Store safely.