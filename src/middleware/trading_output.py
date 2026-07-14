"""TradingOutputMiddleware — 拦截 card 输出，推送 custom stream."""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.config import get_stream_writer

from src.schemas.trading_result import TradingToolResult


def _parse_trading_result(msg: ToolMessage) -> TradingToolResult | None:
    """从 ToolMessage 内容解析 TradingToolResult。

    LangGraph 将 tool 返回值转为 ToolMessage 时调用 str()，
    所以 TradingToolResult 的 __repr__ 会被嵌入 ToolMessage.content。
    """
    content = str(msg.content)
    if not content.startswith("TradingToolResult("):
        return None
    try:
        # 安全 eval：TradingToolResult 是 dataclass，__repr__ 可解析
        return eval(content, {"TradingToolResult": TradingToolResult})
    except Exception:
        return None


class TradingOutputMiddleware(AgentMiddleware):
    """拦截 tool 返回的 TradingToolResult。

    若 show_type=card → stream_writer 推 custom 事件，ToolMessage 仅含摘要。
    """

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Any,
    ) -> ToolMessage:
        msg = await handler(request)

        # Command（如 confirm_popup 的 interrupt/resume）直接透传
        from langgraph.types import Command
        if isinstance(msg, Command):
            return msg

        result = _parse_trading_result(msg)
        if result is None:
            return msg

        if result.show_type == "card" and result.data:
            try:
                writer = get_stream_writer()
                writer({"event": "card", "data": result.data})
            except RuntimeError:
                pass

        return ToolMessage(
            content=result.summary,
            tool_call_id=msg.tool_call_id,
            artifact=result.data if result.show_type == "card" else None,
        )
