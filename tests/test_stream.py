"""测试 SSE 流式适配器 — 支持多 stream mode."""

from __future__ import annotations

import os

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agent import build_agent
from src.context import build_context
from src.stream import sse_adapter, sse_events_to_str

needs_deepseek = pytest.mark.skipif(
    not os.environ.get("DEEPSEEK_API_KEY"),
    reason="DEEPSEEK_API_KEY not set",
)


@needs_deepseek
@pytest.mark.asyncio
async def test_sse_adapter_yields_text_and_done():
    """SSE 适配器输出 event=text，最终以 event=done 结束."""
    agent = build_agent()
    ctx = build_context("u1", "conv-sse-x")
    config = {"configurable": {"thread_id": "conv-sse-x"}}

    stream = agent.astream(
        {"messages": [HumanMessage(content="用一句话介绍比特币。")]},
        config=config,
        context=ctx,
        stream_mode=["messages", "updates"],
    )

    events = []
    async for event in sse_adapter(stream):
        events.append(event)

    assert len(events) >= 2
    text_events = [e for e in events if e["event"] == "text"]
    assert len(text_events) > 0
    assert events[-1]["event"] == "done"


@needs_deepseek
@pytest.mark.asyncio
async def test_sse_adapter_text_concatenation():
    """所有 text 块的 content 拼接后构成完整回复."""
    agent = build_agent()
    ctx = build_context("u2", "conv-sse2-x")
    config = {"configurable": {"thread_id": "conv-sse2-x"}}

    stream = agent.astream(
        {"messages": [HumanMessage(content="说：你好。")]},
        config=config,
        context=ctx,
        stream_mode=["messages", "updates"],
    )

    full_text = ""
    async for event in sse_adapter(stream):
        if event["event"] == "text":
            full_text += event["data"]["content"]

    assert len(full_text) > 0
    assert "你好" in full_text


@needs_deepseek
@pytest.mark.asyncio
async def test_sse_events_to_str_format():
    """sse_events_to_str 输出标准 SSE 文本格式."""
    agent = build_agent()
    ctx = build_context("u3", "conv-sse3-x")
    config = {"configurable": {"thread_id": "conv-sse3-x"}}

    stream = agent.astream(
        {"messages": [HumanMessage(content="回复：OK。")]},
        config=config,
        context=ctx,
        stream_mode=["messages", "updates"],
    )

    lines = []
    async for line in sse_events_to_str(sse_adapter(stream)):
        lines.append(line)

    assert len(lines) >= 2
    for line in lines:
        assert line.startswith("event: ")
        assert "\ndata: " in line
    assert "event: done" in lines[-1]


def test_sse_adapter_error_handling():
    """异常时 sse_adapter 输出 event=error."""

    async def faulty_stream():
        yield "messages", (None, {})
        raise RuntimeError("test error")

    async def run():
        events = []
        async for event in sse_adapter(faulty_stream()):
            events.append(event)
        return events

    import asyncio

    events = asyncio.run(run())
    error_events = [e for e in events if e["event"] == "error"]
    assert len(error_events) >= 1


def test_sse_adapter_handles_tool_messages():
    """updates 中的 ToolMessage 输出为 event=tool."""

    async def tool_stream():
        yield ("ns", "updates", {"agent": {"messages": [ToolMessage(content="已查询礼品卡", tool_call_id="call_1")]}})
        if False:
            yield None

    import asyncio
    events = asyncio.run(_collect(tool_stream()))
    tool_events = [e for e in events if e["event"] == "tool"]
    assert len(tool_events) >= 1
    assert tool_events[0]["data"]["content"] == "已查询礼品卡"


def test_sse_adapter_handles_custom_events():
    """custom channel 中的 card 事件直接透传."""

    async def custom_stream():
        yield ("ns", "custom", {"event": "card", "data": {"card": {"balance": 500}}})
        if False:
            yield None

    import asyncio
    events = asyncio.run(_collect(custom_stream()))
    card_events = [e for e in events if e["event"] == "card"]
    assert len(card_events) >= 1
    assert card_events[0]["data"]["card"]["balance"] == 500


def test_sse_adapter_full_pipeline():
    """模拟完整流：messages + tool + card + done."""

    async def full_stream():
        yield ("ns", "updates", {"agent": {"messages": [ToolMessage(content="调用API", tool_call_id="c1")]}})
        yield ("ns", "custom", {"event": "card", "data": {"positions": [{"symbol": "BTC"}]}})
        yield ("ns", "messages", (AIMessage(content="好的，已展示卡片"), {}))
        if False:
            yield None

    import asyncio
    events = asyncio.run(_collect(full_stream()))
    types = [e["event"] for e in events]
    assert "tool" in types
    assert "card" in types
    assert "text" in types
    assert types[-1] == "done"


async def _collect(stream):
    events = []
    async for event in sse_adapter(stream):
        events.append(event)
    return events
