"""The tools for the Taste Profile and Food Goals. The agent writes as `Author.AGENT`, so the
rules keep it from changing a note the Household wrote. Each returns the plan summary."""

from decimal import Decimal

from pickled import taste
from pickled.agent.tools.common import Runtime, agent_tool, summarise
from pickled.taste import Author, FoodGoalKind


@agent_tool
def add_taste_note(text: str, runtime: Runtime) -> str:
    """Remember a lasting preference of the Household, as a short note in Dutch (at most 200
    characters)."""
    with runtime.context.work() as work:
        note = taste.add_taste_note(work.session, text, Author.AGENT, now=work.now)
        return summarise(f"Added Taste note {note.id}.", work)


@agent_tool
def update_taste_note(note_id: int, text: str, runtime: Runtime) -> str:
    """Rewrite a Taste note you wrote. A note the Household wrote can't be changed: suggest the
    change in chat instead."""
    with runtime.context.work() as work:
        taste.update_taste_note(work.session, note_id, text, Author.AGENT, now=work.now)
        return summarise(f"Rewrote Taste note {note_id}.", work)


@agent_tool
def archive_taste_note(note_id: int, runtime: Runtime) -> str:
    """Stop using a Taste note you wrote that no longer holds."""
    with runtime.context.work() as work:
        taste.archive_taste_note(work.session, note_id, Author.AGENT, now=work.now)
        return summarise(f"Archived Taste note {note_id}.", work)


@agent_tool
def set_food_goal(
    kind: FoodGoalKind,
    runtime: Runtime,
    min: Decimal | None = None,
    max: Decimal | None = None,
    text: str | None = None,
) -> str:
    """Set a Food Goal the Household asks for, replacing the one of its kind. Nutrition goals
    are per person per day; the vegetarian days and the budget are per week, and the budget is
    in euro cents. An `other` goal is a `text` that code doesn't check."""
    with runtime.context.work() as work:
        taste.set_food_goal(work.session, kind, min=min, max=max, text=text, now=work.now)
        return summarise(f"The {kind} goal is set.", work)


@agent_tool
def clear_food_goal(kind: FoodGoalKind, runtime: Runtime) -> str:
    """Stop the Household's Food Goal of `kind`."""
    with runtime.context.work() as work:
        taste.clear_food_goal(work.session, kind, now=work.now)
        return summarise(f"The {kind} goal is cleared.", work)
