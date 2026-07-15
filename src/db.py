"""数据库辅助 — conversations 表管理 + 连接获取."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row

from config.settings import settings


@dataclass
class Conversation:
    conversation_id: str
    user_id: str
    created_at: str


async def _get_conn() -> psycopg.AsyncConnection:
    """获取异步数据库连接（autocommit 模式）."""
    conn = await psycopg.AsyncConnection.connect(
        settings.postgres_uri,
        row_factory=dict_row,
    )
    await conn.set_autocommit(True)
    return conn


async def init_db() -> None:
    """初始化数据库表（幂等）."""
    conn = await _get_conn()
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                conversation_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id)"
        )
    finally:
        await conn.close()


async def create_conversation(user_id: str) -> Conversation:
    """创建新会话，返回 Conversation."""
    conn = await _get_conn()
    try:
        conv_id = uuid.uuid4().hex
        row = await (
            await conn.execute(
                "INSERT INTO conversations (conversation_id, user_id) VALUES (%s, %s) RETURNING *",
                (conv_id, user_id),
            )
        ).fetchone()
        if row is None:
            raise RuntimeError("创建会话失败")
        return Conversation(
            conversation_id=row["conversation_id"],
            user_id=row["user_id"],
            created_at=row["created_at"].isoformat(),
        )
    finally:
        await conn.close()


async def list_conversations(user_id: str) -> list[Conversation]:
    """列出用户的所有会话（按创建时间倒序）."""
    conn = await _get_conn()
    try:
        rows = await (
            await conn.execute(
                "SELECT * FROM conversations WHERE user_id = %s ORDER BY created_at DESC",
                (user_id,),
            )
        ).fetchall()
        return [
            Conversation(
                conversation_id=r["conversation_id"],
                user_id=r["user_id"],
                created_at=r["created_at"].isoformat(),
            )
            for r in rows
        ]
    finally:
        await conn.close()


@dataclass
class MCPConfig:
    server_id: str
    user_id: str
    server_name: str
    transport: str  # "stdio" | "sse"
    command: str | None = None  # stdio only
    args: list | None = None  # stdio only
    url: str | None = None  # sse only
    headers: dict | None = None  # sse only
    env_vars: dict | None = None  # env vars (API keys etc)
    enabled: bool = True


async def init_mcp_table() -> None:
    """初始化 MCP 配置表（幂等）."""
    conn = await _get_conn()
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_mcp_configs (
                server_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                server_name TEXT NOT NULL,
                transport TEXT NOT NULL DEFAULT 'stdio',
                command TEXT,
                args JSONB DEFAULT '[]',
                url TEXT,
                headers JSONB DEFAULT '{}',
                env_vars JSONB DEFAULT '{}',
                enabled BOOLEAN DEFAULT true,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (server_id, user_id)
            )
        """)
    finally:
        await conn.close()


async def list_mcp_configs(user_id: str) -> list[MCPConfig]:
    """列出用户的所有 MCP 配置."""
    conn = await _get_conn()
    try:
        rows = await (
            await conn.execute(
                "SELECT * FROM user_mcp_configs WHERE user_id = %s ORDER BY created_at DESC",
                (user_id,),
            )
        ).fetchall()
        return [
            MCPConfig(
                server_id=r["server_id"],
                user_id=r["user_id"],
                server_name=r["server_name"],
                transport=r["transport"],
                command=r["command"],
                args=r["args"],
                url=r["url"],
                headers=r["headers"],
                env_vars=r["env_vars"],
                enabled=r["enabled"],
            )
            for r in rows
        ]
    finally:
        await conn.close()


async def create_mcp_config(config: MCPConfig) -> None:
    """创建 MCP 配置."""
    conn = await _get_conn()
    try:
        import json as _json
        await conn.execute(
            """INSERT INTO user_mcp_configs (server_id, user_id, server_name, transport, command, args, url, headers, env_vars, enabled)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                config.server_id, config.user_id, config.server_name,
                config.transport, config.command,
                _json.dumps(config.args or []), config.url,
                _json.dumps(config.headers or {}), _json.dumps(config.env_vars or {}),
                config.enabled,
            ),
        )
    finally:
        await conn.close()


async def update_mcp_config(user_id: str, server_id: str, updates: dict) -> bool:
    """更新 MCP 配置，返回是否成功."""
    conn = await _get_conn()
    try:
        import json as _json
        # 检查存在
        row = await (
            await conn.execute(
                "SELECT 1 FROM user_mcp_configs WHERE server_id = %s AND user_id = %s",
                (server_id, user_id),
            )
        ).fetchone()
        if not row:
            return False

        # 构建 SET 子句
        set_parts = []
        params = []
        for key in ("server_name", "transport", "command", "url", "enabled"):
            if key in updates:
                set_parts.append(f"{key} = %s")
                params.append(updates[key])
        if "args" in updates:
            set_parts.append("args = %s")
            params.append(_json.dumps(updates["args"]))
        if "headers" in updates:
            set_parts.append("headers = %s")
            params.append(_json.dumps(updates["headers"]))
        if "env_vars" in updates:
            set_parts.append("env_vars = %s")
            params.append(_json.dumps(updates["env_vars"]))

        if set_parts:
            params.extend([server_id, user_id])
            await conn.execute(
                f"UPDATE user_mcp_configs SET {', '.join(set_parts)} WHERE server_id = %s AND user_id = %s",
                params,
            )
        return True
    finally:
        await conn.close()


async def delete_mcp_config(user_id: str, server_id: str) -> bool:
    """删除 MCP 配置，返回是否成功."""
    conn = await _get_conn()
    try:
        result = await conn.execute(
            "DELETE FROM user_mcp_configs WHERE server_id = %s AND user_id = %s",
            (server_id, user_id),
        )
        return int(result.rowcount) > 0  # type: ignore[union-attr]
    finally:
        await conn.close()


async def conversation_exists(conversation_id: str, user_id: str) -> bool:
    """检查会话是否存在且属于该用户."""
    conn = await _get_conn()
    try:
        row = await (
            await conn.execute(
                "SELECT 1 FROM conversations WHERE conversation_id = %s AND user_id = %s",
                (conversation_id, user_id),
            )
        ).fetchone()
        return row is not None
    finally:
        await conn.close()
