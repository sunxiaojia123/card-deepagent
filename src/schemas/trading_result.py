"""TradingToolResult — 业务 tool 统一返回结构."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from langchain_core.messages import ToolMessage


@dataclass
class TradingToolResult:
    """业务 tool 统一返回结构。

    Middleware 只认这个结构，不解析自然语言。
    """

    summary: str
    """给 LLM 的 ToolMessage 摘要，不包含大 JSON。"""

    show_type: Literal["text", "card", "none"] = "none"
    """输出方式：text=纯文本, card=卡片, none=无输出。"""

    data: dict | None = None
    """show_type=card 时的卡片数据，通过 custom stream 推给前端。"""


def to_tool_message(result: TradingToolResult, tool_call_id: str) -> ToolMessage:
    """将 TradingToolResult 转为 ToolMessage。

    ToolMessage 只包含 summary，card data 不塞进 LLM context。
    """
    return ToolMessage(
        content=result.summary,
        tool_call_id=tool_call_id,
    )
