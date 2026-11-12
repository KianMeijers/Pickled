"""The agent: one `create_agent` loop for drafts and chat, its prompts and tools (ADR 0007)."""

from pickled.agent.agent import (
    CHAT_CALL_LIMIT,
    DRAFT_CALL_LIMIT,
    add_note,
    conversation,
    draft_request,
    is_note,
    make_agent,
    thread,
    unanswered_calls,
)
from pickled.agent.context import PlanContext
from pickled.agent.prompt import system_prompt
from pickled.agent.reflect import reflect_on_conversation

__all__ = [
    "CHAT_CALL_LIMIT",
    "DRAFT_CALL_LIMIT",
    "PlanContext",
    "add_note",
    "conversation",
    "draft_request",
    "is_note",
    "make_agent",
    "reflect_on_conversation",
    "system_prompt",
    "thread",
    "unanswered_calls",
]
