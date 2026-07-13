"""测试 TradingToolResult 数据结构与转换."""

from __future__ import annotations

from langchain_core.messages import ToolMessage

from src.schemas.trading_result import TradingToolResult, to_tool_message


def test_card_type_with_data():
    """show_type=card 时包含 card 数据."""
    result = TradingToolResult(
        summary="用户持仓：BTC 0.5, ETH 10",
        show_type="card",
        data={"positions": [{"symbol": "BTC", "amount": 0.5}]},
    )
    assert result.show_type == "card"
    assert result.data is not None
    assert "BTC" in result.summary


def test_text_type():
    """show_type=text 时无 card 数据."""
    result = TradingToolResult(
        summary="当前 BTC 价格 42000 USDT",
        show_type="text",
    )
    assert result.show_type == "text"
    assert result.data is None


def test_none_type():
    """默认 show_type=none，无输出."""
    result = TradingToolResult(summary="操作完成")
    assert result.show_type == "none"


def test_to_tool_message_card():
    """to_tool_message 生成 ToolMessage，只包含 summary."""
    result = TradingToolResult(
        summary="已展示持仓卡片",
        show_type="card",
        data={"positions": [{"symbol": "BTC"}]},
    )
    msg = to_tool_message(result, "call_123")
    assert isinstance(msg, ToolMessage)
    assert msg.tool_call_id == "call_123"
    assert msg.content == "已展示持仓卡片"
    # card data 不在 context 中
    assert "positions" not in msg.content


def test_to_tool_message_text():
    """to_tool_message for text 类型."""
    result = TradingToolResult(summary="价格 42000", show_type="text")
    msg = to_tool_message(result, "call_456")
    assert msg.content == "价格 42000"
