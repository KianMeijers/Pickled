"""The web app: the plan pages, chat, the day buttons, accept, redraft and first run."""

import asyncio
import re
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal

import pytest
from fakes import FakeChatModel, reply, tool_calls
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from planning_helpers import AMSTERDAM, NOW, SATURDAY, WEEK, FakePrices, ingredient, plan, recipe
from sqlalchemy import delete

import pickled.web.chat as chat_module
from pickled.agent import conversation, thread
from pickled.ingredients import Aisle
from pickled.jobs.draft import QUEUEING_LOCK, draft_meal_plan
from pickled.llm import LlmCall, Role, make_chat_model
from pickled.planning import (
    ShoppingListItem,
    clear_meal,
    plan_summary,
    set_leftovers,
    set_meal,
    set_store,
    start_meal_plan,
)
from pickled.planning.locks import DRAFT_LOCKS, LOCK, MEAL_PLAN_LOCKS, UNLOCK
from pickled.stores import Store
from pickled.taste import (
    Author,
    FoodGoalKind,
    active_food_goals,
    active_taste_notes,
    household,
    set_household,
)
from pickled.web import Services, create_app
from pickled.web.chat import chat_agent


class Web:
    """The app on the test database, with a fake chat model and fake prices."""

    def __init__(self, sessions):
        self.fake = FakeChatModel(replies=[])
        self.prices = FakePrices()
        self.checkpointer = InMemorySaver()
        self.now = NOW
        self.services = Services(
            sessions=sessions,
            checkpointer=self.checkpointer,
            # A fresh model per turn, as in the app, sharing the fake's replies and sent lists.
            chat_model=lambda: make_chat_model(
                Role.CHAT, sessions=sessions, build=lambda name, settings: self.fake.model_copy()
            ),
            prices=lambda session, meal_plan: self.prices,
            shown_prices=lambda session, meal_plan: self.prices,
            clock=lambda: self.now,
        )
        self.client = TestClient(create_app(self.services))


@pytest.fixture
def web(sessions):
    return Web(sessions)


def drafted_week(session, prices):
    """The plan for the week of SATURDAY: kip, its leftovers, linzensoep, then empty days."""
    meal_plan = plan(session)
    ingredient(session, "kipfilet", Aisle.VLEES_VIS_VEGA, keeps_days=2)
    ingredient(session, "linzen", Aisle.VOORRAAD, keeps_days=365)
    prices.set("kipfilet", Store.AH, 499, "300 g").set("linzen", Store.AH, 129, "500 g")
    kip = recipe(session, "Kip met rijst", ("kipfilet", 300, "g"))
    soep = recipe(session, "Linzensoep", ("linzen", 200, "g"), tags=["vegetarisch"])
    today = NOW.date()
    set_store(session, meal_plan, Store.AH, today=today, prices=prices)
    set_meal(session, meal_plan, WEEK[0], kip, 2, today=today, prices=prices)
    set_leftovers(session, meal_plan, WEEK[1], WEEK[0], today=today, prices=prices)
    set_meal(session, meal_plan, WEEK[2], soep, 2, today=today, prices=prices)
    for day in WEEK[3:]:
        clear_meal(session, meal_plan, day, today=today, prices=prices)
    session.flush()
    return meal_plan


def test_a_plan_page_shows_its_seven_days_and_shopping_list(db_session, web):
    drafted_week(db_session, web.prices)

    page = web.client.get(f"/plans/{SATURDAY}")

    assert page.status_code == 200
    for day in ["zaterdag 17 okt", "zondag 18 okt", "maandag 19 okt", "vrijdag 23 okt"]:
        assert day in page.text
    assert "Kip met rijst" in page.text
    assert "Restjes van zaterdag" in page.text
    assert "Linzensoep" in page.text
    assert page.text.count("Geen maaltijd") == 4
    assert "Boodschappen" in page.text
    assert "kipfilet" in page.text


THIS_SATURDAY = date(2026, 10, 10)  # the week NOW, Thursday 15 October, falls in


