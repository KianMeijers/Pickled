"""`start_planning`: the first run fetches and tags both stores' Deals, then drafts."""

import asyncio

import pickled.jobs.draft
import pickled.jobs.start
from pickled.jobs.start import start_planning
from pickled.stores import Store


def record(monkeypatch, fail_fetch: set[Store] = frozenset()) -> list[tuple]:
    steps = []

    def fetch(store, sessions, *, now):
        if store in fail_fetch:
            raise RuntimeError(f"{store} is down")
        steps.append(("fetch", store))

    def tag(store, sessions, *, now):
        steps.append(("tag", store))

    async def draft(week_start, **options):
        steps.append(("draft", str(week_start)))

    monkeypatch.setattr(pickled.jobs.start, "fetch_deals_now", fetch)
    monkeypatch.setattr(pickled.jobs.start, "tag_deals_now", tag)
    monkeypatch.setattr(pickled.jobs.draft, "draft_with_the_app", draft)
    return steps


def test_it_fetches_and_tags_each_store_then_drafts_the_week(monkeypatch):
    steps = record(monkeypatch)

    asyncio.run(start_planning(week="2026-10-17"))

    assert steps == [
        ("fetch", Store.AH),
        ("tag", Store.AH),
        ("fetch", Store.JUMBO),
        ("tag", Store.JUMBO),
        ("draft", "2026-10-17"),
    ]


def test_a_store_that_fails_to_fetch_doesnt_stop_the_draft(monkeypatch):
    steps = record(monkeypatch, fail_fetch={Store.AH})

    asyncio.run(start_planning(week="2026-10-17"))

    assert steps == [("fetch", Store.JUMBO), ("tag", Store.JUMBO), ("draft", "2026-10-17")]
