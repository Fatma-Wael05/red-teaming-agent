# Decisions Log

## 2026-09-29
- Python 3.12, managed by uv. System Python (3.14) unused.
- Docker POSTPONED. Trigger condition: added when the open-environment milestone starts (target served over HTTP). Closed-env comparisons always run in-process.
- Groq (llama-3.3-70b-versatile) is the dev LLM provider. OpenAI-compatible API -> no extra dependency; wrapper uses the openai client with base_url. OpenAI/Anthropic keys stay in config for later provider-swap experiments.
- Every LLM call must pass through the cost-logging wrapper (to be built with the frozen schemas).
