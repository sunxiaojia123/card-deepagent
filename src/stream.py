"""SSE 流式适配器 — 将 agent.astream 转换为统一 event 协议."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

AgentMultiStream = AsyncGenerator[tuple[Any, str, Any], None]


async def sse_adapter(
    stream: AgentMultiStream,
) -> AsyncGenerator[dict[str, Any], None]:
    """将 agent stream 转为统一 SSE event dict。

    兼容:
    - 单 stream_mode: (mode, data) → 2-tuple
    - 多 stream_mode: (ns, mode, data) → 3-tuple

    输出: event=text | tool | done | error
    """
    try:
        async for chunk in stream:
            # 兼容 2-tuple 和 3-tuple 格式
            if len(chunk) == 2:
                mode, data = chunk
            else:
                _ns, mode, data = chunk

            if mode == "messages":
                msg, _meta = data
                if isinstance(msg, (AIMessage, AIMessageChunk)) and msg.content:
                    yield {"event": "text", "data": {"content": msg.content}}

            elif mode == "updates":
                # 检测 interrupt（popup 等暂停信号）
                if "__interrupt__" in data:
                    interrupt_list = data["__interrupt__"]
                    if isinstance(interrupt_list, list) and len(interrupt_list) > 0:
                        # Interrupt 对象转 dict（提取 value + id 字段）
                        item = interrupt_list[0]
                        yield {
                            "event": "interrupt",
                            "data": {
                                "value": getattr(item, "value", None),
                                "id": getattr(item, "id", None),
                            },
                        }
                for _channel, value in data.items():
                    if isinstance(value, dict) and "messages" in value:
                        for m in value["messages"]:
                            if isinstance(m, ToolMessage):
                                yield {
                                    "event": "tool",
                                    "data": {
                                        "content": m.content,
                                        "tool_call_id": getattr(m, "tool_call_id", ""),
                                    },
                                }

            elif mode == "custom":
                # stream_writer 推送的自定义事件（如 card）
                if isinstance(data, dict) and "event" in data:
                    yield data

        yield {"event": "done", "data": {}}
    except Exception as exc:
        yield {"event": "error", "data": {"message": str(exc)}}


async def sse_events_to_str(
    events: AsyncGenerator[dict[str, Any], None],
) -> AsyncGenerator[str, None]:
    """将 event dict 转为 SSE 文本格式."""
    import json

    async for event in events:
        yield f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
