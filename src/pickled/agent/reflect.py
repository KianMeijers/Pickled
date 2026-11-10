"""Reflecting on a week: the reflect model merges anything lasting from a Meal Plan's
Conversation into the Taste notes (spec §6).

It is one structured call, not an agent run: the model answers with the note changes, and code
applies each through the Taste rules as the agent, so it can't touch the plan or a note the
Household wrote.
"""

import logging
from datetime import date, datetime

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from pickled import taste
from pickled.agent.agent import is_note
from pickled.agent.prompt import templates
from pickled.taste import MAX_ACTIVE_NOTES, MAX_NOTE_LENGTH, Author, TasteRefused

logger = logging.getLogger(__name__)

INSTRUCTIONS = f"""\
You are Pickled, the meal planner of one Household in the Netherlands. You keep a Taste Profile:
a few short notes on what the Household likes and dislikes, which you read whenever you plan.

A week has ended. Read its Conversation and keep anything lasting it says about the Household's
taste: likes, dislikes, things they can't eat, how much effort they want to spend cooking.
Leave out what only held for that week ("not fish on Tuesday, we're out").

- Change as little as you can. When nothing lasting was said, answer with no changes.
- When a note on the same subject exists, rewrite that note rather than adding one. Merge two
  of your notes that say much the same, and archive the one you merged away.
- Never change or archive a note the Household wrote. When the Conversation contradicts one,
  leave it: the Household will change it themselves.
- Keep the profile to at most {MAX_ACTIVE_NOTES} notes, each at most {MAX_NOTE_LENGTH}
  characters, written in Dutch.
"""


class NoteChange(BaseModel):
    note: int | None = Field(
        None, description="The number of your note to rewrite, or none for a new note"
    )
    text: str = Field(description="The note, in Dutch")


class Reflection(BaseModel):
    """The changes to the Taste notes that the week's Conversation calls for."""

    notes: list[NoteChange] = Field(default_factory=list)
    archive: list[int] = Field(
        default_factory=list, description="The numbers of your notes that no longer hold"
    )


def reflect_on_conversation(
    session: Session,
    week_start: date,
    messages: list[BaseMessage],
    model: BaseChatModel,
    *,
    now: datetime,
) -> None:
    """Ask `model` what the Conversation `messages` changes in the Taste notes, and apply it.

    A change the Taste rules refuse is skipped and logged; the others still apply. Archiving
    goes first and new notes last, so a merge makes room before a note is added.
    """
    prompt = templates.get_template("reflect.jinja").render(
        week_start=week_start,
        notes=taste.active_taste_notes(session),
        conversation=[(_speaker(message), message.text) for message in messages],
    )
    answer = model.with_structured_output(Reflection).invoke(
        [SystemMessage(content=INSTRUCTIONS), HumanMessage(content=prompt)]
    )
    for note_id in answer.archive:
        _apply(session, taste.archive_taste_note, note_id, Author.AGENT, now=now)
    for change in answer.notes:
        if change.note is not None:
            _apply(
                session, taste.update_taste_note, change.note, change.text, Author.AGENT, now=now
            )
    for change in answer.notes:
        if change.note is None:
            _apply(session, taste.add_taste_note, change.text, Author.AGENT, now=now)


def _apply(session: Session, change, *args, **kwargs) -> None:
    try:
        with session.begin_nested():
            change(session, *args, **kwargs)
    except TasteRefused as refused:
        logger.info("reflect_on_week: a note change was refused: %s", refused)


def _speaker(message: BaseMessage) -> str:
    if isinstance(message, HumanMessage):
        return "Note" if is_note(message) else "Household"
    return "Pickled"
