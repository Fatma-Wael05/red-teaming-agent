"""List prices used to compute notional cost, even while running on a free tier."""

from pydantic import BaseModel, ConfigDict


class ModelPrice(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_per_million: float
    output_per_million: float


# USD per million tokens, from the providers' model pages (checked 2026-10).
PRICES: dict[str, ModelPrice] = {
    "openai/gpt-oss-120b": ModelPrice(input_per_million=0.15, output_per_million=0.60),
    "qwen/qwen3.8-27b": ModelPrice(input_per_million=0.80, output_per_million=4.00),
}


def notional_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Dollar cost at list price. Unknown models fail loudly: a silent $0 would corrupt results."""
    try:
        price = PRICES[model]
    except KeyError:
        raise ValueError(f"no price recorded for model {model!r}; add it to PRICES") from None
    total = input_tokens * price.input_per_million + output_tokens * price.output_per_million
    return total / 1_000_000
