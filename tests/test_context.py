"""测试 TradingContext 定义与 build_context 工具函数."""

from __future__ import annotations

import pytest
from deepagents import create_deep_agent

from src.context import TradingContext, build_context


def test_trading_context_fields():
    """TradingContext 包含所有必要字段."""
    fields = TradingContext.__annotations__
    assert "user_id" in fields
    assert "conversation_id" in fields
    assert "enabled_skills" in fields
    assert "mcp_server_ids" in fields
    assert "tenant_id" in fields


def test_build_context_minimal():
    """最少参数构建 TradingContext."""
    ctx = build_context("user-1", "conv-1")
    assert ctx["user_id"] == "user-1"
    assert ctx["conversation_id"] == "conv-1"
    assert "enabled_skills" not in ctx
    assert "mcp_server_ids" not in ctx
    assert "tenant_id" not in ctx


def test_build_context_full():
    """全参数构建 TradingContext."""
    ctx = build_context(
        "user-2",
        "conv-2",
        enabled_skills=["skill-a"],
        mcp_server_ids=["mcp-1"],
        tenant_id="tenant-x",
    )
    assert ctx["user_id"] == "user-2"
    assert ctx["conversation_id"] == "conv-2"
    assert ctx["enabled_skills"] == ["skill-a"]
    assert ctx["mcp_server_ids"] == ["mcp-1"]
    assert ctx["tenant_id"] == "tenant-x"


def test_build_context_optional_none_not_set():
    """None 可选字段不会被写入 dict."""
    ctx = build_context("u", "c", enabled_skills=None, mcp_server_ids=None, tenant_id=None)
    assert "enabled_skills" not in ctx
    assert "mcp_server_ids" not in ctx
    assert "tenant_id" not in ctx


def test_context_schema_compatible(monkeypatch):
    """TradingContext 可作为 context_schema 传入 create_deep_agent."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    agent = create_deep_agent(
        model="deepseek:deepseek-v4-pro",
        context_schema=TradingContext,
    )
    assert agent is not None
    assert agent.context_schema is TradingContext
