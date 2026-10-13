"""Which adapter reads which store."""

import httpx

from pickled.deals.ah import AhDealSource
from pickled.deals.jumbo import JumboDealSource
from pickled.deals.sources import DealSource
from pickled.stores import Store

SOURCES = {Store.AH: AhDealSource, Store.JUMBO: JumboDealSource}


def source_for(store: Store, client: httpx.Client) -> DealSource:
    """The `DealSource` for `store`, sending its requests through `client`."""
    return SOURCES[store](client)
