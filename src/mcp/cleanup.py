"""MCP 连接管理器 — 超时配置 + 结构化日志 + 监控统计."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from src.db import list_mcp_configs

logger = logging.getLogger(__name__)


@dataclass
class MCPLoadResult:
    """MCP 工具加载结果."""

    tools: list[BaseTool]
    server_count: int
    errors: list[str] = field(default_factory=list)
    load_time_ms: float = 0.0


class MCPConnectionManager:
    """管理 MCP 工具加载生命周期。

    职责：
    - 可配置超时（SSE connect_timeout / sse_read_timeout）
    - 结构化日志（耗时、server 数、tool 数、错误）
    - 基础统计（加载次数、成功/失败、缓存量）
    - 缓存管理（按 user_id）
    - 预留 AsyncExitStack 接口用于未来持久会话管理

    注意：langchain_mcp_adapters 的工具调用每次自动创建/销毁会话
    （async with create_session），无持久连接状态泄漏。此类管理的是
    加载阶段和缓存生命周期。
    """

    def __init__(
        self,
        *,
        connect_timeout: float = 10.0,
        sse_read_timeout: float = 300.0,
    ) -> None:
        self._connect_timeout = connect_timeout
        self._sse_read_timeout = sse_read_timeout
        self._cache: dict[str, MCPLoadResult] = {}
        self._stats: dict[str, int] = {"loads": 0, "successes": 0, "failures": 0}

    # ── public API ──

    async def load_tools(self, user_id: str) -> MCPLoadResult:
        """加载用户 MCP tools，注入超时并记录日志。

        Args:
            user_id: 用户 ID。

        Returns:
            MCPLoadResult（tools、server_count、errors、load_time_ms）。
        """
        self._stats["loads"] += 1
        t0 = time.monotonic()

        configs = await list_mcp_configs(user_id)
        enabled = [c for c in configs if c.enabled]

        if not enabled:
            result = MCPLoadResult(tools=[], server_count=0)
            result.load_time_ms = (time.monotonic() - t0) * 1000
            return result

        from src.mcp.loader import _build_connections

        connections = _build_connections(
            enabled,
            connect_timeout=self._connect_timeout,
            sse_read_timeout=self._sse_read_timeout,
        )

        if not connections:
            result = MCPLoadResult(
                tools=[], server_count=0, errors=["no valid connections"]
            )
            result.load_time_ms = (time.monotonic() - t0) * 1000
            self._stats["failures"] += 1
            return result

        errors: list[str] = []
        tools: list[BaseTool] = []

        try:
            client = MultiServerMCPClient(connections=connections)
            raw_tools = await client.get_tools()
            tools = list(raw_tools)
            self._stats["successes"] += 1
        except Exception as exc:
            msg = f"MCP load failed: {exc}"
            logger.warning(msg)
            errors.append(msg)
            self._stats["failures"] += 1

        server_count = len(connections)
        elapsed_ms = (time.monotonic() - t0) * 1000

        logger.info(
            "MCP load user=%s servers=%d tools=%d time=%.0fms errors=%d",
            user_id, server_count, len(tools), elapsed_ms, len(errors),
        )

        result = MCPLoadResult(
            tools=tools,
            server_count=server_count,
            errors=errors,
            load_time_ms=elapsed_ms,
        )
        self._cache[user_id] = result
        return result

    def invalidate(self, user_id: str) -> None:
        """清除指定用户的缓存."""
        self._cache.pop(user_id, None)

    @property
    def stats(self) -> dict[str, int]:
        """返回加载统计."""
        total_tools = sum(len(r.tools) for r in self._cache.values())
        return {
            **self._stats,
            "cached_users": len(self._cache),
            "cached_tools": total_tools,
        }
