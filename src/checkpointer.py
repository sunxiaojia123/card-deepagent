"""Postgres checkpointer — 基于 LangGraph AsyncPostgresSaver 的对话持久化."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from config.settings import settings


@asynccontextmanager
async def checkpointer_session(
    conn_string: str | None = None,
) -> AsyncGenerator[AsyncPostgresSaver, None]:
    """创建 AsyncPostgresSaver 并自动管理连接生命周期。

    Usage:
        async with checkpointer_session() as saver:
            agent = create_deep_agent(checkpointer=saver, ...)
            await agent.ainvoke(...)
    """
    uri = conn_string or settings.postgres_uri
    async with AsyncPostgresSaver.from_conn_string(uri) as saver:
        await saver.setup()
        yield saver
