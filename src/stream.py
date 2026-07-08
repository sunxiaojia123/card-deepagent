"""SSE 流式适配器 — 将 agent.astream 转换为统一 event 协议."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk

AgentInputStream = AsyncGenerator[tuple[str, tuple[Any, dict]], None]


async def sse_adapter(
    stream: AgentInputStream,
) -> AsyncGenerator[dict[str, Any], None]:
    """将 agent 的 messages stream 转为统一 SSE event dict。

    stream 格式（单 stream_mode）: (mode, (message, metadata))
    输出格式: {"event": "text"|"done"|"error", "data": {...}}

    Usage:
        async for event in sse_adapter(agent.astream(...)):
            yield f"event: {event['event']}\\ndata: {json.dumps(event['data'])}\\n\\n"
    """
    try:
        async for mode, data in stream:
            if mode == "messages":
                msg, _meta = data
                if isinstance(msg, (AIMessage, AIMessageChunk)) and msg.content:
                    yield {
                        "event": "text",
                        "data": {"content": msg.content},
                    }
        yield {"event": "done", "data": {}}
    except Exception as exc:
        yield {"event": "error", "data": {"message": str(exc)}}


async def sse_events_to_str(
    events: AsyncGenerator[dict[str, Any], None],
) -> AsyncGenerator[str, None]:
    """将 event dict 转为 SSE 文本格式。

    Usage:
        async for line in sse_events_to_str(sse_adapter(agent.astream(...))):
            ...
    """
    import json

    async for event in events:
        yield f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