def test_home_shows_this_weeks_plan_and_a_banner_for_next_weeks_draft(db_session, web):
    plan(db_session, week_start=THIS_SATURDAY)
    start_meal_plan(db_session, SATURDAY, now=NOW)

    page = web.client.get("/")

    assert "Week van zaterdag 10 okt" in page.text
    assert "Het plan voor volgende week staat klaar" in page.text
    assert f'href="/plans/{SATURDAY}"' in page.text


def test_home_has_no_banner_while_next_week_has_no_plan(db_session, web):
    plan(db_session, week_start=THIS_SATURDAY)

    page = web.client.get("/")

    assert "Week van zaterdag 10 okt" in page.text
    assert "volgende week staat klaar" not in page.text


def events(stream_text: str) -> list[tuple[str, str]]:
    """The (event, data) pairs of a text/event-stream body."""
    found = []
    for block in stream_text.replace("\r\n", "\n").split("\n\n"):
        name, data = "message", []
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data.append(line[len("data:") :].removeprefix(" "))
        if data or name != "message":
            found.append((name, "\n".join(data)))
    return found


def chat(web, week_start, message: str) -> list[tuple[str, str]]:
    """Post a chat message, then follow its stream to the end, as the browser does."""
    posted = web.client.post(f"/plans/{week_start}/chat", data={"message": message})
    assert posted.status_code == 200, posted.text
    assert message in posted.text
    stream_url = re.search(r'sse-connect="([^"]+)"', posted.text)[1]
    with web.client.stream("GET", stream_url) as streamed:
        assert streamed.headers["content-type"].startswith("text/event-stream")
        return events(streamed.read().decode())


def test_a_chat_turn_changes_a_meal_and_streams_the_reply(db_session, web):
    meal_plan = drafted_week(db_session, web.prices)
    ingredient(db_session, "pasta", Aisle.VOORRAAD, keeps_days=365)
    pasta = recipe(db_session, "Pasta pesto", ("pasta", 250, "g"), tags=["vegetarisch"])
    web.fake.replies = [
        tool_calls(("set_meal", {"date": str(WEEK[3]), "recipe_id": pasta.id, "servings": 2})),
        reply("Ik heb dinsdag pasta pesto ingepland."),
    ]

    streamed = chat(web, SATURDAY, "Wil je dinsdag pasta pesto doen?")

    names = [name for name, _ in streamed]
    assert ("status", "Maaltijd inplannen…") in streamed
    plan_updates = [data for name, data in streamed if name == "plan"]
    assert len(plan_updates) == 1
    assert 'hx-swap-oob="true"' in plan_updates[0]
    assert "Pasta pesto" in plan_updates[0]
    assert "".join(data for name, data in streamed if name == "token") == (
        "Ik heb dinsdag pasta pesto ingepland."
    )
    assert names[-1] == "done"
    db_session.expire_all()
    summary = plan_summary(db_session, meal_plan, prices=web.prices)
    assert summary.days[3].title == "Pasta pesto"
    messages = asyncio.run(conversation(web.checkpointer, meal_plan.id))
    assert [message.text for message in messages] == [
        "Wil je dinsdag pasta pesto doen?",
        "Ik heb dinsdag pasta pesto ingepland.",
    ]


def test_a_finished_chat_stream_doesnt_run_the_turn_again(db_session, web):
    drafted_week(db_session, web.prices)
    web.fake.replies = [reply("Prima.")]
    posted = web.client.post(f"/plans/{SATURDAY}/chat", data={"message": "Dank je"})
    stream_url = re.search(r'sse-connect="([^"]+)"', posted.text)[1]
    web.client.get(stream_url)

    # The browser's EventSource reconnects after a stream ends.
    again = events(web.client.get(stream_url).text)

    assert [name for name, _ in again] == ["done"]
    assert len(web.fake.sent) == 1


