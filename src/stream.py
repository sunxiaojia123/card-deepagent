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

    输出: event=text | tool | card | popup | status | interrupt | done | error
    """
    thinking_emitted = False
    seen_tool_ids: set[str] = set()

    try:
        async for chunk in stream:
            # 兼容 2-tuple 和 3-tuple 格式
            if len(chunk) == 2:
                mode, data = chunk
            else:
                _ns, mode, data = chunk

            if mode == "messages":
                msg, _meta = data

                # ── 检测 tool call ──
                if isinstance(msg, (AIMessage, AIMessageChunk)):
                    # AIMessageChunk 的 tool_call_chunks 包含正在生成的 tool call 片段
                    tcc = getattr(msg, "tool_call_chunks", None)
                    if tcc:
                        for tc in tcc:
                            tid = tc.get("id", "")
                            name = tc.get("name", "")
                            if name and tid and tid not in seen_tool_ids:
                                seen_tool_ids.add(tid)
                                yield {
                                    "event": "status",
                                    "data": {"type": "tool_call", "name": name},
                                }

                    # 完整 tool_calls（非流式模型或最终 chunk）
                    tc = getattr(msg, "tool_calls", None)
                    if tc:
                        for t in tc:
                            tid = t.get("id", "")
                            name = t.get("name", "")
                            if name and tid and tid not in seen_tool_ids:
                                seen_tool_ids.add(tid)
                                yield {
                                    "event": "status",
                                    "data": {"type": "tool_call", "name": name},
                                }

                # ── 文本输出 ──
                if isinstance(msg, (AIMessage, AIMessageChunk)) and msg.content:
                    content = msg.content
                    if isinstance(content, str) and content.strip():
                        if not thinking_emitted:
                            thinking_emitted = True
                            yield {
                                "event": "status",
                                "data": {"type": "thinking"},
                            }
                    yield {"event": "text", "data": {"content": content}}

            elif mode == "updates":
                # ── interrupt ──
                if "__interrupt__" in data:
                    interrupt_list = data["__interrupt__"]
                    if isinstance(interrupt_list, list) and len(interrupt_list) > 0:
                        item = interrupt_list[0]
                        yield {
                            "event": "interrupt",
                            "data": {
                                "value": getattr(item, "value", None),
                                "id": getattr(item, "id", None),
                            },
                        }

                # ── tool 结果 ──
                for _channel, value in data.items():
                    if isinstance(value, dict) and "messages" in value:
                        for m in value["messages"]:
                            if isinstance(m, ToolMessage):
                                tool_name = getattr(m, "name", "") or ""
                                tool_call_id = getattr(m, "tool_call_id", "")
                                yield {
                                    "event": "status",
                                    "data": {
                                        "type": "tool_done",
                                        "name": tool_name,
                                    },
                                }
                                yield {
                                    "event": "tool",
                                    "data": {
                                        "content": m.content,
                                        "tool_call_id": tool_call_id,
                                        "name": tool_name,
                                    },
                                }

            elif mode == "custom":
                # stream_writer 推送的自定义事件（如 card、popup）
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
