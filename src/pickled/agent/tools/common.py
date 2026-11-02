"""What every tool shares: refusals the agent can read, logging, and the plan summary."""

import functools
import logging
from collections.abc import Callable

from langchain.tools import ToolRuntime
from langchain_core.tools import BaseTool, ToolException, tool

from pickled.agent.context import PlanContext, Work
from pickled.planning import PlanRefused, PlanSummary, plan_summary
from pickled.taste import TasteRefused

logger = logging.getLogger("pickled.agent.tools")

Runtime = ToolRuntime[PlanContext]

# What the rules refuse comes back to the agent as an error result, for it to fix and carry on.
REFUSALS = (PlanRefused, TasteRefused, ToolException)


def agent_tool(func: Callable[..., str]) -> BaseTool:
    """A tool for the agent. Its docstring is what the agent reads about it.

    A refused change rolls back and comes back to the agent as an error result. Each call is
    logged by name, without its arguments.
    """

    @functools.wraps(func)
    def logged(*args, **kwargs) -> str:
        try:
            result = func(*args, **kwargs)
        except REFUSALS as error:
            logger.info("tool %s: refused", func.__name__)
            raise ToolException(str(error)) from error
        logger.info("tool %s", func.__name__)
        return result

    made = tool(logged)
    made.handle_tool_error = True
    return made


def with_summary(headline: str, summary: PlanSummary) -> str:
    """A write tool's result: what it did, then the plan summary."""
    return f"{headline}\n\n{summary.text()}"


def summarise(headline: str, work: Work) -> str:
    """A write tool's result, for a change that doesn't itself return the plan summary."""
    return with_summary(headline, plan_summary(work.session, work.meal_plan, prices=work.prices))
