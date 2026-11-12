"""`check_llm_balance`: a daily job reads the Runware account balance into `llm_balance`
(spec §6, §9)."""

import json
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from pickled.jobs import app
from pickled.jobs.balance import check_llm_balance, check_llm_balance_now
from pickled.llm import LlmBalance, read_runware_balance
from pickled.stores import AMSTERDAM

NOW = datetime(2026, 10, 12, 7, 0, tzinfo=AMSTERDAM)


def runware(amount=12.34, *, currency="USD", status=200, sent=None) -> httpx.Client:
    """A client on a fake Runware that answers `getDetails` with `amount`."""

    def handle(request: httpx.Request) -> httpx.Response:
        if sent is not None:
            sent.append(request)
        [task] = json.loads(request.content)
        details = {
            "taskType": "accountManagement",
            "taskUUID": task["taskUUID"],
            "operation": "getDetails",
            "balance": {"amount": amount, "freeBalance": 0.0, "currency": currency},
        }
        return httpx.Response(status, json={"data": [details]})

    return httpx.Client(transport=httpx.MockTransport(handle), base_url="https://api.runware.ai")


def test_the_balance_is_read_from_runwares_account_details():
    sent = []

    balance = read_runware_balance(runware(12.34, sent=sent), api_key="secret")

    assert balance == Decimal("12.34")
    [request] = sent
    assert (request.method, request.url.path) == ("POST", "/v1")
    assert request.headers["Authorization"] == "Bearer secret"
    [task] = json.loads(request.content)
    assert (task["taskType"], task["operation"]) == ("accountManagement", "getDetails")


def test_a_balance_in_another_currency_is_refused():
    with pytest.raises(ValueError, match="EUR"):
        read_runware_balance(runware(12.34, currency="EUR"), api_key="secret")


def test_the_job_stores_the_balance_with_when_it_was_checked(db_session, sessions):
    check_llm_balance_now(sessions, now=NOW, read=lambda: Decimal("8.50"))

    [balance] = db_session.scalars(select(LlmBalance))
    assert (balance.balance_usd, balance.checked_at) == (Decimal("8.50"), NOW)


def test_the_balance_is_checked_daily_at_eight_in_the_morning_amsterdam_time():
    [task] = [
        task
        for (name, _), task in app.periodic_registry.periodic_tasks.items()
        if name == check_llm_balance.name
    ]

    timestamp = task.croniter.get_next(ret_type=float, start_time=NOW.timestamp())

    assert datetime.fromtimestamp(timestamp, AMSTERDAM) == datetime(
        2026, 10, 12, 8, 0, tzinfo=AMSTERDAM
    )


def test_a_balance_check_is_not_retried_once_runware_says_the_credit_has_run_out():
    request = httpx.Request("POST", "https://api.runware.ai/v1")
    no_credit = httpx.HTTPStatusError(
        "Payment required", request=request, response=httpx.Response(402, request=request)
    )

    decision = check_llm_balance.retry_strategy.get_retry_decision(
        exception=no_credit, job=SimpleNamespace(attempts=0)
    )

    assert decision is None
