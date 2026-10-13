"""The shared HTTP client for store requests."""

from collections.abc import Callable
from datetime import datetime

import httpx
from sqlalchemy.orm import Session, sessionmaker

from pickled.stores.requests import AMSTERDAM, spend_request
from pickled.stores.store import Store

# AH is read through the Appie app's API, so it sees the app; Jumbo is read from its website.
USER_AGENTS = {
    Store.AH: "Appie/9.28 (iPhone17,3; iPhone; CPU OS 26_1 like Mac OS X)",
    Store.JUMBO: (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.4 Safari/605.1.15"
    ),
}
TIMEOUT_SECONDS = 30


def make_client(
    store: Store,
    sessions: sessionmaker[Session],
    *,
    transport: httpx.BaseTransport | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(AMSTERDAM),
) -> httpx.Client:
    """An `httpx.Client` for `store` that counts every request against its weekly budget.

    Each request is counted in its own transaction from `sessions` before it is sent, so the
    count survives even if the caller's work is rolled back. A request over budget raises
    `RequestBudgetExceeded` and is never sent.
    """

    def count(request: httpx.Request) -> None:
        with sessions.begin() as session:
            spend_request(session, store, now=clock())

    return httpx.Client(
        headers={"User-Agent": USER_AGENTS[store]},
        timeout=TIMEOUT_SECONDS,
        follow_redirects=True,
        transport=transport,
        event_hooks={"request": [count]},
    )
