"""测试 SSE 流式适配器."""

from __future__ import annotations

import json
import os

import pytest
from langchain_core.messages import HumanMessage

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
    """SSE 适配器输出 event=text 块，最终以 event=done 结束."""
    agent = build_agent()
    ctx = build_context("u1", "conv-sse")
    config = {"configurable": {"thread_id": "conv-sse"}}

    stream = agent.astream(
        {"messages": [HumanMessage(content="用一句话介绍比特币。")]},
        config=config,
        context=ctx,
        stream_mode=["messages"],
    )

    events = []
    async for event in sse_adapter(stream):
        events.append(event)

    assert len(events) >= 2  # 至少一个 text + done
    text_events = [e for e in events if e["event"] == "text"]
    assert len(text_events) > 0
    for te in text_events:
        assert "content" in te["data"]
        assert len(te["data"]["content"]) > 0

    assert events[-1]["event"] == "done"


@needs_deepseek
@pytest.mark.asyncio
async def test_sse_adapter_text_concatenation():
    """所有 text 块的 content 拼接后构成完整回复."""
    agent = build_agent()
    ctx = build_context("u2", "conv-sse2")
    config = {"configurable": {"thread_id": "conv-sse2"}}

    stream = agent.astream(
        {"messages": [HumanMessage(content="说：你好。")]},
        config=config,
        context=ctx,
        stream_mode=["messages"],
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
    ctx = build_context("u3", "conv-sse3")
    config = {"configurable": {"thread_id": "conv-sse3"}}

    stream = agent.astream(
        {"messages": [HumanMessage(content="回复：OK。")]},
        config=config,
        context=ctx,
        stream_mode=["messages"],
    )

    lines = []
    async for line in sse_events_to_str(sse_adapter(stream)):
        lines.append(line)

    assert len(lines) >= 2
    for line in lines:
        assert line.startswith("event: ")
        assert "\ndata: " in line
    # 最后一行是 done
    assert "event: done" in lines[-1]


def test_sse_adapter_error_handling():
    """异常时 sse_adapter 输出 event=error."""

    async def faulty_stream():
        yield "messages", (Exception("test error"), {})
        yield "messages", (None, {})
        if False:  # pragma: no cover
            yield None

    async def run():
        events = []
        async for event in sse_adapter(faulty_stream()):
            events.append(event)
        return events

    import asyncio

    events = asyncio.run(run())
    assert events[-1]["event"] == "done"  # did not raise
    assert len(events) == 1  # no text from faulty data, just done
