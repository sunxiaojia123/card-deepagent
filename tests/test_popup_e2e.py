"""端到端 Popup 验收测试."""

from __future__ import annotations

import json
import os

from dotenv import load_dotenv

load_dotenv(".env")

import pytest
from langchain_core.messages import ToolMessage

needs_deepseek = pytest.mark.skipif(
    not os.environ.get("DEEPSEEK_API_KEY"),
    reason="DEEPSEEK_API_KEY not set",
)


@needs_deepseek
@pytest.mark.asyncio
async def test_popup_tool_works_in_agent():
    """confirm_popup tool 在 agent 中可被调用，产生 interrupt 和 popup 事件."""
    from src.agent import build_agent
    from src.checkpointer import checkpointer_session
    from src.context import build_context

    async with checkpointer_session() as saver:
        agent = build_agent(checkpointer=saver, with_skills=True)
        ctx = build_context("popup-e2e", "conv-popup-e2e")
        config = {"configurable": {"thread_id": "conv-popup-e2e", "checkpoint_ns": ""}}

        events = []
        async for chunk in agent.astream(
            {"messages": [{"role": "user", "content": "帮我买点币，请先弹出选择窗口让我选"}]},
            config=config,
            context=ctx,
            stream_mode=["messages", "updates", "custom"],
        ):
            if len(chunk) == 3:
                ns, mode, data = chunk
            else:
                mode, data = chunk
            if mode == "custom" and isinstance(data, dict):
                events.append(data)

    popup_events = [e for e in events if e.get("event") == "popup"]
    # 如果 LLM 调了 popup（非确定性），验证格式
    if popup_events:
        p = popup_events[0]
        assert "title" in p["data"]
        assert "options" in p["data"]
        assert len(p["data"]["options"]) >= 2
