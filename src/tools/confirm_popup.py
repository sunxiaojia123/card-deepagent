"""confirm_popup — 弹出确认窗口，暂停 Agent 等待用户选择."""

from __future__ import annotations

from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.config import get_stream_writer
from langgraph.types import interrupt


@tool
def confirm_popup(
    title: str,
    options: list[dict],  # [{"id": "...", "label": "..."}]
    tool_call_id: Annotated[str, "InjectedToolCallId"],
) -> ToolMessage:
    """弹出确认窗口，暂停 Agent 等待用户选择后继续。

    适用场景：用户意图模糊、需要确认交易方向/币种/金额等。
    调用后 Agent 暂停，前端展示弹窗，用户点击选项后通过 Resume API 恢复。

    Args:
        title: 弹窗标题。
        options: 选项列表，每项含 id 和 label。
        tool_call_id: 自动注入的 tool call ID。
    """
    # 推 popup 事件到前端
    try:
        writer = get_stream_writer()
        writer({
            "event": "popup",
            "data": {
                "title": title,
                "options": options,
                "tool_call_id": tool_call_id,
            },
        })
    except RuntimeError:
        pass

    # 暂停 graph，等待用户选择
    response = interrupt({
        "type": "popup",
        "title": title,
        "options": options,
    })

    selected = response.get("selected", "") if isinstance(response, dict) else str(response)
    label = ""
    for opt in options:
        if opt.get("id") == selected:
            label = opt.get("label", selected)
            break

    return {
        "messages": [
            ToolMessage(
                content=f"用户选择了: {label or selected}",
                tool_call_id=tool_call_id,
            )
        ]
    }
