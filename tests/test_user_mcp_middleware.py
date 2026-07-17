"""测试 UserMCPMiddleware."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from src.middleware.user_mcp import UserMCPMiddleware


# ── helpers ──

def _make_model_request(user_id="u1", tools=None):
    """构造最小可用 ModelRequest."""
    from langchain.agents.middleware.types import ModelRequest, Runtime

    model = MagicMock()
    runtime = MagicMock(spec=Runtime)
    runtime.context = {"user_id": user_id}

    return ModelRequest(
        model=model,
        messages=[MagicMock()],
        tools=tools or [],
        runtime=runtime,
    )


def _make_tool_call_request(name="test_tool", tool=None):
    """构造最小可用 ToolCallRequest."""
    from langchain.agents.middleware.types import ToolCallRequest
    from langgraph.prebuilt.tool_node import ToolRuntime

    runtime = MagicMock(spec=ToolRuntime)

    return ToolCallRequest(
        tool_call={"name": name, "args": {}, "id": "call_1", "type": "tool_call"},
        tool=tool,
        state={},
        runtime=runtime,
    )


def _make_mcp_tool(name="mcp_echo"):
    """构造 mock MCP tool."""
    from langchain_core.tools import tool as tool_dec

    @tool_dec
    def _echo(x: str) -> str:
        """Echo tool for testing."""
        return x

    _echo.name = name
    return _echo


# ── awrap_model_call ──


@pytest.mark.asyncio
async def test_awrap_model_call_no_mcp_config():
    """无 MCP 配置时，request 不经修改直接传给 handler."""
    mw = UserMCPMiddleware()
    req = _make_model_request()

    async def handler(r):
        return AIMessage(content="ok")

    with patch("src.middleware.user_mcp.load_mcp_tools", return_value=[]):
        result = await mw.awrap_model_call(req, handler)

    assert result.content == "ok"


@pytest.mark.asyncio
async def test_awrap_model_call_merges_mcp_tools():
    """MCP tools 被合并到 request.tools 中."""
    mw = UserMCPMiddleware()
    existing_tool = _make_mcp_tool("existing")
    mcp_tool = _make_mcp_tool("mcp_fetch")

    req = _make_model_request(tools=[existing_tool])

    captured_tools = []

    async def handler(r):
        captured_tools.extend(r.tools)
        return AIMessage(content="ok")

    with patch("src.middleware.user_mcp.load_mcp_tools", return_value=[mcp_tool]):
        await mw.awrap_model_call(req, handler)

    tool_names = [t.name for t in captured_tools]
    assert "existing" in tool_names
    assert "mcp_fetch" in tool_names


@pytest.mark.asyncio
async def test_awrap_model_call_cache():
    """同一 user_id 第二次调用使用缓存，不重新 load."""
    mw = UserMCPMiddleware()
    mcp_tool = _make_mcp_tool("cached_tool")
    req = _make_model_request()

    async def handler(r):
        return AIMessage(content="ok")

    with patch("src.middleware.user_mcp.load_mcp_tools", return_value=[mcp_tool]) as mock_load:
        await mw.awrap_model_call(req, handler)
        await mw.awrap_model_call(req, handler)
        assert mock_load.call_count == 1


# ── awrap_tool_call ──


@pytest.mark.asyncio
async def test_awrap_tool_call_mcp_tool():
    """未注册的 MCP tool 调用 → 替换 tool 后执行."""
    mw = UserMCPMiddleware()
    mcp_tool = _make_mcp_tool("mcp_remote")

    # 先通过 awrap_model_call 填充缓存
    req = _make_model_request()
    async def _model_handler(r):
        return AIMessage(content="ok")
    with patch("src.middleware.user_mcp.load_mcp_tools", return_value=[mcp_tool]):
        await mw.awrap_model_call(req, _model_handler)

    # 现在测试 tool call 拦截
    tc_req = _make_tool_call_request(name="mcp_remote", tool=None)
    captured_request = []

    async def handler(r):
        captured_request.append(r)
        return ToolMessage(content="mcp result", tool_call_id="call_1")

    result = await mw.awrap_tool_call(tc_req, handler)

    assert captured_request[0].tool is mcp_tool
    assert result.content == "mcp result"


@pytest.mark.asyncio
async def test_awrap_tool_call_registered_tool_passthrough():
    """已注册的 tool 调用（tool 不为 None）→ 直接透传."""
    mw = UserMCPMiddleware()
    known_tool = _make_mcp_tool("known_tool")
    tc_req = _make_tool_call_request(name="known_tool", tool=known_tool)

    async def handler(r):
        return ToolMessage(content="done", tool_call_id="call_1")

    result = await mw.awrap_tool_call(tc_req, handler)
    assert result.content == "done"


@pytest.mark.asyncio
async def test_awrap_tool_call_unknown_tool_passthrough():
    """tool=None 且不在 MCP 缓存中 → 透传给 handler（由 ToolNode 报错）."""
    mw = UserMCPMiddleware()
    tc_req = _make_tool_call_request(name="nonexistent", tool=None)

    async def handler(r):
        return ToolMessage(content="error", tool_call_id="call_1", status="error")

    result = await mw.awrap_tool_call(tc_req, handler)
    assert result.status == "error"


# ── cache management ──


def test_invalidate():
    """invalidate() 清除指定 user 的缓存."""
    mw = UserMCPMiddleware()
    mw._tool_cache["u1"] = [_make_mcp_tool("t1")]
    mw._tool_cache["u2"] = [_make_mcp_tool("t2")]

    mw.invalidate("u1")
    assert "u1" not in mw._tool_cache
    assert "u2" in mw._tool_cache


def test_mcp_tools_by_name():
    """_mcp_tools_by_name 正确汇总所有用户缓存."""
    mw = UserMCPMiddleware()
    t1 = _make_mcp_tool("a")
    t2 = _make_mcp_tool("b")
    mw._tool_cache["u1"] = [t1]
    mw._tool_cache["u2"] = [t2]

    by_name = mw._mcp_tools_by_name
    assert by_name["a"] is t1
    assert by_name["b"] is t2
