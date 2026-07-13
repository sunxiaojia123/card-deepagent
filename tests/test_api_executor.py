"""测试通用 API 执行器 call_internal_api."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.schemas.trading_result import TradingToolResult


@pytest.mark.asyncio
async def test_call_api_card_success():
    """show_type=card → 返回 card 类型."""
    with patch("src.tools.api_executor._http_request", return_value={"code": 0, "message": "ok", "data": {"card": {"card_no": "GIFT-12345678", "balance": 500}}}):
        from src.tools.api_executor import call_internal_api
        result = await call_internal_api.ainvoke({"api_name": "query_gift_card", "params": {"card_no": "GIFT-12345678"}})
    assert result.show_type == "card"
    assert result.data["card"]["balance"] == 500


@pytest.mark.asyncio
async def test_call_api_text_success():
    """show_type=text → 返回 text 类型."""
    with patch("src.tools.api_executor._http_request", return_value={"code": 0, "message": "ok", "data": {"symbol": "BTC", "info": "Bitcoin"}}):
        from src.tools.api_executor import call_internal_api
        result = await call_internal_api.ainvoke({"api_name": "query_market_info", "params": {"symbol": "BTC"}})
    assert result.show_type == "text"
    assert "Bitcoin" in result.summary


@pytest.mark.asyncio
async def test_call_api_error_code():
    """code≠0 → 返回 none."""
    with patch("src.tools.api_executor._http_request", return_value={"code": 1001, "message": "卡号不存在", "data": None}):
        from src.tools.api_executor import call_internal_api
        result = await call_internal_api.ainvoke({"api_name": "query_gift_card", "params": {"card_no": "INVALID"}})
    assert result.show_type == "none"
    assert "卡号不存在" in result.summary


@pytest.mark.asyncio
async def test_call_api_unknown_name():
    """未知 API → 返回 none."""
    from src.tools.api_executor import call_internal_api
    result = await call_internal_api.ainvoke({"api_name": "nonexistent", "params": {}})
    assert result.show_type == "none"
    assert "未找到 API" in result.summary


@pytest.mark.asyncio
async def test_call_api_missing_required_param():
    """缺少必填参数 → 返回 none."""
    from src.tools.api_executor import call_internal_api
    result = await call_internal_api.ainvoke({"api_name": "query_gift_card", "params": {}})
    assert result.show_type == "none"
    assert "缺少必填参数" in result.summary


@pytest.mark.asyncio
async def test_call_api_http_error():
    """HTTP 失败 → 返回 none."""
    with patch("src.tools.api_executor._http_request", side_effect=Exception("Connection refused")):
        from src.tools.api_executor import call_internal_api
        result = await call_internal_api.ainvoke({"api_name": "query_gift_card", "params": {"card_no": "GIFT-12345678"}})
    assert result.show_type == "none"
    assert "API 请求失败" in result.summary