def test_a_note_answers_the_tool_calls_a_stopped_run_left_open(db_session, web):
    meal_plan = drafted_week(db_session, web.prices)
    agent = chat_agent(web.services)
    asyncio.run(
        agent.aupdate_state(
            thread(meal_plan.id),
            {"messages": [HumanMessage("Hallo?"), tool_calls(("get_plan", {}))]},
            as_node="model",
        )
    )

    web.client.post(f"/plans/{SATURDAY}/days/{WEEK[2]}/clear")

    messages = asyncio.run(agent.aget_state(thread(meal_plan.id))).values["messages"]
    answered = {message.tool_call_id for message in messages if isinstance(message, ToolMessage)}
    assert {call["id"] for call in messages[1].tool_calls} <= answered


def test_a_turn_whose_stream_never_came_is_dropped(db_session, web, monkeypatch):
    drafted_week(db_session, web.prices)
    monkeypatch.setattr(chat_module, "TURN_EXPIRES", -1)

    web.client.post(f"/plans/{SATURDAY}/chat", data={"message": "Hallo?"})
    web.client.post(f"/plans/{SATURDAY}/chat", data={"message": "Nog een keer?"})

    assert [turn.message for turn in web.client.app.state.turns.values()] == ["Nog een keer?"]


def test_skipping_a_day_clears_it_without_the_model_and_notes_it(db_session, web):
    meal_plan = drafted_week(db_session, web.prices)

    cleared = web.client.post(f"/plans/{SATURDAY}/days/{WEEK[2]}/clear")

    assert cleared.status_code == 200
    assert web.fake.sent == []
    db_session.expire_all()
    assert plan_summary(db_session, meal_plan, prices=web.prices).days[2].kind == "empty"
    messages = asyncio.run(conversation(web.checkpointer, meal_plan.id))
    assert [message.text for message in messages] == ["Maandag 19 okt is leeg gelaten."]
    assert "Maandag 19 okt is leeg gelaten." in web.client.get(f"/plans/{SATURDAY}").text


def test_the_agent_reads_a_skipped_day_in_the_next_chat_turn(db_session, web):
    drafted_week(db_session, web.prices)
    web.client.post(f"/plans/{SATURDAY}/days/{WEEK[2]}/clear")
    web.fake.replies = [reply("Gezien.")]

    chat(web, SATURDAY, "Klopt het plan zo?")

    sent = [message.text for message in web.fake.sent[0]]
    assert sent[-2:] == ["Maandag 19 okt is leeg gelaten.", "Klopt het plan zo?"]


def test_a_day_that_has_passed_cant_be_skipped(db_session, web):
    drafted_week(db_session, web.prices)
    web.now = datetime(2026, 10, 20, 10, 0, tzinfo=AMSTERDAM)

    refused = web.client.post(f"/plans/{SATURDAY}/days/{WEEK[2]}/clear")

    assert refused.status_code == 409
    assert "voorbij" in refused.text


@pytest.mark.parametrize(
    "button, message",
    [
        ("replace", "Kun je maandag 19 okt door iets anders vervangen?"),
        ("leftovers", "Kun je op maandag 19 okt restjes van een eerdere maaltijd eten?"),
    ],
)
def test_a_day_button_asks_the_agent_with_a_templated_message(db_session, web, button, message):
    drafted_week(db_session, web.prices)
    web.fake.replies = [reply("Komt goed.")]

    posted = web.client.post(f"/plans/{SATURDAY}/days/{WEEK[2]}/{button}")
    stream_url = re.search(r'sse-connect="([^"]+)"', posted.text)[1]
    web.client.get(stream_url)

    assert message in posted.text
    assert web.fake.sent[0][-1].text == message


def test_a_finished_plan_can_be_accepted(db_session, web):
    meal_plan = drafted_week(db_session, web.prices)

    accepted = web.client.post(f"/plans/{SATURDAY}/accept")

    assert accepted.status_code == 200
    assert "Geaccepteerd" in accepted.text
    db_session.expire_all()
    assert plan_summary(db_session, meal_plan, prices=web.prices).status == "accepted"


