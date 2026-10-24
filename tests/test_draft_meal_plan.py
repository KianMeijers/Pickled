"""The `draft_meal_plan(week)` job: the agent drafts a whole Meal Plan through its tools."""

import asyncio
import re
from datetime import datetime

import pytest
from fakes import FakeChatModel, reply, tool_calls
from langchain_core.messages import ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from planning_helpers import (
    AMSTERDAM,
    NOW,
    SATURDAY,
    TODAY,
    WEEK,
    FakePrices,
    deal,
    ingredient,
    plan,
    recipe,
)
from sqlalchemy import select

from pickled.agent import DRAFT_CALL_LIMIT, conversation
from pickled.ingredients import Aisle
from pickled.jobs.draft import MissingDeals, draft_meal_plan_now
from pickled.llm import LlmCall, Role, make_chat_model
from pickled.planning import clear_meal, finish_draft, meal_plan_for, plan_summary
from pickled.stores import Store
from pickled.taste import Author, add_taste_note, set_household


def draft(sessions, fake, prices, *, now=NOW, checkpointer=None):
    """Run the draft job for the week of SATURDAY with `fake` as the draft model."""
    model = make_chat_model(Role.DRAFT, sessions=sessions, build=lambda name, settings: fake)
    checkpointer = checkpointer or InMemorySaver()
    asyncio.run(
        draft_meal_plan_now(
            SATURDAY,
            sessions=sessions,
            model=model,
            checkpointer=checkpointer,
            prices=lambda session, meal_plan: prices,
            clock=lambda: now,
        )
    )
    return checkpointer


def saved_recipe_id(messages) -> int:
    return int(re.search(r"Saved Recipe (\d+)", messages[-1].content)[1])


def test_the_agent_drafts_a_whole_meal_plan_through_its_tools(db_session, sessions):
    set_household(db_session, people=2)
    kipfilet = ingredient(db_session, "kipfilet", Aisle.VLEES_VIS_VEGA, keeps_days=2)
    ingredient(db_session, "rijst", Aisle.VOORRAAD, keeps_days=365)
    ingredient(db_session, "prei", Aisle.GROENTE_FRUIT, keeps_days=7, grams_per_piece=200)
    kip = recipe(db_session, "Kip met rijst", ("kipfilet", 300, "g"), ("rijst", 150, "g"))
    deal(db_session, Store.AH, kipfilet, "2e halve prijs")
    deal(db_session, Store.JUMBO, kipfilet, "25% korting")
    prices = FakePrices().set("kipfilet", Store.AH, 499, "300 g").set("prei", Store.AH, 99, "1 st")
    fake = FakeChatModel(
        replies=[
            tool_calls(("search_recipes", {"query": "kip"})),
            tool_calls(
                (
                    "save_recipe",
                    {
                        "title": "Linzensoep met prei",
                        "servings": 2,
                        "steps": "1. Fruit de prei.\n2. Kook de linzen.",
                        "tags": ["vegetarisch", "soep"],
                        "nutrition": {"kcal": 450, "protein_g": 25, "carbs_g": 60, "fat_g": 8},
                        "lines": [
                            {
                                "ingredient": "linzen",
                                "quantity": 200,
                                "unit": "g",
                                "aisle": "voorraad",
                                "keeps_days": 365,
                            },
                            {"ingredient": "prei", "quantity": 1, "unit": "piece"},
                        ],
                    },
                )
            ),
            lambda messages: tool_calls(
                ("set_meal", {"date": str(WEEK[0]), "recipe_id": kip.id, "servings": 2}),
                (
                    "set_meal",
                    {"date": str(WEEK[2]), "recipe_id": saved_recipe_id(messages), "servings": 2},
                ),
            ),
            tool_calls(
                ("set_leftovers", {"date": str(WEEK[1]), "of_date": str(WEEK[0])}),
                *(("clear_meal", {"date": str(day)}) for day in WEEK[3:]),
            ),
            tool_calls(("set_store", {"store": "ah"})),
            tool_calls(("finish_draft", {"summary": "Deze week kip met rijst en linzensoep."})),
        ]
    )

    checkpointer = draft(sessions, fake, prices)

    db_session.expire_all()
    meal_plan = meal_plan_for(db_session, SATURDAY)
    summary = plan_summary(db_session, meal_plan, prices=prices)
    assert summary.drafted
    assert summary.store == Store.AH
    assert [(day.kind, day.title) for day in summary.days] == [
        ("recipe", "Kip met rijst"),
        ("leftovers", "Kip met rijst"),
        ("recipe", "Linzensoep met prei"),
        *[("empty", None)] * 4,
    ]
    messages = asyncio.run(conversation(checkpointer, meal_plan.id))
    assert [message.content for message in messages] == ["Deze week kip met rijst en linzensoep."]
    calls = db_session.scalars(select(LlmCall)).all()
    assert [(call.job, call.meal_plan_id) for call in calls] == [
        ("draft_meal_plan", meal_plan.id)
    ] * 6


