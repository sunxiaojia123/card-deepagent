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