def test_a_plan_with_unfilled_days_cant_be_accepted(db_session, web):
    meal_plan = plan(db_session)

    refused = web.client.post(f"/plans/{SATURDAY}/accept")

    assert refused.status_code == 409
    assert "Vul eerst elke dag" in refused.text
    db_session.expire_all()
    assert plan_summary(db_session, meal_plan, prices=web.prices).status == "draft"


def queued(job_queue) -> list[tuple[str, dict]]:
    return [(job["task_name"], job["args"]) for job in job_queue.jobs.values()]


def test_redrafting_a_draft_queues_the_draft_job_with_the_hint(db_session, web, job_queue):
    drafted_week(db_session, web.prices)

    redrafted = web.client.post(f"/plans/{SATURDAY}/redraft", data={"hint": "Meer vis"})

    assert redrafted.status_code == 200
    [(task, args)] = queued(job_queue)
    assert task == "draft_meal_plan"
    assert args.pop("request_id")
    assert args == {"week": str(SATURDAY), "redraft": True, "hint": "Meer vis"}


def test_an_accepted_plan_cant_be_redrafted(db_session, web, job_queue):
    drafted_week(db_session, web.prices)
    web.client.post(f"/plans/{SATURDAY}/accept")

    refused = web.client.post(f"/plans/{SATURDAY}/redraft", data={"hint": ""})

    assert refused.status_code == 409
    assert queued(job_queue) == []


@contextmanager
def held(test_engine, meal_plan_id, *spaces):
    """The Meal Plan's locks in `spaces`, held on a connection of its own."""
    with test_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as holder:
        for space in spaces:
            holder.execute(LOCK, {"space": space, "id": meal_plan_id})
        try:
            yield
        finally:
            for space in spaces:
                holder.execute(UNLOCK, {"space": space, "id": meal_plan_id})


def held_by_a_draft_job(test_engine, meal_plan_id):
    """The locks a running draft job holds."""
    return held(test_engine, meal_plan_id, DRAFT_LOCKS, MEAL_PLAN_LOCKS)


def held_by_a_chat_turn(test_engine, meal_plan_id):
    """The lock a chat turn holds while the agent replies."""
    return held(test_engine, meal_plan_id, MEAL_PLAN_LOCKS)


def test_chat_is_disabled_while_a_draft_job_holds_the_plan(db_session, web, test_engine):
    meal_plan = drafted_week(db_session, web.prices)

    with held_by_a_draft_job(test_engine, meal_plan.id):
        page = web.client.get(f"/plans/{SATURDAY}")
        posted = web.client.post(f"/plans/{SATURDAY}/chat", data={"message": "Hallo?"})
        cleared = web.client.post(f"/plans/{SATURDAY}/days/{WEEK[2]}/clear")

    assert "Pickled is aan het plannen" in page.text
    assert re.search(r"<textarea[^>]*disabled", page.text)
    assert posted.status_code == 409
    assert cleared.status_code == 409
    assert web.fake.sent == []


def test_a_chat_turn_at_work_isnt_shown_as_a_draft(db_session, web, test_engine):
    meal_plan = drafted_week(db_session, web.prices)

    with held_by_a_chat_turn(test_engine, meal_plan.id):
        page = web.client.get(f"/plans/{SATURDAY}")

    assert "Pickled is aan het plannen" not in page.text
    assert not re.search(r"<textarea[^>]*disabled", page.text)
    # The turn may be changing the Shopping List, so the page's copy can't be ticked.
    assert re.search(r'<input type="checkbox"[^>]*disabled', page.text)


def test_a_queued_thursday_draft_shows_as_drafting(db_session, web):
    set_household(db_session, people=2)
    draft_meal_plan.configure(queueing_lock=QUEUEING_LOCK).defer(timestamp=int(NOW.timestamp()))

    page = web.client.get("/")

    assert "Pickled is aan het plannen" in page.text
    assert "Plan maken" not in page.text


