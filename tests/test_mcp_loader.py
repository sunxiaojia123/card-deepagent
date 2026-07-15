"""测试 MCP 工具加载器."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.db import MCPConfig
from src.mcp.loader import _build_connections, load_mcp_tools


def test_build_stdio_connections():
    """stdio 配置正确转为 StdioConnection."""
    configs = [
        MCPConfig(
            server_id="gate", user_id="u1", server_name="Gate",
            transport="stdio", command="npx", args=["-y", "@gate/mcp-server"],
            env_vars={"GATE_API_KEY": "key123"}, enabled=True,
        ),
    ]
    connections = _build_connections(configs)
    assert "gate" in connections
    conn = connections["gate"]
    assert conn["transport"] == "stdio"
    assert conn["command"] == "npx"
    assert conn["args"] == ["-y", "@gate/mcp-server"]


def test_build_sse_connections():
    """SSE 配置正确转为 SSEConnection."""
    configs = [
        MCPConfig(
            server_id="remote", user_id="u1", server_name="Remote",
            transport="sse", url="https://mcp.example.com/sse",
            headers={"Authorization": "Bearer token"}, enabled=True,
        ),
    ]
    connections = _build_connections(configs)
    assert "remote" in connections
    assert connections["remote"]["transport"] == "sse"
    assert connections["remote"]["url"] == "https://mcp.example.com/sse"


def test_build_connections_skips_disabled():
    """disabled 的配置被跳过."""
    configs = [
        MCPConfig(server_id="enabled", user_id="u1", server_name="E", transport="stdio", command="echo", enabled=True),
        MCPConfig(server_id="disabled", user_id="u1", server_name="D", transport="stdio", command="echo", enabled=False),
    ]
    # build_connections 本身不检查 enabled（在 load_mcp_tools 中过滤）
    # 这里只测 build_connections
    enabled_cfgs = [c for c in configs if c.enabled]
    connections = _build_connections(enabled_cfgs)
    assert len(connections) == 1
    assert "enabled" in connections


def test_build_connections_empty():
    """空配置返回空 dict."""
    assert _build_connections([]) == {}


@pytest.mark.asyncio
async def test_load_mcp_tools_empty():
    """无 MCP 配置时返回空列表."""
    with patch("src.mcp.loader.list_mcp_configs", return_value=[]):
        tools = await load_mcp_tools("user-no-mcp")
    assert tools == []


@pytest.mark.asyncio
async def test_load_mcp_tools_disabled():
    """所有配置 disabled 时返回空列表."""
    configs = [MCPConfig(server_id="x", user_id="u1", server_name="X", transport="stdio", command="echo", enabled=False)]
    with patch("src.mcp.loader.list_mcp_configs", return_value=configs):
        tools = await load_mcp_tools("u1")
    assert tools == []


@pytest.mark.asyncio
async def test_load_mcp_tools_success():
    """正常加载返回 tools 列表."""
    configs = [MCPConfig(server_id="test", user_id="u1", server_name="Test", transport="stdio", command="echo", enabled=True)]
    mock_tool = MagicMock()
    mock_client = MagicMock()
    async def _get_tools(server_name=None):
        return [mock_tool]
    mock_client.get_tools = _get_tools

    with patch("src.mcp.loader.list_mcp_configs", return_value=configs), \
         patch("src.mcp.loader.MultiServerMCPClient", return_value=mock_client):
        tools = await load_mcp_tools("u1")
    assert len(tools) == 1
    assert tools[0] is mock_tool


@pytest.mark.asyncio
async def test_load_mcp_tools_client_error():
    """client.get_tools() 异常时降级返回空列表."""
    configs = [MCPConfig(server_id="bad", user_id="u1", server_name="Bad", transport="stdio", command="bad-cmd", enabled=True)]
    mock_client = MagicMock()
    async def _get_tools_error(server_name=None):
        raise Exception("Connection refused")
    mock_client.get_tools = _get_tools_error

    with patch("src.mcp.loader.list_mcp_configs", return_value=configs), \
         patch("src.mcp.loader.MultiServerMCPClient", return_value=mock_client):
        tools = await load_mcp_tools("u1")
    assert tools == []
