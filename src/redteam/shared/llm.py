"""The one place every LLM call goes through (rule 1).

Routes a role to its model, retries transient errors, falls back to the next model
(never for the target unless asked), computes notional cost, and appends one LLMCallLog
line per answered call.
"""

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openai import APIConnectionError, OpenAI

from redteam.shared.pricing import notional_cost_usd
from redteam.shared.schemas import LLMCallLog, ToolCall
from redteam.shared.settings import GROQ_BASE_URL, Settings
from redteam.shared.storage import append_jsonl

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


class LLMError(Exception):
    """Base class for wrapper errors."""


class MissingKeyError(LLMError):
    """The API key for a provider is empty or still a placeholder."""


class AllModelsFailed(LLMError):
    """Every model in the fallback chain failed with a retryable error."""


@dataclass(frozen=True)
class LLMResult:
    text: str
    finish_reason: str | None
    call: LLMCallLog
    tool_calls: tuple[ToolCall, ...] = ()
    # Ready to append to the conversation history. When the model called tools it carries
    # the tool-call ids, in the same order as tool_calls, for the matching tool messages.
    assistant_message: dict[str, Any] = field(default_factory=dict)


def is_retryable(exc: Exception) -> bool:
    """Rate limits, timeouts, server errors and dropped connections are worth retrying."""
    if isinstance(exc, APIConnectionError):
        return True
    status = getattr(exc, "status_code", None)
    return isinstance(status, int) and (status in (408, 429) or status >= 500)


def build_client(provider: str, settings: Settings) -> Any:
    if provider != "groq":
        raise LLMError(f"provider {provider!r} is not supported yet")
    key = settings.groq_api_key
    if not key or key.startswith("your_"):
        msg = "GROQ_API_KEY is empty or a placeholder; set it in your local .env"
        raise MissingKeyError(msg)
    return OpenAI(api_key=key, base_url=GROQ_BASE_URL)


def parse_arguments(raw: Any) -> dict[str, Any]:
    """Tool arguments arrive as a JSON string. Anything unusable becomes an empty dict."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _extract_tools(text: str, message: Any) -> tuple[tuple[ToolCall, ...], dict[str, Any]]:
    """Turn the model's raw message into ToolCall records plus a history-ready message."""
    raw_calls = getattr(message, "tool_calls", None) or []
    calls: list[ToolCall] = []
    wire: list[dict[str, Any]] = []
    for tc in raw_calls:
        raw_args = tc.function.arguments
        calls.append(ToolCall(name=tc.function.name, arguments=parse_arguments(raw_args)))
        wire.append(
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": raw_args
                    if isinstance(raw_args, str)
                    else json.dumps(raw_args or {}),
                },
            }
        )
    assistant: dict[str, Any] = {
        "role": "assistant",
        "content": text if (text or not wire) else None,
    }
    if wire:
        assistant["tool_calls"] = wire
    return tuple(calls), assistant


def _request_kwargs(
    model: str,
    messages: list[dict[str, Any]],
    effort: str | None,
    temperature: float | None,
    max_tokens: int | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"model": model, "messages": messages}
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if effort is not None:
        kwargs["reasoning_effort"] = effort
    if tools is not None:
        kwargs["tools"] = tools
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice
    if seed is not None:
        kwargs["seed"] = seed
    return kwargs


class LLMClient:
    def __init__(
        self,
        settings: Settings,
        log_path: Path | None = None,
        *,
        client_factory: Callable[[str], Any] | None = None,
        max_retries: int = 2,
        backoff_s: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._log_path = log_path
        self._factory = client_factory or (lambda provider: build_client(provider, settings))
        self._max_retries = max_retries
        self._backoff_s = backoff_s
        self._sleep = sleep
        self._clock = clock
        self._clients: dict[str, Any] = {}

    def _client(self, provider: str) -> Any:
        if provider not in self._clients:
            self._clients[provider] = self._factory(provider)
        return self._clients[provider]

    def chat(
        self,
        role: str,
        messages: list[dict[str, Any]],
        *,
        attempt_id: str | None = None,
        caller: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        seed: int | None = None,
        allow_fallback: bool | None = None,
    ) -> LLMResult:
        cfg = self._settings.role_config(role)
        temp = temperature if temperature is not None else cfg.temperature
        # A fallback silently changes what we are measuring, so the target never gets one
        # unless the caller asks for it explicitly.
        use_fallbacks = allow_fallback if allow_fallback is not None else role != "target"
        fallbacks = (
            [m for m in self._settings.fallback_models() if m != cfg.model] if use_fallbacks else []
        )
        chain = [cfg.model, *fallbacks]
        for model in chain:
            notional_cost_usd(model, 0, 0)  # an unknown price fails here, before any call
        client = self._client(cfg.provider)

        last_error: Exception | None = None
        for model in chain:
            effort = cfg.reasoning_effort if model == cfg.model else None
            kwargs = _request_kwargs(
                model,
                messages,
                effort=effort,
                temperature=temp,
                max_tokens=max_tokens,
                tools=tools,
                tool_choice=tool_choice,
                seed=seed,
            )
            try:
                resp, latency = self._create_with_retries(client, kwargs)
            except Exception as exc:
                if not is_retryable(exc):
                    raise
                last_error = exc
                continue
            return self._finish(
                resp,
                latency,
                role=caller or role,
                provider=cfg.provider,
                requested_model=cfg.model,
                model=model,
                attempt_id=attempt_id,
            )
        raise AllModelsFailed(f"all models failed for role {role!r}: {chain}") from last_error

    def _create_with_retries(self, client: Any, kwargs: dict[str, Any]) -> tuple[Any, float]:
        for attempt in range(self._max_retries + 1):
            start = self._clock()
            try:
                resp = client.chat.completions.create(**kwargs)
            except Exception as exc:
                if not is_retryable(exc) or attempt == self._max_retries:
                    raise
                self._sleep(self._backoff_s * (2**attempt))
                continue
            return resp, self._clock() - start
        raise AssertionError("unreachable")

    def _finish(
        self,
        resp: Any,
        latency: float,
        *,
        role: str,
        provider: str,
        requested_model: str,
        model: str,
        attempt_id: str | None,
    ) -> LLMResult:
        text = ""
        finish: str | None = "no_choices"
        message: Any = None
        if resp.choices:
            choice = resp.choices[0]
            message = choice.message
            raw: str = message.content or ""
            text = _THINK_RE.sub("", raw).strip()
            finish = choice.finish_reason

        usage = getattr(resp, "usage", None)
        input_tokens: int = getattr(usage, "prompt_tokens", 0) or 0
        output_tokens: int = getattr(usage, "completion_tokens", 0) or 0
        call = LLMCallLog(
            role=role,
            provider=provider,
            requested_model=requested_model,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=notional_cost_usd(model, input_tokens, output_tokens),
            latency_s=latency,
            attempt_id=attempt_id,
            finish_reason=finish,
        )
        if self._log_path is not None:
            append_jsonl(self._log_path, call)

        tool_calls, assistant_message = _extract_tools(text, message)
        return LLMResult(
            text=text,
            finish_reason=finish,
            call=call,
            tool_calls=tool_calls,
            assistant_message=assistant_message,
        )