def test_chat_is_disabled_while_a_redraft_is_queued(db_session, web):
    drafted_week(db_session, web.prices)
    web.client.post(f"/plans/{SATURDAY}/redraft", data={"hint": ""})

    page = web.client.get(f"/plans/{SATURDAY}")
    posted = web.client.post(f"/plans/{SATURDAY}/chat", data={"message": "Hallo?"})

    assert "Pickled is aan het plannen" in page.text
    assert posted.status_code == 409


def test_chat_is_open_when_no_draft_job_is_running(db_session, web):
    drafted_week(db_session, web.prices)

    page = web.client.get(f"/plans/{SATURDAY}")

    assert "Pickled is aan het plannen" not in page.text
    assert re.search(r"<textarea", page.text)
    assert not re.search(r"<textarea[^>]*disabled", page.text)


def test_before_onboarding_home_sends_the_household_to_onboarding(web):
    page = web.client.get("/", follow_redirects=False)

    assert page.status_code == 303
    assert page.headers["location"] == "/welkom"
    assert "Met hoeveel personen" in web.client.get("/welkom").text


def test_onboarding_sets_the_household_and_starts_planning(db_session, web, job_queue):
    onboarded = web.client.post(
        "/welkom",
        data={
            "people": "3",
            "budget_euros": "70",
            "vegetarian_days": "2",
            "taste_notes": "Geen spruitjes\n\n  Houdt van pittig eten  \n",
        },
        follow_redirects=False,
    )

    assert onboarded.status_code == 303
    assert onboarded.headers["location"] == "/"
    assert household(db_session).people == 3
    goals = {goal.kind: (goal.min, goal.max) for goal in active_food_goals(db_session)}
    assert goals == {
        FoodGoalKind.BUDGET_CENTS_PER_WEEK: (None, 7000),
        FoodGoalKind.VEGETARIAN_DAYS_PER_WEEK: (2, None),
    }
    notes = [(note.text, note.author) for note in active_taste_notes(db_session)]
    assert notes == [("Geen spruitjes", Author.USER), ("Houdt van pittig eten", Author.USER)]
    assert queued(job_queue) == [("start_planning", {"week": str(SATURDAY)})]
    assert "Pickled is aan het plannen" in web.client.get("/").text


def test_onboarding_sent_again_changes_nothing(db_session, web, job_queue):
    form = {"people": "2", "taste_notes": "Geen spruitjes"}

    web.client.post("/welkom", data=form, follow_redirects=False)
    again = web.client.post("/welkom", data={**form, "people": "4"}, follow_redirects=False)

    assert again.status_code == 303
    assert household(db_session).people == 2
    assert [note.text for note in active_taste_notes(db_session)] == ["Geen spruitjes"]
    assert queued(job_queue) == [("start_planning", {"week": str(SATURDAY)})]


def test_without_a_plan_home_offers_to_draft_next_week(db_session, web, job_queue):
    set_household(db_session, people=2)

    page = web.client.get("/")
    drafted = web.client.post("/plans/draft")

    assert "Plan maken" in page.text
    assert drafted.status_code == 200
    assert queued(job_queue) == [("draft_meal_plan", {"week": str(SATURDAY)})]
    assert "Plan maken" not in web.client.get("/").text


def test_draft_now_is_refused_once_next_week_has_a_plan(db_session, web, job_queue):
    plan(db_session)

    refused = web.client.post("/plans/draft")

    assert refused.status_code == 409
    assert queued(job_queue) == []


def shopping_line(db_session, web, meal_plan, name):
    db_session.expire_all()
    summary = plan_summary(db_session, meal_plan, prices=web.prices)
    return next(line for line in summary.shopping_list if line.name == name)


