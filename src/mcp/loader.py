"""MCP 工具加载器 — 按用户配置动态加载 MCP tools."""

from __future__ import annotations

import logging

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.sessions import SSEConnection, StdioConnection

from src.db import MCPConfig, list_mcp_configs

logger = logging.getLogger(__name__)


async def load_mcp_tools(user_id: str) -> list[BaseTool]:
    """根据用户 MCP 配置加载所有启用的 MCP tools。

    连接失败的 server 自动跳过（降级），不影响其他 server 的加载。

    Args:
        user_id: 用户 ID。

    Returns:
        LangChain BaseTool 列表（可能为空）。
    """
    configs = await list_mcp_configs(user_id)
    enabled = [c for c in configs if c.enabled]
    if not enabled:
        return []

    connections = _build_connections(enabled)
    if not connections:
        return []

    client = MultiServerMCPClient(connections=connections)
    try:
        tools = await client.get_tools()
        logger.info("Loaded %d MCP tools for user %s from %d server(s)", len(tools), user_id, len(enabled))
        return list(tools)
    except Exception as exc:
        logger.warning("Failed to load MCP tools for user %s: %s", user_id, exc)
        return []


def _build_connections(configs: list[MCPConfig]) -> dict:
    """将 MCPConfig 列表转为 MultiServerMCPClient 的 connections dict。

    每个 server 单独 try，单个 server 连接失败不影响其他。
    """
    connections: dict = {}
    for cfg in configs:
        try:
            if cfg.transport == "stdio":
                connections[cfg.server_id] = StdioConnection(
                    transport="stdio",
                    command=cfg.command,
                    args=cfg.args or [],
                    env=cfg.env_vars,
                )
            elif cfg.transport == "sse":
                connections[cfg.server_id] = SSEConnection(
                    transport="sse",
                    url=cfg.url,
                    headers=cfg.headers or {},
                )
        except Exception as exc:
            logger.warning("Failed to build connection for MCP server '%s': %s", cfg.server_id, exc)
    return connections
