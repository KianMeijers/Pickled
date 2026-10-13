"""`price_of(model, usage)`: what a call cost in USD, from the price table in code."""

import logging
from decimal import Decimal

from pickled.llm import TokenUsage, price_of


def test_each_kind_of_token_is_priced_per_million():
    usage = TokenUsage(
        input=1_000_000, cache_write=1_000_000, cache_read=1_000_000, output=1_000_000
    )

    assert price_of("claude-sonnet-5-5", usage) == Decimal("14.7")


def test_a_small_call_costs_a_fraction_of_a_cent():
    usage = TokenUsage(input=1200, cache_write=0, cache_read=0, output=300)

    assert price_of("claude-opus-5-5", usage) == Decimal("0.0108")


def test_runware_model_ids_are_priced_like_anthropic_names():
    usage = TokenUsage(input=1000, cache_write=0, cache_read=0, output=1000)

    assert price_of("anthropic:claude@sonnet-5.5", usage) == price_of("claude-sonnet-5-5", usage)


def test_an_unknown_model_has_no_price_and_logs_a_warning(caplog):
    usage = TokenUsage(input=1000, cache_write=0, cache_read=0, output=1000)

    with caplog.at_level(logging.WARNING):
        assert price_of("claude-mystery-9", usage) is None

    assert "claude-mystery-9" in caplog.text


def test_usage_metadata_splits_the_cached_tokens_out_of_the_input():
    # LangChain's `input_tokens` already includes the cache reads and writes.
    metadata = {
        "input_tokens": 1500,
        "output_tokens": 40,
        "total_tokens": 1540,
        "input_token_details": {"cache_read": 1000, "cache_creation": 200},
    }

    assert TokenUsage.from_metadata(metadata) == TokenUsage(
        input=300, cache_write=200, cache_read=1000, output=40
    )


def test_usage_metadata_without_cache_details_is_all_plain_input():
    metadata = {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15}

    assert TokenUsage.from_metadata(metadata) == TokenUsage(
        input=12, cache_write=0, cache_read=0, output=3
    )


def test_usage_metadata_counts_cache_writes_reported_by_ttl():
    metadata = {
        "input_tokens": 700,
        "output_tokens": 5,
        "total_tokens": 705,
        "input_token_details": {
            "cache_read": 0,
            "cache_creation": 0,
            "ephemeral_5m_input_tokens": 500,
            "ephemeral_1h_input_tokens": 100,
        },
    }

    assert TokenUsage.from_metadata(metadata) == TokenUsage(
        input=100, cache_write=600, cache_read=0, output=5
    )
