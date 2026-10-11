"""Throwaway smoke test of Runware's Anthropic-compatible /v1/messages endpoint.

Run from the repo root (reads RUNWARE_API_KEY from .env, never prints it):
    uv run --with langchain-anthropic python <this file>
"""

import json
import time
import traceback

import anthropic
import httpx
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class S(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    runware_api_key: SecretStr


KEY = S().runware_api_key.get_secret_value()
BASE = "https://api.runware.ai"
MODEL = "anthropic:claude@sonnet-5.5"
results: dict[str, object] = {}


def client(**kw) -> anthropic.Anthropic:
    return anthropic.Anthropic(base_url=BASE, auth_token=KEY, api_key=None, **kw)


def scrub(x):
    s = json.dumps(x, default=str) if not isinstance(x, str) else x
    return s.replace(KEY, "<KEY>")


def check(name):
    def deco(fn):
        print(f"\n=== {name} ===")
        t = time.time()
        try:
            out = fn()
            results[name] = {"ok": True, "out": out}
        except Exception as e:  # noqa: BLE001
            results[name] = {"ok": False, "err": f"{type(e).__name__}: {e}"}
            traceback.print_exc()
        results[name]["secs"] = round(time.time() - t, 1)
        print(scrub(results[name])[:3000])
        return fn

    return deco


WEATHER_TOOL = {
    "name": "get_deal_price",
    "description": "Look up this week's deal price in euros for a product at a Dutch supermarket.",
    "input_schema": {
        "type": "object",
        "properties": {
            "product": {"type": "string"},
            "store": {"type": "string", "enum": ["AH", "Jumbo"]},
        },
        "required": ["product", "store"],
    },
}


@check("raw_http_usage_and_headers")
def _():
    r = httpx.post(
        f"{BASE}/v1/messages",
        headers={
            "Authorization": f"Bearer {KEY}",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={"model": MODEL, "max_tokens": 50, "messages": [{"role": "user", "content": "Say hi"}]},
        timeout=60,
    )
    return {
        "status": r.status_code,
        "headers": {k: v for k, v in r.headers.items() if "auth" not in k.lower()},
        "body": r.json(),
    }


@check("tool_loop_multi_turn")
def _():
    c = client()
    msgs = [
        {
            "role": "user",
            "content": "What does kipfilet cost at AH this week? Use the tool, then answer in one line.",
        }
    ]
    r1 = c.messages.create(model=MODEL, max_tokens=500, tools=[WEATHER_TOOL], messages=msgs)
    tu = next(b for b in r1.content if b.type == "tool_use")
    msgs += [
        {"role": "assistant", "content": r1.content},
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tu.id, "content": "€6.49 per 500g (25% off)"}
            ],
        },
    ]
    r2 = c.messages.create(model=MODEL, max_tokens=500, tools=[WEATHER_TOOL], messages=msgs)
    return {
        "r1_stop": r1.stop_reason,
        "tool_input": tu.input,
        "r2_stop": r2.stop_reason,
        "r2_text": "".join(b.text for b in r2.content if b.type == "text"),
        "r2_model": r2.model,
        "usage": r2.usage.model_dump(),
    }


@check("streaming")
def _():
    events, text = [], ""
    with client().messages.stream(
        model=MODEL, max_tokens=200, messages=[{"role": "user", "content": "Count 1 to 10."}]
    ) as s:
        for ev in s:
            events.append(ev.type)
            if ev.type == "content_block_delta" and getattr(ev.delta, "type", "") == "text_delta":
                text += ev.delta.text
        final = s.get_final_message()
    return {
        "event_types": sorted(set(events)),
        "n_text_deltas": events.count("content_block_delta"),
        "text": text,
        "usage": final.usage.model_dump(),
    }


