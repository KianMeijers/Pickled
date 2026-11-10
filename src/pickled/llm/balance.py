"""The Runware account balance. Runware reports no cost per call, so the balance read daily is
the check on our own spend record (ADR 0009)."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from pickled.llm.models import LlmBalance
from pickled.llm.spend import recorded_spend


def read_runware_balance(client: httpx.Client, *, api_key: str) -> Decimal:
    """The account's balance in USD, from Runware's `accountManagement` `getDetails` task.

    `client` has Runware's base URL. Raises `httpx.HTTPStatusError` for a refused request, and
    `ValueError` for a balance in another currency.
    """
    task = {"taskType": "accountManagement", "taskUUID": str(uuid4()), "operation": "getDetails"}
    response = client.post("/v1", json=[task], headers={"Authorization": f"Bearer {api_key}"})
    response.raise_for_status()
    balance = response.json()["data"][0]["balance"]
    if balance["currency"] != "USD":
        raise ValueError(f"Runware reports the balance in {balance['currency']}, not USD")
    return Decimal(str(balance["amount"]))


def latest_balance(session: Session) -> LlmBalance | None:
    """The balance last read, or None before the first check."""
    return session.scalars(select(LlmBalance).order_by(LlmBalance.checked_at.desc())).first()


@dataclass(frozen=True)
class BalanceComparison:
    """The drop in the balance between the first and last check in a month, against what our
    own record says the calls in between cost. A top-up in between makes the drop meaningless."""

    first: LlmBalance
    last: LlmBalance
    recorded: Decimal

    @property
    def drop(self) -> Decimal:
        return self.first.balance_usd - self.last.balance_usd

    @property
    def difference(self) -> Decimal:
        return self.drop - self.recorded


def compare_balance(
    session: Session, *, start: datetime, end: datetime
) -> BalanceComparison | None:
    """The comparison for the checks from `start` until `end`; None with fewer than two."""
    checks = list(
        session.scalars(
            select(LlmBalance)
            .where(LlmBalance.checked_at >= start, LlmBalance.checked_at < end)
            .order_by(LlmBalance.checked_at)
        )
    )
    if len(checks) < 2:
        return None
    first, last = checks[0], checks[-1]
    recorded = recorded_spend(session, start=first.checked_at, end=last.checked_at)
    return BalanceComparison(first, last, recorded)
