"""`pickled jobs run <job> [--source …]` reruns a job by hand, in this process."""

import pytest

import pickled.jobs.deals
from pickled.cli import main
from pickled.stores import Store


@pytest.fixture
def fetched(monkeypatch):
    stores = []
    monkeypatch.setattr(
        pickled.jobs.deals, "fetch_deals_now", lambda store, sessions, now: stores.append(store)
    )
    return stores


def test_jobs_run_fetch_deals_for_one_source(fetched):
    main(["jobs", "run", "fetch_deals", "--source", "ah"])

    assert fetched == [Store.AH]


def test_jobs_run_fetch_deals_without_a_source_fetches_every_store(fetched):
    main(["jobs", "run", "fetch_deals"])

    assert fetched == [Store.AH, Store.JUMBO]


def test_jobs_run_refuses_an_unknown_job():
    with pytest.raises(SystemExit):
        main(["jobs", "run", "make_coffee"])


def test_jobs_run_fetches_the_other_stores_when_one_fails(monkeypatch):
    stores = []

    def fetch(store, sessions, now):
        stores.append(store)
        if store is Store.AH:
            raise RuntimeError("AH is down")

    monkeypatch.setattr(pickled.jobs.deals, "fetch_deals_now", fetch)

    with pytest.raises(RuntimeError, match="AH is down"):
        main(["jobs", "run", "fetch_deals"])
    assert stores == [Store.AH, Store.JUMBO]
