"""Record one real Deals payload for a store as a test fixture.

    uv run python scripts/record_deal_fixture.py ah|jumbo

Every request goes through the store's request counter, so it counts against the weekly
budget (ADR 0005). Tests read the fixture and never hit the network.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pickled.config import Settings
from pickled.deals.registry import SOURCES
from pickled.stores import AMSTERDAM, Store, make_client

FIXTURES = Path(__file__).parents[1] / "tests" / "fixtures"


def main(store: Store) -> None:
    sessions = sessionmaker(create_engine(Settings().database_url))
    today = datetime.now(AMSTERDAM).date()
    with make_client(store, sessions) as client:
        raw = SOURCES[store](client).download(today)
    path = FIXTURES / f"deals_{store}_{today.isoformat()}.json"
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=1) + "\n")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main(Store(sys.argv[1]))
