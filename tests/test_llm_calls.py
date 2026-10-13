"""`make_chat_model(role)`: the one way to build a model, and the `llm_call` row per call."""

import logging
from decimal import Decimal

import pytest
from fakes import FakeChatModel, usage
from langchain_core.messages import AIMessage
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from pickled.llm import LlmCall, Role, llm_context, make_chat_model


def fake(**usage_counts) -> FakeChatModel:
    return FakeChatModel(replies=[AIMessage(content="ok", usage_metadata=usage(**usage_counts))])


def fake_build(model):
    """A `build` for `make_chat_model` that returns `model` and notes which name it was given."""

    def build(name, settings):
        build.names.append(name)
        return model

    build.names = []
    return build


def calls(db_session) -> list[LlmCall]:
    return list(db_session.scalars(select(LlmCall).order_by(LlmCall.id)))


def test_a_call_writes_a_row_with_its_role_model_tokens_and_cost(db_session, sessions, monkeypatch):
    monkeypatch.setenv("PICKLED_CHAT_MODEL", "claude-sonnet-5-5")
    model = make_chat_model(
        Role.CHAT,
        sessions=sessions,
        build=fake_build(
            fake(input_tokens=300, output_tokens=40, cache_read=1000, cache_creation=200)
        ),
    )

    assert model.invoke("hoi").content == "ok"

    [call] = calls(db_session)
    assert (call.role, call.model) == (Role.CHAT, "claude-sonnet-5-5")
    assert (call.input_tokens, call.cache_write_tokens, call.cache_read_tokens) == (300, 200, 1000)
    assert call.output_tokens == 40
    assert call.cost_usd == Decimal("0.0017")
    assert call.called_at is not None


def test_the_row_says_which_job_started_the_call(db_session, sessions):
    model = make_chat_model(Role.TAG_DEALS, sessions=sessions, build=fake_build(fake()))

    with llm_context(job="tag_deals"):
        model.invoke("hoi")

    [call] = calls(db_session)
    assert (call.job, call.meal_plan_id) == ("tag_deals", None)


def test_the_row_says_which_meal_plan_started_the_call(db_session, sessions):
    model = make_chat_model(Role.CHAT, sessions=sessions, build=fake_build(fake()))

    with llm_context(meal_plan=7):
        model.invoke("hoi")

    [call] = calls(db_session)
    assert (call.job, call.meal_plan_id) == (None, 7)


def test_the_context_ends_with_its_block(db_session, sessions):
    model = make_chat_model(
        Role.CHAT,
        sessions=sessions,
        build=fake_build(
            FakeChatModel(
                replies=[
                    AIMessage(content="a", usage_metadata=usage()),
                    AIMessage(content="b", usage_metadata=usage()),
                ]
            )
        ),
    )

    with llm_context(job="draft_meal_plan"):
        model.invoke("hoi")
    model.invoke("hoi")

    assert [call.job for call in calls(db_session)] == ["draft_meal_plan", None]


def test_a_model_without_a_price_records_an_unknown_cost(db_session, sessions, monkeypatch):
    monkeypatch.setenv("PICKLED_CHAT_MODEL", "claude-mystery-9")
    model = make_chat_model(Role.CHAT, sessions=sessions, build=fake_build(fake()))

    model.invoke("hoi")

    [call] = calls(db_session)
    assert (call.model, call.cost_usd) == ("claude-mystery-9", None)


def test_a_failed_write_is_logged_and_the_call_still_answers(caplog):
    nowhere = sessionmaker(create_engine("postgresql+psycopg://nobody@127.0.0.1:1/nothing"))
    model = make_chat_model(Role.CHAT, sessions=nowhere, build=fake_build(fake()))

    with caplog.at_level(logging.ERROR):
        assert model.invoke("hoi").content == "ok"

    assert "Could not record a chat call" in caplog.text


@pytest.mark.parametrize(
    ("role", "setting"),
    [
        (Role.CHAT, "PICKLED_CHAT_MODEL"),
        (Role.DRAFT, "PICKLED_DRAFT_MODEL"),
        (Role.REFLECT, "PICKLED_DRAFT_MODEL"),
        (Role.TAG_DEALS, "PICKLED_MATCH_MODEL"),
        (Role.PICK_PRODUCT, "PICKLED_MATCH_MODEL"),
        (Role.EVAL_JUDGE, "PICKLED_JUDGE_MODEL"),
    ],
)
def test_each_role_uses_its_model_setting(role, setting, monkeypatch):
    monkeypatch.setenv(setting, "claude-opus-5-5")
    build = fake_build(fake())

    make_chat_model(role, build=build)

    assert build.names == ["claude-opus-5-5"]


def test_the_model_talks_to_runware_with_a_bearer_key_a_timeout_and_retries(monkeypatch):
    monkeypatch.setenv("RUNWARE_API_KEY", "rw-test-key")
    monkeypatch.setenv("RUNWARE_BASE_URL", "https://runware.test")
    monkeypatch.setenv("PICKLED_LLM_TIMEOUT_SECONDS", "120")
    monkeypatch.setenv("PICKLED_LLM_MAX_RETRIES", "2")
    monkeypatch.setenv("PICKLED_CHAT_MODEL", "claude-sonnet-5-5")

    model = make_chat_model(Role.CHAT)

    assert model.anthropic_api_url == "https://runware.test"
    assert model.default_headers == {"Authorization": "Bearer rw-test-key"}
    assert (model.default_request_timeout, model.max_retries) == (120, 2)
    assert model.model == "claude-sonnet-5-5"
