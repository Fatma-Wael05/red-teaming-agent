from redteam.shared.schemas import LLMCallLog


def _log(**extra: object) -> LLMCallLog:
    return LLMCallLog(
        role="judge",
        provider="groq",
        requested_model="openai/gpt-oss-120b",
        model="openai/gpt-oss-120b",
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.0,
        latency_s=0.5,
        **extra,
    )


def test_finish_reason_is_optional() -> None:
    assert _log().finish_reason is None


def test_finish_reason_roundtrips_through_json() -> None:
    log = _log(finish_reason="content_filter")
    assert LLMCallLog.model_validate_json(log.model_dump_json()).finish_reason == "content_filter"
