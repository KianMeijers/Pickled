"""The supermarkets Pickled reads from, and the rules for talking to them (ADR 0005).

Every request to a store goes through `make_client`, which counts it against the store's
weekly budget and refuses it once the budget is spent.
"""

from pickled.stores.http import make_client
from pickled.stores.requests import (
    REQUEST_BUDGET,
    RequestBudgetExceeded,
    StoreRequest,
    requests_this_week,
    spend_request,
)
from pickled.stores.store import Store

__all__ = [
    "REQUEST_BUDGET",
    "RequestBudgetExceeded",
    "Store",
    "StoreRequest",
    "make_client",
    "requests_this_week",
    "spend_request",
]
