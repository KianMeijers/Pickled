"""What a model call cost, from a price table in code (ADR 0009).

Runware reports token usage but no cost, so the cost is usage × these prices. They are
Anthropic's list prices in USD per million tokens; the monthly comparison against the Runware
balance shows if Runware's real prices drift from them.
"""

import logging
from dataclasses import dataclass
from decimal import Decimal

from langchain_core.messages.ai import UsageMetadata

logger = logging.getLogger(__name__)

MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class Price:
    """USD per million tokens of each kind. Cache writes are priced at the 5-minute rate."""

    input: Decimal
    cache_write: Decimal
    cache_read: Decimal
    output: Decimal


SONNET_5_5 = Price(Decimal("2"), Decimal("2.5"), Decimal("0.2"), Decimal("10"))
OPUS_5_5 = Price(Decimal("4"), Decimal("5"), Decimal("0.2"), Decimal("20"))

# Runware accepts both Anthropic's names and its own ids, and reports its own.
PRICES = {
    "claude-sonnet-5-5": SONNET_5_5,
    "anthropic:claude@sonnet-5.5": SONNET_5_5,
    "claude-opus-5-5": OPUS_5_5,
    "anthropic:claude@opus-5.5": OPUS_5_5,
}


@dataclass(frozen=True)
class TokenUsage:
    """The tokens of one call, by kind. `input` is only the uncached input."""

    input: int
    cache_write: int
    cache_read: int
    output: int

    @classmethod
    def from_metadata(cls, metadata: UsageMetadata) -> TokenUsage:
        """Split LangChain's `usage_metadata`, whose `input_tokens` includes cached tokens."""
        details = metadata.get("input_token_details") or {}
        cache_read = details.get("cache_read") or 0
        cache_write = (details.get("cache_creation") or 0) + sum(
            details.get(key) or 0
            for key in ("ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens")
        )
        return cls(
            input=metadata["input_tokens"] - cache_read - cache_write,
            cache_write=cache_write,
            cache_read=cache_read,
            output=metadata["output_tokens"],
        )


def price_of(model: str, usage: TokenUsage) -> Decimal | None:
    """The cost of `usage` on `model` in USD, or None (with a warning) for an unknown model."""
    price = PRICES.get(model)
    if price is None:
        logger.warning("No price for the model %r; its cost is recorded as unknown", model)
        return None
    return (
        usage.input * price.input
        + usage.cache_write * price.cache_write
        + usage.cache_read * price.cache_read
        + usage.output * price.output
    ) / MILLION
