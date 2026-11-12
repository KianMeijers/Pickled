"""`reflect_on_week(meal_plan)`: after a plan's Friday, the reflect model merges anything lasting
from the week's Conversation into the Taste notes (spec §6)."""

import asyncio
from datetime import date, datetime
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from fakes import FakeChatModel, tool_call
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from planning_helpers import AMSTERDAM, NOW, plan

import pickled.jobs.reflect
from pickled.agent import make_agent, thread
from pickled.jobs import app
from pickled.jobs.reflect import reflect_on_week, reflect_on_week_now
from pickled.llm import Role, make_chat_model
from pickled.planning import weeks_to_reflect_on
from pickled.taste import MAX_ACTIVE_NOTES, Author, active_taste_notes, add_taste_note

# The Saturday after the plan's week, from 17 to 23 October.
AFTER_THE_WEEK = datetime(2026, 10, 24, 3, 0, tzinfo=AMSTERDAM)


def said(checkpointer, meal_plan_id, *messages):
    """Put `messages` on the plan's Conversation, as if they had been said in chat."""
    agent = make_agent(FakeChatModel(replies=[]), call_limit=1, checkpointer=checkpointer)
    asyncio.run(
        agent.aupdate_state(
            thread(meal_plan_id), {"messages": list(messages)}, as_node="CallLimit.after_model"
        )
    )


def changes(*notes, archive=()):
    """The reflect model's answer: each note is (id of a note to rewrite or None, text)."""
    return tool_call(
        "Reflection",
        {
            "notes": [{"note": note, "text": text} for note, text in notes],
            "archive": list(archive),
        },
    )


def reflect(sessions, meal_plan_id, fake, checkpointer, *, now=AFTER_THE_WEEK):
    model = make_chat_model(Role.REFLECT, sessions=sessions, build=lambda name, settings: fake)
    asyncio.run(
        reflect_on_week_now(
            meal_plan_id,
            sessions=sessions,
            model=model,
            checkpointer=checkpointer,
            clock=lambda: now,
        )
    )


def test_a_lasting_preference_from_the_conversation_becomes_an_agent_taste_note(
    db_session, sessions
):
    meal_plan = plan(db_session)
    checkpointer = InMemorySaver()
    said(
        checkpointer,
        meal_plan.id,
        HumanMessage(content="Geen koriander meer alsjeblieft, daar kan ik niet tegen."),
        AIMessage(content="Komt goed, ik laat koriander weg."),
    )
    fake = FakeChatModel(replies=[changes((None, "Lust geen koriander."))])

    reflect(sessions, meal_plan.id, fake, checkpointer)

    [note] = active_taste_notes(db_session)
    assert (note.text, note.author) == ("Lust geen koriander.", Author.AGENT)
    [sent] = fake.sent
    assert "Geen koriander meer" in sent[-1].content


def test_a_similar_agent_note_is_rewritten_and_the_one_merged_into_it_archived(
    db_session, sessions
):
    meal_plan = plan(db_session)
    spicy = add_taste_note(db_session, "Houdt van pittig.", Author.AGENT, now=NOW)
    chili = add_taste_note(db_session, "Lust chili.", Author.AGENT, now=NOW)
    checkpointer = InMemorySaver()
    said(checkpointer, meal_plan.id, HumanMessage(content="Mag nog wel wat pittiger hoor!"))
    fake = FakeChatModel(
        replies=[changes((spicy.id, "Houdt van flink pittig, met chili."), archive=[chili.id])]
    )

    reflect(sessions, meal_plan.id, fake, checkpointer)

    db_session.expire_all()
    assert [note.text for note in active_taste_notes(db_session)] == [
        "Houdt van flink pittig, met chili."
    ]


