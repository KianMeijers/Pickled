"""Writing the Household, the Taste Profile's notes and the Food Goals, with their rules."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from pickled.taste.models import Author, FoodGoal, FoodGoalKind, Household, TasteNote

MAX_NOTE_LENGTH = 200
# A Taste Profile stays a few short notes: past this, similar notes are merged instead.
MAX_ACTIVE_NOTES = 30


class TasteRefused(Exception):
    """A change the rules don't allow; the message says why, for the agent to read."""


def household(session: Session) -> Household | None:
    """The Household, or None before onboarding has set it."""
    return session.scalars(select(Household)).first()


def set_household(session: Session, *, people: int, name: str | None = None) -> Household:
    """Set the number of people the Household cooks for, and its optional name."""
    if people < 1:
        raise TasteRefused("A Household cooks for at least one person.")
    found = household(session)
    if found is None:
        found = Household(people=people)
        session.add(found)
    found.people, found.name = people, name
    session.flush()
    return found


def active_taste_notes(session: Session) -> list[TasteNote]:
    """The Taste notes in use, oldest first."""
    return list(
        session.scalars(
            select(TasteNote)
            .where(TasteNote.archived_at.is_(None))
            .order_by(TasteNote.created_at, TasteNote.id)
        )
    )


def add_taste_note(session: Session, text: str, author: Author, *, now: datetime) -> TasteNote:
    _check_text(text)
    if len(active_taste_notes(session)) >= MAX_ACTIVE_NOTES:
        raise TasteRefused(
            f"The Taste Profile already has {MAX_ACTIVE_NOTES} notes: merge this into a similar "
            "note, or archive one first."
        )
    note = TasteNote(text=text, author=author, created_at=now, updated_at=now)
    session.add(note)
    session.flush()
    return note


def update_taste_note(
    session: Session, note_id: int, text: str, author: Author, *, now: datetime
) -> TasteNote:
    """Rewrite a note. A note the Household rewrites becomes theirs."""
    _check_text(text)
    note = _editable(session, note_id, author)
    note.text, note.author, note.updated_at = text, author, now
    session.flush()
    return note


def archive_taste_note(session: Session, note_id: int, author: Author, *, now: datetime) -> None:
    _editable(session, note_id, author).archived_at = now
    session.flush()


def active_food_goals(session: Session) -> list[FoodGoal]:
    return list(
        session.scalars(
            select(FoodGoal).where(FoodGoal.active).order_by(FoodGoal.kind, FoodGoal.id)
        )
    )


def set_food_goal(
    session: Session,
    kind: FoodGoalKind,
    *,
    min: Decimal | int | None = None,
    max: Decimal | int | None = None,
    text: str | None = None,
    now: datetime,
) -> FoodGoal:
    """Set a Food Goal, replacing the active one of its kind. `other` goals are added instead,
    since each says something different."""
    if kind == FoodGoalKind.OTHER:
        if not text:
            raise TasteRefused("An 'other' Food Goal needs a text saying what it is.")
    else:
        if min is None and max is None:
            raise TasteRefused(f"A {kind} goal needs a min, a max or both.")
        if min is not None and max is not None and min > max:
            raise TasteRefused(f"A {kind} goal's min is above its max.")
        clear_food_goal(session, kind, now=now)
    goal = FoodGoal(kind=kind, min=min, max=max, text=text, active=True, set_at=now)
    session.add(goal)
    session.flush()
    return goal


def clear_food_goal(session: Session, kind: FoodGoalKind, *, now: datetime) -> None:
    """Stop every active Food Goal of `kind`."""
    session.execute(
        update(FoodGoal).where(FoodGoal.kind == kind, FoodGoal.active).values(active=False)
    )
    session.expire_all()


def _check_text(text: str) -> None:
    if len(text) > MAX_NOTE_LENGTH:
        raise TasteRefused(f"A Taste note is at most {MAX_NOTE_LENGTH} characters.")


def _editable(session: Session, note_id: int, author: Author) -> TasteNote:
    note = session.get(TasteNote, note_id)
    if note is None or note.archived_at is not None:
        raise TasteRefused(f"There is no active Taste note {note_id}.")
    if author == Author.AGENT and note.author == Author.USER:
        raise TasteRefused(
            "The Household wrote this note: suggest the change in chat instead of making it."
        )
    return note
