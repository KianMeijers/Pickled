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
            ModelCallLimitMiddleware(run_limit=call_limit),
        ],
        context_schema=PlanContext,
        checkpointer=checkpointer,
    )


def thread(meal_plan_id: int) -> RunnableConfig:
    """The run config for the Conversation of Meal Plan `meal_plan_id`."""
    return {"configurable": {"thread_id": f"meal-plan-{meal_plan_id}"}}


def draft_request(week: list[date], hint: str | None = None) -> HumanMessage:
    """The message that asks the agent to draft the Meal Plan for `week`."""
    text = templates.get_template("draft.jinja").render(week=week, hint=hint)
    return HumanMessage(content=text, id=f"{DRAFT_REQUEST}-{uuid4()}")


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
        meal_plan = session.get_one(MealPlan, context.meal_plan_id)
        return system_prompt(session, meal_plan, today=context.clock().astimezone(AMSTERDAM).date())


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


def _shown(message: BaseMessage) -> bool:
    if isinstance(message, HumanMessage):
        return not (message.id or "").startswith(DRAFT_REQUEST)
    return isinstance(message, AIMessage) and not message.tool_calls and bool(message.text)
