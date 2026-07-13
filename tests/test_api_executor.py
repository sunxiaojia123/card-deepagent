"""测试通用 API 执行器 call_internal_api."""

from __future__ import annotations

import pytest
from httpx import Response

from src.schemas.trading_result import TradingToolResult
from src.tools.api_executor import call_internal_api


@pytest.mark.asyncio
async def test_call_api_card_success(httpx_mock):
    """code=0 + show_type=card → 返回 card 类型."""
    httpx_mock.add_response(
        method="POST",
        url="http://localhost:9000/api/v1/gift-card/query",
        json={"code": 0, "message": "ok", "data": {"card": {"card_no": "GIFT-12345678", "balance": 500}}},
    )
    result = await call_internal_api.ainvoke({"api_name": "query_gift_card", "params": {"card_no": "GIFT-12345678"}})
    assert isinstance(result, TradingToolResult)
    assert result.show_type == "card"
    assert result.data == {"card": {"card_no": "GIFT-12345678", "balance": 500}}
    assert "执行成功" in result.summary


@pytest.mark.asyncio
async def test_call_api_text_success(httpx_mock):
    """code=0 + show_type=text → 返回 text 类型."""
    httpx_mock.add_response(
        method="GET",
        url="http://localhost:9000/api/v1/market/info?symbol=BTC",
        json={"code": 0, "message": "ok", "data": {"symbol": "BTC", "info": "Bitcoin"}},
    )
    result = await call_internal_api.ainvoke({"api_name": "query_market_info", "params": {"symbol": "BTC"}})
    assert result.show_type == "text"
    assert "Bitcoin" in result.summary


@pytest.mark.asyncio
async def test_call_api_error_code(httpx_mock):
    """code≠0 → 返回 none 类型，summary 含错误信息."""
    httpx_mock.add_response(
        method="POST",
        url="http://localhost:9000/api/v1/gift-card/query",
        json={"code": 1001, "message": "卡号不存在", "data": None},
    )
    result = await call_internal_api.ainvoke({"api_name": "query_gift_card", "params": {"card_no": "INVALID"}})
    assert result.show_type == "none"
    assert "卡号不存在" in result.summary
    assert "code=1001" in result.summary


@pytest.mark.asyncio
async def test_call_api_unknown_name():
    """未知 API 名称 → 返回 none."""
    result = await call_internal_api.ainvoke({"api_name": "nonexistent_api", "params": {}})
    assert result.show_type == "none"
    assert "未找到 API" in result.summary


@pytest.mark.asyncio
async def test_call_api_missing_required_param():
    """缺少必填参数 → 返回 none."""
    result = await call_internal_api.ainvoke({"api_name": "query_gift_card", "params": {}})
    assert result.show_type == "none"
    assert "缺少必填参数" in result.summary
    assert "card_no" in result.summary


@pytest.mark.asyncio
async def test_call_api_http_error(httpx_mock):
    """HTTP 请求失败 → 返回 none."""
    httpx_mock.add_exception(
        method="POST",
        url="http://localhost:9000/api/v1/gift-card/query",
        exception=Exception("Connection refused"),
    )
    result = await call_internal_api.ainvoke({"api_name": "query_gift_card", "params": {"card_no": "GIFT-12345678"}})
    assert result.show_type == "none"
    assert "API 请求失败" in result.summary
