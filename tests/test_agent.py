"""测试基础 Agent 创建与多轮对话."""

from __future__ import annotations

import os

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agent import TRADING_ORCHESTRATOR_PROMPT, build_agent
from src.checkpointer import checkpointer_session
from src.context import TradingContext, build_context

needs_deepseek = pytest.mark.skipif(
    not os.environ.get("DEEPSEEK_API_KEY"),
    reason="DEEPSEEK_API_KEY not set",
)


def test_system_prompt_not_empty():
    """System prompt 非空且包含关键角色信息."""
    assert len(TRADING_ORCHESTRATOR_PROMPT) > 50
    assert "交易助手" in TRADING_ORCHESTRATOR_PROMPT
    assert "合规" in TRADING_ORCHESTRATOR_PROMPT


def test_build_agent_without_checkpointer(monkeypatch):
    """build_agent() 不传 checkpointer 也能成功构建."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    agent = build_agent()
    assert agent is not None
    assert agent.context_schema is TradingContext


def test_build_agent_with_checkpointer(monkeypatch):
    """build_agent() 传入 checkpointer 能成功构建."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    agent = build_agent(checkpointer=True)
    assert agent is not None


@needs_deepseek
@pytest.mark.asyncio
async def test_agent_single_turn_invoke():
    """不传 checkpointer：单轮对话返回 AIMessage."""
    ctx = build_context("user-test", "conv-test")
    config = {"configurable": {"thread_id": "conv-test"}}

    agent = build_agent()
    result = await agent.ainvoke(
        {"messages": [HumanMessage(content="你好，请用一句话介绍你自己。")]},
        config=config,
        context=ctx,
    )

    msgs = result.get("messages", [])
    ai_msgs = [m for m in msgs if isinstance(m, AIMessage)]
    assert len(ai_msgs) > 0
    assert len(ai_msgs[-1].content) > 0


@needs_deepseek
@pytest.mark.asyncio
async def test_agent_multi_turn_with_checkpointer():
    """同一 thread_id 两轮对话，第二轮能引用前文."""
    ctx = build_context("user-mt", "conv-mt")
    config = {"configurable": {"thread_id": "conv-mt"}}

    async with checkpointer_session() as saver:
        agent = build_agent(checkpointer=saver)

        # 第一轮
        result1 = await agent.ainvoke(
            {"messages": [HumanMessage(content="我叫小明，我想了解比特币。")]},
            config=config,
            context=ctx,
        )
        msgs1 = result1.get("messages", [])
        ai1 = [m for m in msgs1 if isinstance(m, AIMessage)]
        assert len(ai1) > 0

        # 第二轮：引用前文
        result2 = await agent.ainvoke(
            {"messages": [HumanMessage(content="我叫什么名字？")]},
            config=config,
            context=ctx,
        )
        msgs2 = result2.get("messages", [])
        ai2 = [m for m in msgs2 if isinstance(m, AIMessage)]
        assert len(ai2) > 0
        # 第二轮回复应该包含"小明"
        assert "小明" in ai2[-1].content
