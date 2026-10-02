# redteam — Autonomous Multi-Agent Red-Teaming System

A red-teaming system for agentic AI: a coordinated team of specialist attacker agents
probes, attacks, and adaptively refines attempts against self-built target agents.
Every attempt is verified by a hybrid judge (programmatic checks first, a constrained
LLM only for fuzzy cases).

## Prerequisites

- Git
- uv — `pip install uv` (or see https://docs.astral.sh/uv/getting-started/installation/)

## Setup (5 commands)

```powershell
git clone https://github.com/Fatma-Wael05/red-teaming-agent.git
cd red-teaming-agent
uv sync
Copy-Item .env.example .env
uv run pytest
```

## Daily commands

| Command                                    | What it does                          |
| :----------------------------------------- | :------------------------------------ |
| `uv sync`                                  | Install exact versions from `uv.lock` |
| `uv run pytest`                            | Run the test suite                    |
| `uv run ruff check` / `uv run ruff format` | Lint / auto-format                    |
| `uv run mypy src`                          | Type check                            |

## Project layout

- `src/redteam/shared/` — frozen schemas, configuration, cost-logging wrapper
- `src/redteam/target/` — the guarded target agent
- `src/redteam/attacker/` — specialist agents + orchestrator
- `src/redteam/judge/` — verification checkers
- `tests/unit/`, `tests/integration/` — tests
- `configs/` — taxonomy + target profiles
- `data/` — run logs and reference DB (gitignored)
- `DECISIONS.md` — every irreversible choice

## Team rules

1. Never commit `.env`; real keys live only in your local `.env`.
2. Never work directly on `main` — branch + pull request.
3. Every LLM call goes through the cost wrapper.
4. Docker is intentionally postponed — trigger condition recorded in `DECISIONS.md`.
