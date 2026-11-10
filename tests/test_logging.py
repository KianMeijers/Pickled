"""Logs: one line per tool call with its name, duration and outcome, never its arguments
(spec §9)."""

import logging
import re

import pytest

from pickled.agent.tools.common import agent_tool
from pickled.taste import TasteRefused


@agent_tool
def shout(text: str) -> str:
    """Say `text` louder."""
    if text == "nee":
        raise TasteRefused("Not allowed.")
    if text == "boem":
        raise RuntimeError("broken")
    return text.upper()


def tool_lines(caplog) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.name.endswith("tools")]


def test_a_tool_call_logs_its_name_duration_and_that_it_went_ok_without_its_arguments(caplog):
    caplog.set_level(logging.INFO)

    shout.invoke({"text": "geheim recept"})

    [line] = tool_lines(caplog)
    assert re.fullmatch(r"tool shout: ok in \d+ms", line)
    assert "geheim" not in caplog.text


def test_a_refused_tool_call_logs_that_it_was_refused(caplog):
    caplog.set_level(logging.INFO)

    shout.invoke({"text": "nee"})

    [line] = tool_lines(caplog)
    assert re.fullmatch(r"tool shout: refused in \d+ms", line)


def test_a_failing_tool_call_logs_the_error(caplog):
    caplog.set_level(logging.INFO)

    with pytest.raises(RuntimeError):
        shout.invoke({"text": "boem"})

    [line] = tool_lines(caplog)
    assert re.fullmatch(r"tool shout: error RuntimeError in \d+ms", line)