def test_ticking_a_shopping_list_item_keeps_it_ticked(db_session, web):
    meal_plan = drafted_week(db_session, web.prices)
    kipfilet = shopping_line(db_session, web, meal_plan, "kipfilet")

    ticked = web.client.post(f"/plans/{SATURDAY}/shopping/{kipfilet.id}", data={"checked": "on"})

    assert ticked.status_code == 200
    assert shopping_line(db_session, web, meal_plan, "kipfilet").checked
    web.client.post(f"/plans/{SATURDAY}/shopping/{kipfilet.id}", data={})
    assert not shopping_line(db_session, web, meal_plan, "kipfilet").checked


def test_a_line_the_page_brings_onto_the_shopping_list_can_be_ticked(db_session, web):
    meal_plan = drafted_week(db_session, web.prices)
    # A stored list out of date with the Meals.
    db_session.execute(delete(ShoppingListItem).where(ShoppingListItem.name == "kipfilet"))

    page = web.client.get(f"/plans/{SATURDAY}")
    item_id = re.search(r'shopping/(\d+)"[^>]*>\s*<span>kipfilet', page.text)[1]
    ticked = web.client.post(f"/plans/{SATURDAY}/shopping/{item_id}", data={"checked": "on"})

    assert ticked.status_code == 200
    assert shopping_line(db_session, web, meal_plan, "kipfilet").checked


def test_the_household_adds_its_own_item_to_the_shopping_list(db_session, web):
    meal_plan = drafted_week(db_session, web.prices)

    added = web.client.post(f"/plans/{SATURDAY}/shopping", data={"name": "wc-papier"})

    assert added.status_code == 200
    assert "wc-papier" in added.text
    assert shopping_line(db_session, web, meal_plan, "wc-papier").manual


def test_an_item_of_another_plan_cant_be_ticked(db_session, web):
    meal_plan = drafted_week(db_session, web.prices)
    kipfilet = shopping_line(db_session, web, meal_plan, "kipfilet")
    start_meal_plan(db_session, date(2026, 10, 24), now=NOW)

    refused = web.client.post(f"/plans/2026-10-24/shopping/{kipfilet.id}", data={"checked": "on"})

    assert refused.status_code == 404
    assert not shopping_line(db_session, web, meal_plan, "kipfilet").checked


def test_a_chat_turn_whose_model_fails_says_so_and_frees_the_plan(db_session, web):
    drafted_week(db_session, web.prices)
    web.fake.replies = []  # the fake fails when called with no replies left

    streamed = chat(web, SATURDAY, "Hallo?")

    assert ("error", "Er ging iets mis. Probeer het nog eens.") in streamed
    assert streamed[-1][0] == "done"
    web.fake.replies = [reply("Hallo!")]
    retried = chat(web, SATURDAY, "Hallo?")
    assert "".join(data for name, data in retried if name == "token") == "Hallo!"


def test_every_page_loads_the_status_line(db_session, web):
    drafted_week(db_session, web.prices)

    page = web.client.get(f"/plans/{SATURDAY}")

    assert 'hx-get="/status"' in page.text


def test_the_status_line_lists_its_warnings(db_session, web):
    web.now = datetime(2026, 10, 15, 18, 0, tzinfo=AMSTERDAM)

    fragment = web.client.get("/status")

    assert "Er zijn geen aanbiedingen van Albert Heijn." in fragment.text
    assert "Er zijn geen aanbiedingen van Jumbo." in fragment.text


def spend_the_cap(session):
    session.add(
        LlmCall(
            called_at=NOW,
            role=Role.CHAT,
            model="claude-sonnet-5-5",
            input_tokens=0,
            cache_write_tokens=0,
            cache_read_tokens=0,
            output_tokens=0,
            cost_usd=Decimal("25"),
        )
    )
    session.flush()


def test_chat_shows_a_banner_once_the_spend_cap_is_reached(db_session, web):
    drafted_week(db_session, web.prices)
    before = web.client.get(f"/plans/{SATURDAY}")
    spend_the_cap(db_session)

    after = web.client.get(f"/plans/{SATURDAY}")

    banner = "Het maandbudget voor LLM-kosten is op"
    assert banner not in before.text
    assert banner in after.text
