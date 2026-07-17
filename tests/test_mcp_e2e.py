"""端到端 MCP 验收测试 — 用户隔离 + 工具加载 + 中间件注入.

使用两个真实 MCP server（stdio，无需认证）：
- @modelcontextprotocol/server-sequential-thinking: sequentialthinking
- @modelcontextprotocol/server-memory: read_graph, search_nodes, create_entities 等
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from src.db import MCPConfig, create_mcp_config, delete_mcp_config, init_mcp_table
from src.mcp.loader import load_mcp_tools
from src.middleware.user_mcp import UserMCPMiddleware

# 真实 MCP server，npx 启动
SEQUENTIAL_THINKING = {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
}
MEMORY_GRAPH = {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-memory"],
}


@pytest.fixture(autouse=True)
async def _ensure_table():
    await init_mcp_table()


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def _register(user_id: str, server_id: str, name: str, cfg: dict):
    await create_mcp_config(MCPConfig(
        server_id=server_id,
        user_id=user_id,
        server_name=name,
        transport="stdio",
        command=cfg["command"],
        args=cfg.get("args", []),
        enabled=True,
    ))


async def _cleanup(user_id: str, *server_ids: str):
    for sid in server_ids:
        await delete_mcp_config(user_id, sid)


def _make_model_request(user_id: str):
    from langchain.agents.middleware.types import ModelRequest, Runtime

    runtime = MagicMock(spec=Runtime)
    runtime.context = {"user_id": user_id}
    return ModelRequest(
        model=MagicMock(),
        messages=[MagicMock()],
        tools=[],
        runtime=runtime,
    )


# ── 1. 工具加载隔离 ──


@pytest.mark.asyncio
async def test_user_a_loads_sequential_thinking_only():
    """用户 A 配置 sequential-thinking → 只加载该工具."""
    uid = _uid("e2e-a")
    await _register(uid, "seq", "SeqThink", SEQUENTIAL_THINKING)
    try:
        tools = await load_mcp_tools(uid)
        names = {t.name for t in tools}
        assert "sequentialthinking" in names
        # 不应加载其他 server 的工具
        assert "read_graph" not in names
        assert "search_nodes" not in names
    finally:
        await _cleanup(uid, "seq")


@pytest.mark.asyncio
async def test_user_b_loads_memory_tools():
    """用户 B 配置 memory graph → 加载知识图谱工具集."""
    uid = _uid("e2e-b")
    await _register(uid, "mem", "MemGraph", MEMORY_GRAPH)
    try:
        tools = await load_mcp_tools(uid)
        names = {t.name for t in tools}
        assert "read_graph" in names
        assert "search_nodes" in names
        assert "create_entities" in names
        assert "sequentialthinking" not in names
    finally:
        await _cleanup(uid, "mem")


# ── 2. 中间件注入隔离 ──


@pytest.mark.asyncio
async def test_middleware_injects_per_user_tools():
    """中间件按用户注入不同工具集."""
    uid_a = _uid("e2e-mwa")
    uid_b = _uid("e2e-mwb")
    await _register(uid_a, "seq", "SeqThink", SEQUENTIAL_THINKING)
    await _register(uid_b, "mem", "MemGraph", MEMORY_GRAPH)
    try:
        mw = UserMCPMiddleware()

        captured_a: list = []
        captured_b: list = []

        async def handler_a(req):
            captured_a.extend(t.name for t in req.tools)
            return AIMessage(content="ok")

        async def handler_b(req):
            captured_b.extend(t.name for t in req.tools)
            return AIMessage(content="ok")

        await mw.awrap_model_call(_make_model_request(uid_a), handler_a)
        await mw.awrap_model_call(_make_model_request(uid_b), handler_b)

        # 用户 A 看到 sequentialthinking
        assert "sequentialthinking" in captured_a
        assert "read_graph" not in captured_a

        # 用户 B 看到 memory 工具
        assert "read_graph" in captured_b
        assert "sequentialthinking" not in captured_b
    finally:
        await _cleanup(uid_a, "seq")
        await _cleanup(uid_b, "mem")


# ── 3. 工具执行端到端 ──


@pytest.mark.asyncio
async def test_mcp_tool_executes_via_middleware():
    """MCP 工具通过中间件 awrap_tool_call 正确执行."""
    uid = _uid("e2e-exec")
    await _register(uid, "mem", "MemGraph", MEMORY_GRAPH)
    try:
        mw = UserMCPMiddleware()

        # 先触发加载（填充缓存）
        async def _noop(req):
            return AIMessage(content="ok")
        await mw.awrap_model_call(_make_model_request(uid), _noop)

        # 构造 tool call 请求（tool=None 模拟 ToolNode 未注册场景）
        from langchain.agents.middleware.types import ToolCallRequest
        from langgraph.prebuilt.tool_node import ToolRuntime

        tc_req = ToolCallRequest(
            tool_call={
                "name": "read_graph",
                "args": {},
                "id": "call_e2e",
                "type": "tool_call",
            },
            tool=None,
            state={},
            runtime=MagicMock(spec=ToolRuntime),
        )

        # 中间件应替换 tool 并执行
        async def execute_handler(req):
            assert req.tool is not None, "中间件应注入真实 tool"
            result = await req.tool.ainvoke(req.tool_call["args"])
            text = result[0]["text"] if isinstance(result, list) else str(result)
            return ToolMessage(content=text, tool_call_id="call_e2e")

        msg = await mw.awrap_tool_call(tc_req, execute_handler)
        # read_graph 返回 JSON，即使空图也包含 entities 字段
        assert "entities" in msg.content
    finally:
        await _cleanup(uid, "mem")


# ── 4. 配置变更后缓存失效 ──


@pytest.mark.asyncio
async def test_config_change_invalidates_cache():
    """用户修改 MCP 配置 → invalidate 后重新加载."""
    uid = _uid("e2e-inv")
    await _register(uid, "seq", "SeqThink", SEQUENTIAL_THINKING)
    try:
        mw = UserMCPMiddleware()

        async def _noop(req):
            return AIMessage(content="ok")

        # 第一次加载（sequentialthinking）
        await mw.awrap_model_call(_make_model_request(uid), _noop)
        assert "sequentialthinking" in mw._mcp_tools_by_name

        # 模拟配置变更：删除 seq，添加 mem
        await _cleanup(uid, "seq")
        await _register(uid, "mem", "MemGraph", MEMORY_GRAPH)
        mw.invalidate(uid)

        # 重新加载（memory 工具）
        await mw.awrap_model_call(_make_model_request(uid), _noop)
        names = mw._mcp_tools_by_name
        assert "read_graph" in names
        assert "sequentialthinking" not in names
    finally:
        await _cleanup(uid, "mem")


# ── 5. 无配置用户不受影响 ──


@pytest.mark.asyncio
async def test_user_without_mcp_config():
    """未配置 MCP 的用户 → 工具列表为空，请求正常透传."""
    uid = _uid("e2e-none")
    mw = UserMCPMiddleware()

    original_tools = [MagicMock(name="existing_tool")]
    req = _make_model_request(uid)
    req = req.override(tools=original_tools)

    captured: list = []

    async def handler(r):
        captured.extend(r.tools)
        return AIMessage(content="ok")

    await mw.awrap_model_call(req, handler)
    assert captured == original_tools