def test_a_note_the_household_wrote_is_never_rewritten_but_the_other_changes_still_apply(
    db_session, sessions
):
    meal_plan = plan(db_session)
    theirs = add_taste_note(db_session, "Geen vis.", Author.USER, now=NOW)
    checkpointer = InMemorySaver()
    said(checkpointer, meal_plan.id, HumanMessage(content="Zalm was eigenlijk best lekker."))
    fake = FakeChatModel(
        replies=[
            changes(
                (theirs.id, "Lust zalm, maar verder geen vis."),
                (None, "Vindt zalm lekker."),
                archive=[theirs.id],
            )
        ]
    )

    reflect(sessions, meal_plan.id, fake, checkpointer)

    db_session.expire_all()
    assert [(note.text, note.author) for note in active_taste_notes(db_session)] == [
        ("Geen vis.", Author.USER),
        ("Vindt zalm lekker.", Author.AGENT),
    ]


def test_reflection_adds_no_note_past_the_profiles_thirty(db_session, sessions):
    meal_plan = plan(db_session)
    for number in range(MAX_ACTIVE_NOTES):
        add_taste_note(db_session, f"Notitie {number}.", Author.AGENT, now=NOW)
    checkpointer = InMemorySaver()
    said(checkpointer, meal_plan.id, HumanMessage(content="We houden van stamppot."))
    fake = FakeChatModel(replies=[changes((None, "Houdt van stamppot."))])

    reflect(sessions, meal_plan.id, fake, checkpointer)

    notes = active_taste_notes(db_session)
    assert len(notes) == MAX_ACTIVE_NOTES
    assert "Houdt van stamppot." not in [note.text for note in notes]


def test_a_week_is_reflected_on_once(db_session, sessions):
    meal_plan = plan(db_session)
    checkpointer = InMemorySaver()
    said(checkpointer, meal_plan.id, HumanMessage(content="Geen spruitjes meer."))
    fake = FakeChatModel(replies=[changes((None, "Lust geen spruitjes."))])

    reflect(sessions, meal_plan.id, fake, checkpointer)
    reflect(sessions, meal_plan.id, fake, checkpointer)

    assert len(fake.sent) == 1
    assert len(active_taste_notes(db_session)) == 1


def test_a_week_the_household_said_nothing_in_is_not_sent_to_the_model(db_session, sessions):
    meal_plan = plan(db_session)
    checkpointer = InMemorySaver()
    said(checkpointer, meal_plan.id, AIMessage(content="Hier is het plan voor deze week."))
    fake = FakeChatModel(replies=[])

    reflect(sessions, meal_plan.id, fake, checkpointer)

    assert fake.sent == []


def test_the_reflection_runs_on_saturday_at_three_in_the_morning_amsterdam_time():
    [task] = [
        task
        for (name, _), task in app.periodic_registry.periodic_tasks.items()
        if name == reflect_on_week.name
    ]
    friday = datetime(2026, 10, 23, 12, 0, tzinfo=AMSTERDAM)

    timestamp = task.croniter.get_next(ret_type=float, start_time=friday.timestamp())

    assert datetime.fromtimestamp(timestamp, AMSTERDAM) == AFTER_THE_WEEK


def test_the_weeks_to_reflect_on_are_those_ended_and_not_yet_reflected_on(db_session):
    ended = plan(db_session, week_start=date(2026, 10, 10))
    done = plan(db_session, week_start=date(2026, 10, 3))
    done.reflected_at = NOW
    plan(db_session, week_start=date(2026, 10, 17))  # ends on Friday 23 October

    assert weeks_to_reflect_on(db_session, today=date(2026, 10, 23)) == [ended.id]


@pytest.fixture
def reflected(monkeypatch):
    plans = []

    async def record(meal_plan_id, **options):
        plans.append(meal_plan_id)

    monkeypatch.setattr(pickled.jobs.reflect, "reflect_with_the_app", record)
    return plans


def test_the_job_reflects_on_the_plan_it_is_given(reflected):
    asyncio.run(reflect_on_week(meal_plan=7))

    assert reflected == [7]


def test_a_reflection_is_not_retried_once_runware_says_the_credit_has_run_out():
    request = httpx2.Request("POST", "https://api.runware.ai/v1/messages")
    no_credit = anthropic.APIStatusError(
        "Insufficient credit", response=httpx2.Response(402, request=request), body=None
    )

    decision = reflect_on_week.retry_strategy.get_retry_decision(
        exception=no_credit, job=SimpleNamespace(attempts=0)
    )

    assert decision is None
