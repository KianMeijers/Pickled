"""The one `create_agent` agent that drafts and chats (ADR 0004, ADR 0007).

A draft is the first turn of the Meal Plan's Conversation, so both run on the same thread,
`meal-plan-{id}`, kept by the LangGraph checkpointer.
"""

from datetime import date
from uuid import uuid4

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentState,
    ModelCallLimitMiddleware,
    ModelRequest,
    before_model,
    dynamic_prompt,
    hook_config,
)
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from langgraph.types import Checkpointer

from pickled.agent.context import PlanContext
from pickled.agent.prompt import system_prompt, templates
from pickled.agent.tools import TOOLS
from pickled.planning import MealPlan
from pickled.stores import AMSTERDAM

DRAFT_CALL_LIMIT = 40
CHAT_CALL_LIMIT = 15

# The request that starts a draft is the Conversation's first turn, but not the Household's.
DRAFT_REQUEST = "draft-request"
# Where a run hit its call limit: kept on the thread for the agent, hidden from the Household.
CALL_LIMIT = "call-limit"
# A note of a change the Household made outside the chat, such as leaving a day empty.
NOTE = "note"


def make_agent(model: BaseChatModel, *, call_limit: int, checkpointer: Checkpointer):
    """The agent, allowed `call_limit` model calls per run: `DRAFT_CALL_LIMIT` for a draft,
    `CHAT_CALL_LIMIT` for a chat turn. Past the limit the run ends where it is."""
    return create_agent(
        model,
        tools=TOOLS,
        middleware=[
            end_after_finish_draft,
            plan_prompt,
            AnthropicPromptCachingMiddleware(),
            CallLimit(run_limit=call_limit),
        ],
        context_schema=PlanContext,
        checkpointer=checkpointer,
    )


def thread(meal_plan_id: int) -> RunnableConfig:
    """The run config for the Conversation of Meal Plan `meal_plan_id`."""
    return {"configurable": {"thread_id": f"meal-plan-{meal_plan_id}"}}


def draft_request(
    week: list[date], hint: str | None = None, *, key: str | None = None
) -> HumanMessage:
    """The message that asks the agent to draft the Meal Plan for `week`. A `key` gives it the
    same id each time, so a retried job can find its own request on the thread."""
    text = templates.get_template("draft.jinja").render(week=week, hint=hint)
    return HumanMessage(content=text, id=f"{DRAFT_REQUEST}-{key or uuid4()}")


async def add_note(agent, meal_plan_id: int, text: str) -> None:
    """Add a note to a Meal Plan's Conversation without a run: the agent reads it on its next
    turn, and the Household sees it as a note. `agent` is any agent `make_agent` made."""
    config = thread(meal_plan_id)
    state = await agent.aget_state(config)
    note = HumanMessage(content=text, id=f"{NOTE}-{uuid4()}")
    # Added as if the model had just answered, so the thread ends here rather than waiting
    # for a run to carry on from the note.
    await agent.aupdate_state(
        config,
        {"messages": [*unanswered_calls(state.values.get("messages", [])), note]},
        as_node=f"{CallLimit.__name__}.after_model",
    )


def unanswered_calls(messages: list[BaseMessage]) -> list[ToolMessage]:
    """An error result for each tool call a stopped run left without one, to add before any
    new message: a model call refuses a history with a tool call that has no result."""
    last_call = next(
        (message for message in reversed(messages) if isinstance(message, AIMessage)), None
    )
    if last_call is None:
        return []
    answered = {
        message.tool_call_id
        for message in messages[messages.index(last_call) + 1 :]
        if isinstance(message, ToolMessage)
    }
    return [
        ToolMessage(
            content="Not run: the run stopped before this call.",
            tool_call_id=call["id"],
            name=call["name"],
            status="error",
        )
        for call in last_call.tool_calls
        if call["id"] not in answered
    ]


def is_note(message: BaseMessage) -> bool:
    return (message.id or "").startswith(NOTE)


async def conversation(checkpointer: Checkpointer, meal_plan_id: int) -> list[BaseMessage]:
    """The messages of a Meal Plan's Conversation the Household reads: theirs and the agent's
    replies, without draft requests or tool steps."""
    saved = await checkpointer.aget_tuple(thread(meal_plan_id))
    if saved is None:
        return []
    return [
        message
        for message in saved.checkpoint["channel_values"].get("messages", [])
        if _shown(message)
    ]


@dynamic_prompt
def plan_prompt(request: ModelRequest) -> str:
    context: PlanContext = request.runtime.context
    with context.sessions() as session:
        return system_prompt(
            session,
            session.get_one(MealPlan, context.meal_plan_id),
            today=context.clock().astimezone(AMSTERDAM).date(),
            facts=context.week_facts,
        )


@before_model(can_jump_to=["end"])
def end_after_finish_draft(state: AgentState, runtime: Runtime) -> dict | None:
    """End the run once `finish_draft` succeeds, with its summary as the agent's reply."""
    messages = state["messages"]
    last_call = next(
        (message for message in reversed(messages) if isinstance(message, AIMessage)), None
    )
    if last_call is None:
        return None
    finished = {
        message.tool_call_id
        for message in messages[messages.index(last_call) + 1 :]
        if isinstance(message, ToolMessage)
        and message.name == "finish_draft"
        and message.status != "error"
    }
    for call in last_call.tool_calls:
        if call["id"] in finished:
            return {"jump_to": "end", "messages": [AIMessage(content=call["args"]["summary"])]}
    return None


class CallLimit(ModelCallLimitMiddleware):
    """Ends the run at the call limit, with its English note marked as not for the Household."""

    @hook_config(can_jump_to=["end"])
    def before_model(self, state, runtime):
        update = super().before_model(state, runtime)
        for message in (update or {}).get("messages", []):
            message.id = f"{CALL_LIMIT}-{uuid4()}"
        return update


def _shown(message: BaseMessage) -> bool:
    if isinstance(message, HumanMessage):
        return not (message.id or "").startswith(DRAFT_REQUEST)
    return (
        isinstance(message, AIMessage)
        and not (message.id or "").startswith(CALL_LIMIT)
        and not message.tool_calls
        and bool(message.text)
    )
