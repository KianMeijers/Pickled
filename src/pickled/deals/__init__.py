"""Deals from AH and Jumbo: the DealSource port, discount parsing, storing and querying."""

from pickled.deals.ah import AhDealSource
from pickled.deals.discounts import Discount, DiscountKind, parse_discount
from pickled.deals.jumbo import JumboDealSource
from pickled.deals.models import Deal, DealFetch, DealProduct
from pickled.deals.registry import source_for
from pickled.deals.sources import (
    Channel,
    DealPayloadError,
    DealProductRecord,
    DealRecord,
    DealSource,
    FetchResult,
)
from pickled.deals.storing import FetchRejected, deals_valid_on, save_fetch

__all__ = [
    "AhDealSource",
    "Channel",
    "Deal",
    "DealFetch",
    "DealPayloadError",
    "DealProduct",
    "DealProductRecord",
    "DealRecord",
    "DealSource",
    "Discount",
    "DiscountKind",
    "FetchRejected",
    "FetchResult",
    "JumboDealSource",
    "deals_valid_on",
    "parse_discount",
    "save_fetch",
    "source_for",
]
