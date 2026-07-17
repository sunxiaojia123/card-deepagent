"""UserMCPMiddleware — 按 user 动态绑定 MCP tools."""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from typing import Any, Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse, ToolCallRequest
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from langgraph.types import Command

from src.mcp.loader import load_mcp_tools

logger = logging.getLogger(__name__)

_CACHE_TTL_S = 300  # 5 分钟


class UserMCPMiddleware(AgentMiddleware):
    """按用户动态加载 MCP tools 并注入到模型调用中。

    两个 hook：
    - awrap_model_call: 加载用户 MCP tools，合并到 request.tools
    - awrap_tool_call: 拦截未注册的 MCP tool 调用，替换为真实 tool 实例后再执行

    缓存策略：按 user_id 缓存，TTL 300s 后自动刷新。
    """

    def __init__(self) -> None:
        super().__init__()
        self._tool_cache: dict[str, list[BaseTool]] = {}
        self._cache_ts: dict[str, float] = {}

    # ── model call ──

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        ctx = request.runtime.context or {}
        user_id: str = ctx.get("user_id", "anonymous")

        mcp_tools = await self._get_or_load(user_id)

        if not mcp_tools:
            return await handler(request)

        merged = list(request.tools) + mcp_tools
        return await handler(request.override(tools=merged))

    # ── tool call ──

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        tool_name = request.tool_call["name"]

        if request.tool is None and tool_name in self._mcp_tools_by_name:
            tool = self._mcp_tools_by_name[tool_name]
            return await handler(replace(request, tool=tool))

        return await handler(request)

    # ── cache ──

    async def _get_or_load(self, user_id: str) -> list[BaseTool]:
        """获取缓存的 tools，过期则重新加载."""
        now = time.monotonic()
        cached_at = self._cache_ts.get(user_id, 0)
        if user_id in self._tool_cache and (now - cached_at) < _CACHE_TTL_S:
            return self._tool_cache[user_id]

        mcp_tools = await load_mcp_tools(user_id)
        self._tool_cache[user_id] = mcp_tools
        self._cache_ts[user_id] = now

        if mcp_tools:
            logger.debug("MCP tools cached for user=%s count=%d ttl=%ds", user_id, len(mcp_tools), _CACHE_TTL_S)
        return mcp_tools

    def invalidate(self, user_id: str) -> None:
        """清除用户 MCP tool 缓存（MCP 配置变更后调用）."""
        self._tool_cache.pop(user_id, None)
        self._cache_ts.pop(user_id, None)

    # ── helpers ──

    @property
    def _mcp_tools_by_name(self) -> dict[str, BaseTool]:
        """所有已缓存 MCP tools 的 name → tool 映射."""
        out: dict[str, BaseTool] = {}
        for tools in self._tool_cache.values():
            for t in tools:
                if t.name not in out:
                    out[t.name] = t
        return out
