"""A whole week end to end, on fake stores and fake models: fetch, tag, draft, accept, chat
edits and the reflection after the week (build step 11)."""

import asyncio
from datetime import date, datetime

import pytest
from fakes import FakeChatModel, reply, tool_call, tool_calls
from planning_helpers import AMSTERDAM, NOW, SATURDAY, WEEK, ingredient, recipe
from sqlalchemy import select
from test_web import Web, chat

from pickled.deals import Channel, Deal, DealRecord, FetchResult
from pickled.ingredients import Aisle
from pickled.jobs.deals import fetch_deals_now, tag_deals_now
from pickled.jobs.draft import draft_meal_plan_now
from pickled.jobs.reflect import reflect_on_week_now
from pickled.llm import LlmCall, Role, make_chat_model
from pickled.planning import meal_plan_for, plan_summary
from pickled.stores import Store
from pickled.taste import Author, active_taste_notes, set_household

# Thursday 15 October: both stores are fetched at 17:00, and the week is drafted at 18:00.
FETCHED_AT = datetime(2026, 10, 15, 17, 0, tzinfo=AMSTERDAM)
# The Saturday after the plan's week.
AFTER_THE_WEEK = datetime(2026, 10, 24, 3, 0, tzinfo=AMSTERDAM)


class FakeSource:
    requests_per_fetch = 1

    def __init__(self, store, title):
        self.store = store
        self.title = title

    def fetch(self, on):
        deal = DealRecord(
            source_id=f"{self.store}-1",
            title=self.title,
            discount_text="25% korting",
            valid_from=date(2026, 10, 12),
            valid_to=date(2026, 10, 18),
            channel=Channel.BOTH,
        )
        return FetchResult(store=self.store, on=on, raw={}, deals=[deal])


def model(role, sessions, fake):
    return make_chat_model(role, sessions=sessions, build=lambda name, settings: fake)


@pytest.fixture
def web(sessions):
    return Web(sessions)


def test_a_week_runs_from_fetching_deals_to_the_reflection_after_it(db_session, sessions, web):
    set_household(db_session, people=2)

    # Thursday 17:00: each store's Deals are fetched, then tagged.
    titles = {Store.AH: "AH Kipfilet 300 g", Store.JUMBO: "Jumbo Kipfilet"}
    for store in Store:
        fetch_deals_now(
            store,
            sessions,
            now=FETCHED_AT,
            source_for=lambda store, client: FakeSource(store, titles[store]),
        )
        deal_id = db_session.scalars(select(Deal.id).where(Deal.store == store)).one()
        tagger = FakeChatModel(
            replies=[
                tool_call(
                    "DealTags",
                    {
                        "deals": [
                            {
                                "deal": deal_id,
                                "non_food": False,
                                "ingredients": [{"name": "kipfilet", "aisle": "vlees_vis_vega"}],
                            }
                        ]
                    },
                )
            ]
        )
        tag_deals_now(
            store, sessions, now=FETCHED_AT, model=model(Role.TAG_DEALS, sessions, tagger)
        )

    # Thursday 18:00: the week is drafted around the kipfilet Deal.
    ingredient(db_session, "linzen", Aisle.VOORRAAD, keeps_days=365)
    kip = recipe(db_session, "Kip met rijst", ("kipfilet", 300, "g"))
    soep = recipe(db_session, "Linzensoep", ("linzen", 200, "g"), tags=["vegetarisch"])
    web.prices.set("kipfilet", Store.AH, 499, "300 g").set("linzen", Store.AH, 129, "500 g")
    drafter = FakeChatModel(
        replies=[
            tool_calls(
                ("set_store", {"store": "ah"}),
                ("set_meal", {"date": str(WEEK[0]), "recipe_id": kip.id, "servings": 2}),
            ),
            # The leftovers in a turn of their own: calls in one turn run in any order.
            tool_calls(
                ("set_leftovers", {"date": str(WEEK[1]), "of_date": str(WEEK[0])}),
                *(("clear_meal", {"date": str(day)}) for day in WEEK[2:]),
            ),
            tool_calls(("finish_draft", {"summary": "Deze week kip met rijst."})),
        ]
    )
    asyncio.run(
        draft_meal_plan_now(
            SATURDAY,
            sessions=sessions,
            model=model(Role.DRAFT, sessions, drafter),
            checkpointer=web.checkpointer,
            prices=lambda session, meal_plan: web.prices,
            clock=lambda: NOW,
        )
    )

    # The Household accepts it, then swaps Tuesday for soup in chat.
    assert web.client.post(f"/plans/{SATURDAY}/accept").status_code == 200
    web.fake.replies = [
        tool_calls(("set_meal", {"date": str(WEEK[3]), "recipe_id": soep.id, "servings": 2})),
        reply("Dinsdag staat er linzensoep op het menu."),
    ]
    chat(web, SATURDAY, "Kan dinsdag soep? En geen koriander meer in de recepten graag.")

    # The Saturday after: the week's Conversation becomes a Taste note.
    reflector = FakeChatModel(
        replies=[tool_call("Reflection", {"notes": [{"text": "Lust geen koriander."}]})]
    )
    meal_plan_id = meal_plan_for(db_session, SATURDAY).id
    asyncio.run(
        reflect_on_week_now(
            meal_plan_id,
            sessions=sessions,
            model=model(Role.REFLECT, sessions, reflector),
            checkpointer=web.checkpointer,
            clock=lambda: AFTER_THE_WEEK,
        )
    )

    db_session.expire_all()
    meal_plan = meal_plan_for(db_session, SATURDAY)
    summary = plan_summary(db_session, meal_plan, prices=web.prices)
    assert summary.status == "accepted"
    assert [day.title for day in summary.days[:4]] == [
        "Kip met rijst",
        "Kip met rijst",
        None,
        "Linzensoep",
    ]
    assert meal_plan.reflected_at == AFTER_THE_WEEK
    assert [(note.text, note.author) for note in active_taste_notes(db_session)] == [
        ("Lust geen koriander.", Author.AGENT)
    ]
    roles = [call.role for call in db_session.scalars(select(LlmCall).order_by(LlmCall.id))]
    assert roles == [Role.TAG_DEALS] * 2 + [Role.DRAFT] * 3 + [Role.CHAT] * 2 + [Role.REFLECT]
