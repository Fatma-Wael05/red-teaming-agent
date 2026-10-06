# Decisions Log

## 2026-09-29
- Python 3.12, managed by uv. System Python (3.14) unused.
- Docker POSTPONED. Trigger condition: added when the open-environment milestone starts (target served over HTTP). Closed-env comparisons always run in-process.
- Groq (llama-3.3-70b-versatile) is the dev LLM provider. OpenAI-compatible API -> no extra dependency; wrapper uses the openai client with base_url. OpenAI/Anthropic keys stay in config for later provider-swap experiments.
- Every LLM call must pass through the cost-logging wrapper (to be built with the frozen schemas).

## 2026-10-02 - Groq model migration
- llama-3.3-70b-versatile was shut down by Groq on 2026-08-16 (supersedes the model named in the Groq provider decision above).
- Switched LLM_MODEL to openai/gpt-oss-120b, Groq's recommended replacement.
- Re-check tool calling and structured-output behavior in tests.

## 2026-10-05 - Per-role models
- attacker: qwen/qwen3.8-27b, judge: openai/gpt-oss-120b, target: openai/gpt-oss-120b.
- TEMPORARY: judge and target share a model while building. Switch the target to a different family before any baseline vs. adaptive comparison.
- Cost is logged at list price (notional) even on free tiers, so the Cost Engine stays meaningful.

## 2026-10-06 - Attacker temperature
- Qwen on Groq returned an off-instruction word at default sampling; temperature 0.7 (model page, instruct mode) fixed it in 3 of 3 trials.
- Thinking (reasoning_effort=low) cost about 10x the output tokens for the same answer, so the attacker default stays "none".
