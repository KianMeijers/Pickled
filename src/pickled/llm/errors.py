"""Telling apart the model errors that a retry can't fix."""

import anthropic
import httpx

PAYMENT_REQUIRED = 402


def out_of_credit(error: BaseException) -> bool:
    """Whether `error` is Runware saying the account's credit has run out (spec §9), from a
    model call or from a plain request such as the balance check."""
    if isinstance(error, anthropic.APIStatusError):
        return error.status_code == PAYMENT_REQUIRED
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code == PAYMENT_REQUIRED
    return False