@check("prompt_caching")
def _():
    big = "Pickled Taste Profile notes. " + ("The household likes spicy food and dislikes coriander. " * 400)
    sys = [{"type": "text", "text": big, "cache_control": {"type": "ephemeral"}}]
    c = client()
    out = []
    for _ in range(2):
        r = c.messages.create(
            model=MODEL, max_tokens=20, system=sys, messages=[{"role": "user", "content": "OK?"}]
        )
        out.append(r.usage.model_dump())
        time.sleep(2)
    return out


@check("model_name_anthropic_style")
def _():
    out = {}
    for m in ["claude-sonnet-5-5", "claude-opus-5-5", "anthropic:claude@opus-5.5"]:
        try:
            r = client().messages.create(
                model=m, max_tokens=10, messages=[{"role": "user", "content": "hi"}]
            )
            out[m] = {"ok": True, "model": r.model}
        except anthropic.APIStatusError as e:
            out[m] = {"ok": False, "status": e.status_code, "body": e.body}
    return out


@check("beta_header_passthrough")
def _():
    c = client(default_headers={"anthropic-beta": "context-management-2025-06-27"})
    r = c.messages.with_raw_response.create(
        model=MODEL,
        max_tokens=20,
        messages=[{"role": "user", "content": "hi"}],
        extra_body={"context_management": {"edits": [{"type": "clear_tool_uses_20250919"}]}},
    )
    m = r.parse()
    return {"status": r.status_code, "context_management": getattr(m, "context_management", None)}


@check("bogus_beta_header")
def _():
    c = client(default_headers={"anthropic-beta": "definitely-not-a-real-beta-2099"})
    try:
        r = c.messages.create(model=MODEL, max_tokens=10, messages=[{"role": "user", "content": "hi"}])
        return {"accepted": True, "model": r.model}
    except anthropic.APIStatusError as e:
        return {"accepted": False, "status": e.status_code, "body": e.body}


@check("error_format")
def _():
    out = {}
    for label, kw in {
        "bad_model": {"model": "anthropic:claude@nope-9", "max_tokens": 10},
        "bad_max_tokens": {"model": MODEL, "max_tokens": -1},
    }.items():
        try:
            client(max_retries=0).messages.create(messages=[{"role": "user", "content": "hi"}], **kw)
            out[label] = "no error"
        except anthropic.APIStatusError as e:
            out[label] = {
                "sdk_class": type(e).__name__,
                "status": e.status_code,
                "body": e.body,
                "retry_after": e.response.headers.get("retry-after"),
            }
    try:
        anthropic.Anthropic(base_url=BASE, auth_token="bogus", max_retries=0).messages.create(
            model=MODEL, max_tokens=10, messages=[{"role": "user", "content": "hi"}]
        )
    except anthropic.APIStatusError as e:
        out["bad_key"] = {"sdk_class": type(e).__name__, "status": e.status_code, "body": e.body}
    return out


@check("langchain_tool_loop")
def _():
    from langchain_anthropic import ChatAnthropic
    from langchain_core.messages import HumanMessage, ToolMessage
    from langchain_core.tools import tool

    @tool
    def get_deal_price(product: str, store: str) -> str:
        """Look up this week's deal price in euros for a product at AH or Jumbo."""
        return "€6.49 per 500g (25% off)"

    llm = ChatAnthropic(
        model=MODEL,
        base_url=BASE,
        api_key=KEY,
        default_headers={"Authorization": f"Bearer {KEY}"},
        max_tokens=500,
    ).bind_tools([get_deal_price])
    msgs = [HumanMessage("What does kipfilet cost at Jumbo this week? Use the tool, one line.")]
    a1 = llm.invoke(msgs)
    msgs.append(a1)
    for tc in a1.tool_calls:
        msgs.append(ToolMessage(get_deal_price.invoke(tc["args"]), tool_call_id=tc["id"]))
    a2 = llm.invoke(msgs)
    chunks = list(llm.stream([HumanMessage("Say three Dutch vegetables.")]))
    return {
        "tool_calls": a1.tool_calls,
        "final": a2.content,
        "usage": a2.usage_metadata,
        "stream_chunks": len(chunks),
    }


print("\n\n##### SUMMARY #####")
print(scrub(results))