def test_a_draft_that_hits_the_call_limit_stays_partial(db_session, sessions):
    set_household(db_session, people=2)
    prices = with_deals_at_both_stores(db_session)
    fake = FakeChatModel(
        replies=[tool_calls(("get_plan", {})) for _ in range(DRAFT_CALL_LIMIT)]
        + [reply("Nooit gevraagd.")]
    )

    draft(sessions, fake, prices)

    assert len(fake.sent) == DRAFT_CALL_LIMIT
    db_session.expire_all()
    summary = plan_summary(db_session, meal_plan_for(db_session, SATURDAY), prices=prices)
    assert not summary.drafted


def with_deals_at_both_stores(session) -> FakePrices:
    kipfilet = ingredient(session, "kipfilet", Aisle.VLEES_VIS_VEGA, keeps_days=2)
    deal(session, Store.AH, kipfilet, "2e halve prijs")
    deal(session, Store.JUMBO, kipfilet, "25% korting")
    return FakePrices().set("kipfilet", Store.AH, 499, "300 g")


def last_tool_result(fake, call: int) -> ToolMessage:
    """The tool result the model was sent on its `call`th call (from 0)."""
    message = fake.sent[call][-1]
    assert isinstance(message, ToolMessage)
    return message


def test_a_tool_refuses_a_day_that_has_passed_and_the_agent_carries_on(db_session, sessions):
    set_household(db_session, people=2)
    prices = with_deals_at_both_stores(db_session)
    kip = recipe(db_session, "Kip met rijst", ("kipfilet", 300, "g"))
    monday = datetime(2026, 10, 19, 10, 0, tzinfo=AMSTERDAM)
    fake = FakeChatModel(
        replies=[
            tool_calls(("set_meal", {"date": str(WEEK[0]), "recipe_id": kip.id, "servings": 2})),
            tool_calls(("set_meal", {"date": str(WEEK[2]), "recipe_id": kip.id, "servings": 2})),
            reply("Ik heb maandag ingepland."),
        ]
    )

    draft(sessions, fake, prices, now=monday)

    refused = last_tool_result(fake, 1)
    assert refused.status == "error"
    assert "has passed" in refused.content
    db_session.expire_all()
    summary = plan_summary(db_session, meal_plan_for(db_session, SATURDAY), prices=prices)
    assert [day.kind for day in summary.days[:3]] == ["unfilled", "unfilled", "recipe"]


