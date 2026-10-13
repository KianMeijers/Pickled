"""A fake chat model, so no test calls a real one."""

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field


def usage(input_tokens=100, output_tokens=20, cache_read=0, cache_creation=0) -> dict:
    """`usage_metadata` as ChatAnthropic reports it: `input_tokens` includes cached tokens."""
    return {
        "input_tokens": input_tokens + cache_read + cache_creation,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + cache_read + cache_creation + output_tokens,
        "input_token_details": {"cache_read": cache_read, "cache_creation": cache_creation},
    }


def tool_call(name: str, args: dict, **usage_counts) -> AIMessage:
    """A reply that calls tool `name`, which is how a structured output comes back."""
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": f"call_{name}"}],
        usage_metadata=usage(**usage_counts),
    )


class FakeChatModel(BaseChatModel):
    """Answers each call with the next of `replies`, and keeps the messages it was sent."""

    replies: list[AIMessage]
    sent: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.sent.append(list(messages))
        if not self.replies:
            raise AssertionError("FakeChatModel has no replies left")
        return ChatResult(generations=[ChatGeneration(message=self.replies.pop(0))])

    def bind_tools(self, tools, **kwargs: Any):
        return self
