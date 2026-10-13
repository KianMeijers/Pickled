"""Telling apart the model errors that a retry can't fix."""

import anthropic

PAYMENT_REQUIRED = 402


def out_of_credit(error: BaseException) -> bool:
    """Whether `error` is Runware saying the account's credit has run out (spec §9)."""
    return isinstance(error, anthropic.APIStatusError) and error.status_code == PAYMENT_REQUIRED
