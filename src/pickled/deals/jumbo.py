"""Jumbo Deals from the `__NUXT_DATA__` payload on jumbo.com/aanbiedingen/nu (ADR 0005).

One request a run. The payload is a devalue-encoded array that `resolve_nuxt` turns back into
plain JSON. It holds this week's Deals and, from Tuesday, next week's, grouped by category;
the same Deal can appear in several places. The models are named after Jumbo's payload types.
"""

import json
import re
from datetime import date, datetime
from typing import Any

import httpx
from pydantic import ValidationError

from pickled.deals.sources import Channel, DealPayloadError, DealRecord, FetchResult, StrictModel
from pickled.stores import AMSTERDAM, Store

OFFERS_URL = "https://www.jumbo.com/aanbiedingen/nu"
NUXT_DATA = re.compile(r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)

# Tags that say where a Deal applies rather than what it gives.
CHANNEL_TAGS = {
    "alleen online": Channel.ONLINE,
    "alleen online - op=op": Channel.ONLINE,
    "alleen in de winkel": Channel.IN_STORE,
    "alleen in de slijterij": Channel.IN_STORE,
}
NOT_A_DISCOUNT = {"op=op"}


class JumboDealSource:
    store = Store.JUMBO
    requests_per_fetch = 1

    def __init__(self, client: httpx.Client):
        self.client = client

    def download(self, on: date) -> list:
        """The raw `__NUXT_DATA__` array of the offers page (Jumbo shows only its current page)."""
        response = self.client.get(OFFERS_URL)
        response.raise_for_status()
        match = NUXT_DATA.search(response.text)
        if match is None:
            raise DealPayloadError("the Jumbo offers page has no __NUXT_DATA__ payload")
        return json.loads(match.group(1))

    def fetch(self, on: date) -> FetchResult:
        return parse(self.download(on), on)


class Tag(StrictModel):
    text: str


class Moment(StrictModel):
    iso: str

    def day(self) -> date:
        return datetime.fromisoformat(self.iso).astimezone(AMSTERDAM).date()


class Promotion(StrictModel):
    id: str
    title: str
    subtitle: str | None
    start: Moment
    end: Moment
    tags: list[Tag]
    active: bool
    hidden: bool


def parse(raw: list, on: date) -> FetchResult:
    """The Deals in a raw `__NUXT_DATA__` array that are valid on `on`."""
    deals: dict[str, DealRecord] = {}
    bad: set[str | int] = set()
    for item, category in _promotions(resolve_nuxt(raw)):
        try:
            promotion = Promotion.model_validate(item)
        except ValidationError:
            bad.add(item.get("id") if isinstance(item.get("id"), str) else id(item))
            continue
        if promotion.id in deals or not promotion.active or promotion.hidden:
            continue
        if promotion.start.day() <= on <= promotion.end.day():
            deals[promotion.id] = _deal(promotion, category)
    return FetchResult(
        store=Store.JUMBO, on=on, raw=raw, deals=list(deals.values()), skipped=len(bad)
    )


def _promotions(root: Any):
    """Each Deal's raw item with its category, if it has one, taking categorised copies first."""
    try:
        runtimes = root["data"]["nuTab"]["activeTab"]["runtimes"]
        sections = [section for runtime in runtimes for section in runtime["sections"]]
    except (KeyError, TypeError) as error:
        raise DealPayloadError(
            f"the Jumbo payload has lost its runtimes and sections: {error!r}"
        ) from error
    for section in sections:
        for category in section.get("categories") or []:
            for promotion in category.get("promotions") or []:
                yield promotion, category.get("title")
    for section in sections:
        for promotion in section.get("promotions") or []:
            yield promotion, None


def _deal(promotion: Promotion, category: str | None) -> DealRecord:
    tags = [tag.text.strip() for tag in promotion.tags]
    channels = [CHANNEL_TAGS[t.lower()] for t in tags if t.lower() in CHANNEL_TAGS]
    discounts = [t for t in tags if t.lower() not in CHANNEL_TAGS.keys() | NOT_A_DISCOUNT]
    return DealRecord(
        source_id=promotion.id,
        title=promotion.title,
        description=_plain(promotion.subtitle),
        discount_text=discounts[0] if discounts else " · ".join(tags),
        valid_from=promotion.start.day(),
        valid_to=promotion.end.day(),
        channel=channels[0] if channels else Channel.BOTH,
        category=category,
    )


def _plain(text: str | None) -> str | None:
    if text is None:
        return None
    return " ".join(re.sub(r"<br\s*/?>", "\n", text).split()) or None


# devalue encodes a few values as negative indices; we read them all as None.
WRAPPERS = {"Reactive", "ShallowReactive", "Ref", "ShallowRef"}


def resolve_nuxt(raw: list) -> Any:
    """Turn a devalue-encoded `__NUXT_DATA__` array back into plain JSON values.

    Each object or array holds indices into `raw`; Vue's reactive wrappers are unwrapped and
    other special forms (Date, Set, Map) are kept as they are.
    """
    if not isinstance(raw, list) or not raw:
        raise DealPayloadError("the __NUXT_DATA__ payload is not a devalue array")
    resolved: dict[int, Any] = {}

    def value(index: Any) -> Any:
        if not isinstance(index, int) or index < 0:
            return None
        if index in resolved:
            return resolved[index]
        entry = raw[index]
        if isinstance(entry, list) and entry and isinstance(entry[0], str):
            resolved[index] = value(entry[1]) if entry[0] in WRAPPERS and len(entry) > 1 else entry
        elif isinstance(entry, list):
            resolved[index] = out = []
            out.extend(value(i) for i in entry)
        elif isinstance(entry, dict):
            resolved[index] = obj = {}
            obj.update({key: value(i) for key, i in entry.items()})
        else:
            resolved[index] = entry
        return resolved[index]

    return value(0)
