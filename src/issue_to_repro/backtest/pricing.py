"""Token prices for estimating backtest spend.

Estimates are upper bounds: every prompt token is priced as uncached input, although cached
reads cost less. Prices are USD per million tokens, from the providers' published price lists;
update them when prices change. Gemini models are not listed because their current prices could
not be verified, so a spend cap cannot be applied to them.
"""

from dataclasses import dataclass

from ..config import Settings


@dataclass(frozen=True)
class Price:
    input_per_mtok: float
    output_per_mtok: float


PRICES: dict[str, Price] = {
    "claude-haiku-5-5": Price(0.10, 0.50),  # prompts up to 100K tokens
    "claude-sonnet-5-5": Price(2.00, 10.00),
    "claude-opus-5-5": Price(4.00, 20.00),
}


def price_of(model: str) -> Price:
    try:
        return PRICES[model]
    except KeyError:
        raise ValueError(
            f"no price known for {model!r}; add it to backtest/pricing.py to use a spend cap"
        ) from None


def cost_usd(model: str, prompt_tokens: int, output_tokens: int) -> float:
    price = price_of(model)
    return (prompt_tokens * price.input_per_mtok + output_tokens * price.output_per_mtok) / 1e6


def worst_case_cost(settings: Settings) -> float:
    """Most one case can cost: its whole token budget at the pricier of the two models' rates.

    The token budget is checked after each model call, so a case can overshoot it by one call's
    output; `anthropic_max_tokens` of output at the output price is added for that.
    """
    prices = [price_of(settings.coordinator_model), price_of(settings.worker_model)]
    input_rate = max(p.input_per_mtok for p in prices)
    output_rate = max(p.output_per_mtok for p in prices)
    budget = settings.backtest_max_tokens
    overshoot = settings.anthropic_max_tokens
    return (budget * input_rate + overshoot * output_rate) / 1e6
