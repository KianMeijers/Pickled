"""The `draft_meal_plan(week)` job: the agent drafts a whole Meal Plan through its tools."""

import asyncio
import re
from contextlib import asynccontextmanager
from datetime import datetime

import pytest
from fakes import FakeChatModel, reply, tool_calls
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
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

import pickled.jobs.draft
from pickled.agent import DRAFT_CALL_LIMIT, conversation, make_agent, thread
from pickled.ingredients import Aisle
from pickled.jobs.draft import MissingDeals, draft_meal_plan_now
from pickled.llm import LlmCall, Role, make_chat_model
from pickled.planning import (
    MealPlan,
    accept_meal_plan,
    add_shopping_item,
    clear_meal,
    finish_draft,
    meal_plan_for,
    plan_summary,
    set_meal,
)
from pickled.stores import Store
from pickled.taste import Author, add_taste_note, set_household


def draft(sessions, fake, prices, *, now=NOW, checkpointer=None, **options):
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
            **options,
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

    checkpointer = draft(sessions, fake, prices)

    assert len(fake.sent) == DRAFT_CALL_LIMIT
    db_session.expire_all()
    meal_plan = meal_plan_for(db_session, SATURDAY)
    summary = plan_summary(db_session, meal_plan, prices=prices)
    assert not summary.drafted
    assert asyncio.run(conversation(checkpointer, meal_plan.id)) == []


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


def test_a_week_another_run_drafts_while_this_one_waits_for_the_lock_is_left_alone(
    db_session, sessions, monkeypatch
):
    set_household(db_session, people=2)
    prices = with_deals_at_both_stores(db_session)

    @asynccontextmanager
    async def finished_by_the_other_run(sessions, meal_plan_id):
        with sessions.begin() as session:
            meal_plan = session.get_one(MealPlan, meal_plan_id)
            for day in WEEK:
                clear_meal(session, meal_plan, day, today=TODAY, prices=prices)
            finish_draft(session, meal_plan, now=NOW, prices=prices)
        yield

    monkeypatch.setattr(pickled.jobs.draft, "plan_lock", finished_by_the_other_run)
    fake = FakeChatModel(replies=[])

    draft(sessions, fake, prices)

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


def finished_draft(session, prices):
    """A finished draft of the week of SATURDAY: kip on Saturday, the other days empty, and an
    item of the Household's own on the Shopping List."""
    meal_plan = plan(session)
    kip = recipe(session, "Kip met rijst", ("kipfilet", 300, "g"))
    set_meal(session, meal_plan, WEEK[0], kip, 2, today=TODAY, prices=prices)
    for day in WEEK[1:]:
        clear_meal(session, meal_plan, day, today=TODAY, prices=prices)
    add_shopping_item(session, meal_plan, "wc-papier", prices=prices)
    finish_draft(session, meal_plan, now=NOW, prices=prices)
    return meal_plan


def test_a_redraft_replaces_every_meal_with_the_households_hint(db_session, sessions):
    prices = with_deals_at_both_stores(db_session)
    meal_plan = finished_draft(db_session, prices)
    fake = FakeChatModel(
        replies=[
            tool_calls(("get_plan", {})),
            tool_calls(*(("clear_meal", {"date": str(day)}) for day in WEEK)),
            tool_calls(("finish_draft", {"summary": "Deze week eten we buiten de deur."})),
        ]
    )

    checkpointer = draft(sessions, fake, prices, redraft=True, hint="Meer vis")

    assert "Meer vis" in fake.sent[0][-1].content
    assert last_tool_result(fake, 1).content.count("not filled") == 7
    db_session.expire_all()
    summary = plan_summary(db_session, meal_plan, prices=prices)
    assert summary.drafted
    assert [day.kind for day in summary.days] == ["empty"] * 7
    assert [line.name for line in summary.shopping_list] == ["wc-papier"]
    messages = asyncio.run(conversation(checkpointer, meal_plan.id))
    assert [message.content for message in messages] == [
        "Meer vis",
        "Deze week eten we buiten de deur.",
    ]


def test_an_accepted_plan_is_not_redrafted(db_session, sessions):
    prices = with_deals_at_both_stores(db_session)
    meal_plan = finished_draft(db_session, prices)
    accept_meal_plan(db_session, meal_plan, now=NOW, prices=prices)
    fake = FakeChatModel(replies=[])

    draft(sessions, fake, prices, redraft=True)

    assert fake.sent == []
    db_session.expire_all()
    assert plan_summary(db_session, meal_plan, prices=prices).days[0].kind == "recipe"


def test_a_retried_redraft_carries_on_from_the_first_attempt(db_session, sessions):
    prices = with_deals_at_both_stores(db_session)
    meal_plan = finished_draft(db_session, prices)
    checkpointer = InMemorySaver()
    redraft = {"redraft": True, "hint": "Meer vis", "request_id": "job-1"}
    failing = FakeChatModel(replies=[tool_calls(("get_plan", {}))])  # then has no replies left

    with pytest.raises(AssertionError):
        draft(sessions, failing, prices, checkpointer=checkpointer, **redraft)
    retried = FakeChatModel(replies=[reply("Verder.")])
    draft(sessions, retried, prices, checkpointer=checkpointer, **redraft)

    [sent] = retried.sent
    assert isinstance(sent[-1], ToolMessage) and sent[-1].name == "get_plan"
    messages = asyncio.run(conversation(checkpointer, meal_plan.id))
    assert [message.content for message in messages].count("Meer vis") == 1


def test_a_redraft_answers_the_tool_calls_a_stopped_run_left_open(db_session, sessions):
    prices = with_deals_at_both_stores(db_session)
    meal_plan = finished_draft(db_session, prices)
    checkpointer = InMemorySaver()
    stopped = make_agent(FakeChatModel(replies=[]), call_limit=1, checkpointer=checkpointer)
    asyncio.run(
        stopped.aupdate_state(
            thread(meal_plan.id),
            {"messages": [HumanMessage("Hallo?"), tool_calls(("get_plan", {}))]},
            as_node="model",
        )
    )
    fake = FakeChatModel(replies=[reply("Opnieuw begonnen.")])

    draft(sessions, fake, prices, checkpointer=checkpointer, redraft=True)

    [sent] = fake.sent
    calls = {
        call["id"]
        for message in sent
        if isinstance(message, AIMessage)
        for call in message.tool_calls
    }
    answered = {message.tool_call_id for message in sent if isinstance(message, ToolMessage)}
    assert calls and calls <= answered
