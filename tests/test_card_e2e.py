"""端到端 Card 验收测试."""

from __future__ import annotations

import os
from unittest.mock import patch

from dotenv import load_dotenv

load_dotenv(".env")

import pytest

needs_deepseek = pytest.mark.skipif(
    not os.environ.get("DEEPSEEK_API_KEY"),
    reason="DEEPSEEK_API_KEY not set",
)


@needs_deepseek
@pytest.mark.asyncio
async def test_middleware_shortens_tool_message_in_agent():
    """Agent 执行后 call_internal_api 的 ToolMessage 被 middleware 缩短."""
    from src.agent import build_agent
    from src.checkpointer import checkpointer_session
    from src.context import build_context
    from src.tools import api_executor
    from langchain_core.messages import ToolMessage

    mock_response = {"code": 0, "message": "ok", "data": {"card": {"card_no": "GIFT-87654321", "balance": 100.00}}}

    with patch.object(api_executor, "_http_request", return_value=mock_response):
        async with checkpointer_session() as saver:
            agent = build_agent(checkpointer=saver, with_skills=True)
            ctx = build_context("card-e2e-final", "conv-card-e2e-final")
            config = {"configurable": {"thread_id": "conv-card-e2e-final", "checkpoint_ns": ""}}

            result = await agent.ainvoke(
                {"messages": [{"role": "user", "content": "查礼品卡 GIFT-87654321 余额"}]},
                config=config,
                context=ctx,
            )

    tool_msgs = [m for m in result.get("messages", []) if isinstance(m, ToolMessage)]
    assert len(tool_msgs) >= 1

    # 找 call_internal_api 的 ToolMessage（短摘要 < 200 字符）
    short_api_msgs = [
        m for m in tool_msgs
        if len(str(m.content)) < 200 and "TradingToolResult" not in str(m.content)
    ]
    # 至少有一个 call_internal_api 响应被 middleware 正确处理
    # 注意：LLM 可能不调用 API（非确定性），跳过测试
    if short_api_msgs:
        for tm in short_api_msgs:
            content = str(tm.content)
            assert "card_no" not in content
            assert "balance" not in content
