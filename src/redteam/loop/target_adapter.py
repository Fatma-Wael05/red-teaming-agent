"""Bridge between the real TargetAgent (a separate repo) and the runner.

Until the target calls our LLM wrapper itself (rule 1), this copies the target's own
per-call log into llm_calls.jsonl at notional prices, tagged with the attempt id.
Switch that off with log_agent_calls=False once the target uses an injected client.
"""

from pathlib import Path
from typing import Any

from redteam.shared.pricing import notional_cost_usd
from redteam.shared.schemas import LLMCallLog
from redteam.shared.storage import append_jsonl


class TargetAdapter:
    def __init__(
        self,
        agent: Any,
        *,
        llm_log_path: Path | None = None,
        log_agent_calls: bool = True,
        provider: str = "groq",
    ) -> None:
        self._agent = agent
        self._llm_log_path = llm_log_path
        self._log_agent_calls = log_agent_calls
        self._provider = provider
        self._attempt_id: str | None = None
        # The real agent's call_log is cumulative and survives reset_conversation(),
        # so remember how much of it has already been copied.
        self._seen = len(self._agent_calls())

    def _agent_calls(self) -> list[dict[str, Any]]:
        calls = getattr(self._agent, "call_log", None)
        return calls if isinstance(calls, list) else []

    def begin_attempt(self, attempt_id: str) -> None:
        self._attempt_id = attempt_id
        if hasattr(self._agent, "attempt_id"):
            self._agent.attempt_id = attempt_id

    def reset_conversation(self) -> None:
        self._agent.reset_conversation()

    def handle_message(self, text: str) -> tuple[str, list[dict[str, Any]]]:
        try:
            result: tuple[str, list[dict[str, Any]]] = self._agent.handle_message(text)
            return result
        finally:
            self._copy_new_calls()

    def _to_log(self, record: dict[str, Any]) -> LLMCallLog:
        model = str(record.get("model", "unknown"))
        input_tokens = int(record.get("input_tokens", 0))
        output_tokens = int(record.get("output_tokens", 0))
        return LLMCallLog(
            role="target",
            provider=self._provider,
            requested_model=model,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=notional_cost_usd(model, input_tokens, output_tokens),
            latency_s=float(record.get("duration_sec", 0.0)),
            attempt_id=self._attempt_id,
        )

    def _copy_new_calls(self) -> None:
        calls = self._agent_calls()
        new = calls[self._seen :]
        if self._log_agent_calls and self._llm_log_path is not None:
            # Build every line first, so an unknown price fails before anything is written.
            logs = [self._to_log(record) for record in new]
            for log in logs:
                append_jsonl(self._llm_log_path, log)
        self._seen = len(calls)
