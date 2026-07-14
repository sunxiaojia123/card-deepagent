"""测试 confirm_popup Tool."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import ToolMessage

from src.tools.confirm_popup import confirm_popup


def test_confirm_popup_returns_dict_with_messages():
    """confirm_popup 返回 `{messages: [ToolMessage]}` 格式."""
    with patch("src.tools.confirm_popup.get_stream_writer", return_value=MagicMock()), \
         patch("src.tools.confirm_popup.interrupt", return_value={"selected": "buy"}):
        result = confirm_popup.invoke({
            "title": "选择方向",
            "options": [
                {"id": "buy", "label": "买入"},
                {"id": "sell", "label": "卖出"},
            ],
            "tool_call_id": "call_001",
        })

    assert isinstance(result, dict)
    assert "messages" in result
    assert isinstance(result["messages"][0], ToolMessage)
    assert "买入" in result["messages"][0].content
    assert result["messages"][0].tool_call_id == "call_001"


def test_confirm_popup_stream_writer_called():
    """stream_writer 被调用，推送 popup 事件."""
    writer = MagicMock()
    with patch("src.tools.confirm_popup.get_stream_writer", return_value=writer), \
         patch("src.tools.confirm_popup.interrupt", return_value={"selected": "spot"}):
        confirm_popup.invoke({
            "title": "选择交易类型",
            "options": [
                {"id": "spot", "label": "现货"},
                {"id": "futures", "label": "合约"},
            ],
            "tool_call_id": "call_002",
        })

    writer.assert_called_once()
    payload = writer.call_args[0][0]
    assert payload["event"] == "popup"
    assert payload["data"]["title"] == "选择交易类型"
    assert len(payload["data"]["options"]) == 2
    assert payload["data"]["tool_call_id"] == "call_002"


def test_confirm_popup_writer_error_handled():
    """stream_writer 不可用时（RuntimeError）不崩溃."""
    writer = MagicMock(side_effect=RuntimeError("no context"))
    with patch("src.tools.confirm_popup.get_stream_writer", return_value=writer), \
         patch("src.tools.confirm_popup.interrupt", return_value={"selected": "x"}):
        result = confirm_popup.invoke({
            "title": "test",
            "options": [{"id": "x", "label": "X"}],
            "tool_call_id": "call_003",
        })
    assert isinstance(result, dict) and "messages" in result


def test_confirm_popup_string_response():
    """resume 值为字符串时也能正确处理."""
    with patch("src.tools.confirm_popup.get_stream_writer", return_value=MagicMock()), \
         patch("src.tools.confirm_popup.interrupt", return_value="spot"):
        result = confirm_popup.invoke({
            "title": "选择",
            "options": [{"id": "spot", "label": "现货"}],
            "tool_call_id": "call_004",
        })
    content = result["messages"][0].content
    assert "现货" in content or "spot" in content
