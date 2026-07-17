"""测试 MCP 连接管理器 + loader 增强."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from src.db import MCPConfig
from src.mcp.cleanup import MCPConnectionManager, MCPLoadResult
from src.mcp.loader import _build_connections, load_mcp_tools_with_stats


# ── _build_connections 增强 ──


def test_build_connections_injects_sse_timeout():
    """SSE 连接被注入 timeout 和 sse_read_timeout."""
    configs = [
        MCPConfig(
            server_id="sse-srv", user_id="u1", server_name="SSE",
            transport="sse", url="https://mcp.example.com/sse",
            headers={"Authorization": "Bearer x"}, enabled=True,
        ),
    ]
    connections = _build_connections(configs, connect_timeout=5.0, sse_read_timeout=120.0)
    conn = connections["sse-srv"]
    assert conn["timeout"] == 5.0
    assert conn["sse_read_timeout"] == 120.0


def test_build_connections_sse_default_timeouts():
    """未指定超时时使用默认值."""
    configs = [
        MCPConfig(
            server_id="sse-srv", user_id="u1", server_name="SSE",
            transport="sse", url="https://mcp.example.com/sse",
            enabled=True,
        ),
    ]
    connections = _build_connections(configs)
    conn = connections["sse-srv"]
    assert conn["timeout"] == 10.0
    assert conn["sse_read_timeout"] == 300.0


def test_build_connections_streamable_http():
    """streamable_http transport 正确构建连接."""
    configs = [
        MCPConfig(
            server_id="http-srv", user_id="u1", server_name="HTTP",
            transport="streamable_http", url="https://mcp.example.com/mcp",
            headers={"X-API-Key": "secret"}, enabled=True,
        ),
    ]
    connections = _build_connections(configs)
    conn = connections["http-srv"]
    assert conn["transport"] == "streamable_http"
    assert conn["url"] == "https://mcp.example.com/mcp"
    assert conn["headers"] == {"X-API-Key": "secret"}


def test_build_connections_stdio_unchanged():
    """stdio 连接不受 timeout 参数影响."""
    configs = [
        MCPConfig(
            server_id="cli", user_id="u1", server_name="CLI",
            transport="stdio", command="npx", args=["-y", "mcp"],
            enabled=True,
        ),
    ]
    connections = _build_connections(configs, connect_timeout=5.0)
    conn = connections["cli"]
    assert conn["transport"] == "stdio"
    assert conn["command"] == "npx"
    assert "timeout" not in conn  # stdio 无 timeout 字段


# ── load_mcp_tools_with_stats ──


@pytest.mark.asyncio
async def test_load_mcp_tools_with_stats_empty():
    """无配置时返回空 stats."""
    with patch("src.mcp.loader.list_mcp_configs", return_value=[]):
        tools, stats = await load_mcp_tools_with_stats("u1")
    assert tools == []
    assert stats["server_count"] == 0
    assert stats["tool_count"] == 0
    assert stats["errors"] == []


@pytest.mark.asyncio
async def test_load_mcp_tools_with_stats_success():
    """正常加载返回 tools + stats."""
    configs = [
        MCPConfig(
            server_id="test", user_id="u1", server_name="Test",
            transport="stdio", command="echo", enabled=True,
        ),
    ]
    mock_tool = MagicMock()
    mock_client = MagicMock()

    async def _get_tools(server_name=None):
        return [mock_tool]
    mock_client.get_tools = _get_tools

    with patch("src.mcp.loader.list_mcp_configs", return_value=configs), \
         patch("src.mcp.loader.MultiServerMCPClient", return_value=mock_client):
        tools, stats = await load_mcp_tools_with_stats("u1")

    assert len(tools) == 1
    assert stats["server_count"] == 1
    assert stats["tool_count"] == 1
    assert stats["errors"] == []
    assert stats["time_ms"] >= 0


# ── MCPConnectionManager ──


@pytest.mark.asyncio
async def test_manager_load_tools_empty():
    """无配置时返回空 MCPLoadResult."""
    mgr = MCPConnectionManager()
    with patch("src.mcp.cleanup.list_mcp_configs", return_value=[]):
        result = await mgr.load_tools("u1")
    assert isinstance(result, MCPLoadResult)
    assert result.tools == []
    assert result.server_count == 0


@pytest.mark.asyncio
async def test_manager_load_tools_success():
    """正常加载返回 MCPLoadResult."""
    mgr = MCPConnectionManager()
    configs = [
        MCPConfig(
            server_id="test", user_id="u1", server_name="Test",
            transport="stdio", command="echo", enabled=True,
        ),
    ]
    mock_tool = MagicMock()
    mock_client = MagicMock()

    async def _get_tools(server_name=None):
        return [mock_tool]
    mock_client.get_tools = _get_tools

    with patch("src.mcp.cleanup.list_mcp_configs", return_value=configs), \
         patch("src.mcp.cleanup.MultiServerMCPClient", return_value=mock_client):
        result = await mgr.load_tools("u1")

    assert len(result.tools) == 1
    assert result.server_count == 1
    assert result.load_time_ms >= 0


@pytest.mark.asyncio
async def test_manager_stats():
    """stats 正确反映加载统计."""
    mgr = MCPConnectionManager()
    configs = [
        MCPConfig(
            server_id="test", user_id="u1", server_name="Test",
            transport="stdio", command="echo", enabled=True,
        ),
    ]
    mock_tool = MagicMock()
    mock_client = MagicMock()

    async def _get_tools(server_name=None):
        return [mock_tool]
    mock_client.get_tools = _get_tools

    with patch("src.mcp.cleanup.list_mcp_configs", return_value=configs), \
         patch("src.mcp.cleanup.MultiServerMCPClient", return_value=mock_client):
        await mgr.load_tools("u1")
        await mgr.load_tools("u2")

    s = mgr.stats
    assert s["loads"] == 2
    assert s["successes"] == 2
    assert s["failures"] == 0
    assert s["cached_users"] == 2


@pytest.mark.asyncio
async def test_manager_invalidate():
    """invalidate 清除指定用户缓存."""
    mgr = MCPConnectionManager()
    configs = [
        MCPConfig(
            server_id="test", user_id="u1", server_name="Test",
            transport="stdio", command="echo", enabled=True,
        ),
    ]
    mock_tool = MagicMock()
    mock_client = MagicMock()

    async def _get_tools(server_name=None):
        return [mock_tool]
    mock_client.get_tools = _get_tools

    with patch("src.mcp.cleanup.list_mcp_configs", return_value=configs), \
         patch("src.mcp.cleanup.MultiServerMCPClient", return_value=mock_client):
        await mgr.load_tools("u1")
        await mgr.load_tools("u2")

    assert mgr.stats["cached_users"] == 2
    mgr.invalidate("u1")
    assert mgr.stats["cached_users"] == 1


# ── middleware TTL cache ──


@pytest.mark.asyncio
async def test_middleware_cache_ttl_expiry():
    """缓存过期后重新加载."""
    from src.middleware.user_mcp import UserMCPMiddleware

    mw = UserMCPMiddleware()
    mcp_tool = MagicMock()
    mcp_tool.name = "fresh_tool"
    req = _make_model_request()
    mw._tool_cache["u1"] = [mcp_tool]
    mw._cache_ts["u1"] = 0  # 很久以前缓存的，已过期

    async def handler(r):
        return MagicMock(content="ok")

    with patch("src.middleware.user_mcp.load_mcp_tools", return_value=[mcp_tool]) as mock_load:
        await mw.awrap_model_call(req, handler)
        assert mock_load.call_count == 1  # 重新加载了


@pytest.mark.asyncio
async def test_middleware_cache_ttl_fresh():
    """缓存未过期时不重新加载."""
    from src.middleware.user_mcp import UserMCPMiddleware

    mw = UserMCPMiddleware()
    mcp_tool = MagicMock()
    mcp_tool.name = "fresh_tool"
    req = _make_model_request()
    mw._tool_cache["u1"] = [mcp_tool]
    mw._cache_ts["u1"] = time.monotonic()  # 刚缓存的

    async def handler(r):
        return MagicMock(content="ok")

    with patch("src.middleware.user_mcp.load_mcp_tools") as mock_load:
        await mw.awrap_model_call(req, handler)
        assert mock_load.call_count == 0  # 使用缓存


def _make_model_request(user_id="u1"):
    """构造最小可用 ModelRequest."""
    from langchain.agents.middleware.types import ModelRequest, Runtime

    runtime = MagicMock(spec=Runtime)
    runtime.context = {"user_id": user_id}
    return ModelRequest(
        model=MagicMock(),
        messages=[MagicMock()],
        tools=[],
        runtime=runtime,
    )