def test_the_agent_cant_rewrite_a_taste_note_the_household_wrote(db_session, sessions):
    set_household(db_session, people=2)
    prices = with_deals_at_both_stores(db_session)
    note = add_taste_note(db_session, "Geen spruitjes", Author.USER, now=NOW)
    fake = FakeChatModel(
        replies=[
            tool_calls(("update_taste_note", {"note_id": note.id, "text": "Wel spruitjes"})),
            reply("Zal ik je notitie over spruitjes aanpassen?"),
        ]
    )

    draft(sessions, fake, prices)

    refused = last_tool_result(fake, 1)
    assert refused.status == "error"
    assert "suggest the change in chat" in refused.content
    db_session.expire_all()
    assert db_session.get(type(note), note.id).text == "Geen spruitjes"


def test_finishing_a_draft_with_days_unfilled_is_refused_and_the_draft_goes_on(
    db_session, sessions
):
    set_household(db_session, people=2)
    prices = with_deals_at_both_stores(db_session)
    fake = FakeChatModel(
        replies=[
            tool_calls(("finish_draft", {"summary": "Klaar!"})),
            reply("Ik ben nog niet klaar."),
        ]
    )

    checkpointer = draft(sessions, fake, prices)

    assert "Fill these days" in last_tool_result(fake, 1).content
    meal_plan = meal_plan_for(db_session, SATURDAY)
    messages = asyncio.run(conversation(checkpointer, meal_plan.id))
    assert [message.content for message in messages] == ["Ik ben nog niet klaar."]


def test_a_draft_waits_for_a_store_whose_deals_are_missing(db_session, sessions):
    set_household(db_session, people=2)
    deal(db_session, Store.AH, ingredient(db_session, "kipfilet"), "2e halve prijs")
    fake = FakeChatModel(replies=[])

    with pytest.raises(MissingDeals) as missing:
        draft(sessions, fake, FakePrices())

    assert missing.value.retry_at == datetime(2026, 10, 15, 19, 0, tzinfo=AMSTERDAM)
    assert meal_plan_for(db_session, SATURDAY) is None


def test_a_store_still_missing_deals_waits_no_later_than_friday_noon(db_session, sessions):
    set_household(db_session, people=2)
    friday_morning = datetime(2026, 10, 16, 11, 30, tzinfo=AMSTERDAM)

    with pytest.raises(MissingDeals) as missing:
        draft(sessions, FakeChatModel(replies=[]), FakePrices(), now=friday_morning)

    assert missing.value.retry_at == datetime(2026, 10, 16, 12, 0, tzinfo=AMSTERDAM)


def test_after_friday_noon_the_draft_goes_ahead_with_the_deals_there_are(db_session, sessions):
    set_household(db_session, people=2)
    friday_noon = datetime(2026, 10, 16, 12, 0, tzinfo=AMSTERDAM)
    fake = FakeChatModel(replies=[reply("Er zijn deze week geen aanbiedingen bekend.")])

    draft(sessions, fake, FakePrices(), now=friday_noon)

    assert len(fake.sent) == 1
    assert meal_plan_for(db_session, SATURDAY) is not None


def test_a_week_whose_draft_is_finished_is_left_alone(db_session, sessions):
    meal_plan = plan(db_session)
    for day in WEEK:
        clear_meal(db_session, meal_plan, day, today=TODAY, prices=FakePrices())
    finish_draft(db_session, meal_plan, now=NOW, prices=FakePrices())
    fake = FakeChatModel(replies=[])

    draft(sessions, fake, FakePrices())

    assert fake.sent == []


def test_a_draft_that_failed_part_way_resumes_where_it_stopped(db_session, sessions):
    set_household(db_session, people=2)
    prices = with_deals_at_both_stores(db_session)
    checkpointer = InMemorySaver()
    failing = FakeChatModel(replies=[tool_calls(("get_plan", {}))])  # then has no replies left

    with pytest.raises(AssertionError):
        draft(sessions, failing, prices, checkpointer=checkpointer)
    resumed = FakeChatModel(replies=[reply("Verder.")])
    draft(sessions, resumed, prices, checkpointer=checkpointer)

    [sent] = resumed.sent
    assert isinstance(sent[-1], ToolMessage) and sent[-1].name == "get_plan"
