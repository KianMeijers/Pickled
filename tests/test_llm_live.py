"""A smoke test against Runware itself: `uv run pytest -m live`. It spends a fraction of a cent."""

import pytest
from sqlalchemy import select

from pickled.config import Settings
from pickled.llm import LlmCall, Role, llm_context, make_chat_model

pytestmark = pytest.mark.live


def test_runware_answers_and_the_call_is_recorded_with_a_cost(db_session, sessions):
    if not Settings().runware_api_key.get_secret_value():
        pytest.fail("RUNWARE_API_KEY is not set")
    model = make_chat_model(Role.CHAT, sessions=sessions)

    with llm_context(job="smoke_test"):
        reply = model.invoke("Antwoord met alleen het woord: komkommer")

    assert "komkommer" in reply.text.lower()
    [call] = db_session.scalars(select(LlmCall))
    assert call.job == "smoke_test"
    assert call.input_tokens > 0 and call.output_tokens > 0
    assert call.cost_usd > 0
