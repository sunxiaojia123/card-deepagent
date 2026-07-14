"""测试 TradingOutputMiddleware."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import ToolMessage

from src.middleware.trading_output import TradingOutputMiddleware
from src.schemas.trading_result import TradingToolResult


from langgraph.types import Command


def _make_request():
    request = MagicMock()
    request.tool_call = {"id": "call_123", "name": "call_internal_api", "args": {}}
    return request


def _make_handler(result):
    async def handler(_req):
        return result
    return handler


def _card_msg(summary="摘要", data=None):
    r = TradingToolResult(summary=summary, show_type="card", data=data)
    return ToolMessage(content=str(r), tool_call_id="call_123")


def _text_msg(summary="文本结果"):
    r = TradingToolResult(summary=summary, show_type="text")
    return ToolMessage(content=str(r), tool_call_id="call_123")


@pytest.mark.asyncio
async def test_card_result_sends_stream_event():
    """show_type=card → stream_writer 推送 card 事件，返回短 ToolMessage."""
    writer = MagicMock()
    middleware = TradingOutputMiddleware()

    with patch("src.middleware.trading_output.get_stream_writer", return_value=writer):
        result = await middleware.awrap_tool_call(
            _make_request(),
            _make_handler(_card_msg("摘要", {"card": {"balance": 500}})),
        )

    assert isinstance(result, ToolMessage)
    assert result.content == "摘要"
    assert result.tool_call_id == "call_123"
    assert result.artifact == {"card": {"balance": 500}}
    writer.assert_called_once_with({"event": "card", "data": {"card": {"balance": 500}}})


@pytest.mark.asyncio
async def test_text_result_no_stream():
    """show_type=text → 不推 stream 事件."""
    writer = MagicMock()
    middleware = TradingOutputMiddleware()

    with patch("src.middleware.trading_output.get_stream_writer", return_value=writer):
        result = await middleware.awrap_tool_call(
            _make_request(),
            _make_handler(_text_msg("文本结果")),
        )

    assert result.content == "文本结果"
    writer.assert_not_called()


@pytest.mark.asyncio
async def test_non_trading_result_passthrough():
    """非 TradingToolResult 直接透传."""
    middleware = TradingOutputMiddleware()
    result = await middleware.awrap_tool_call(
        _make_request(),
        _make_handler(ToolMessage(content="普通消息", tool_call_id="call_456")),
    )
    assert result.content == "普通消息"


@pytest.mark.asyncio
async def test_card_writer_exception_no_crash():
    """stream_writer 抛 RuntimeError 不崩溃."""
    middleware = TradingOutputMiddleware()
    result = await middleware.awrap_tool_call(
        _make_request(),
        _make_handler(_card_msg("ok", {"x": 1})),
    )
    assert result.content == "ok"


@pytest.mark.asyncio
async def test_card_no_data_no_stream():
    """data=None 时不推送."""
    writer = MagicMock()
    middleware = TradingOutputMiddleware()

    with patch("src.middleware.trading_output.get_stream_writer", return_value=writer):
        result = await middleware.awrap_tool_call(
            _make_request(),
            _make_handler(_card_msg("ok", None)),
        )

    assert result.content == "ok"
    writer.assert_not_called()


@pytest.mark.asyncio
async def test_command_passthrough():
    """confirm_popup 返回的 Command 直接透传（不解析为 TradingToolResult）."""
    middleware = TradingOutputMiddleware()
    cmd = Command(update={"messages": [ToolMessage(content="用户选择了: 现货", tool_call_id="call_cmd")]})

    result = await middleware.awrap_tool_call(
        _make_request(),
        _make_handler(cmd),
    )
    assert isinstance(result, Command)
    assert result.update["messages"][0].content == "用户选择了: 现货"
