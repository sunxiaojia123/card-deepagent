"""测试 Postgres checkpointer 的读写与隔离."""

from __future__ import annotations

import uuid

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.checkpointer import checkpointer_session


def _config(thread_id: str | None = None, checkpoint_ns: str = "") -> dict:
    tid = thread_id or uuid.uuid4().hex
    return {"configurable": {"thread_id": tid, "checkpoint_ns": checkpoint_ns}}


def _checkpoint(messages: list, v: int = 1) -> dict:
    return {
        "v": v,
        "id": uuid.uuid4().hex,
        "ts": "2025-01-01T00:00:00Z",
        "channel_values": {"messages": messages},
        "channel_versions": {"messages": str(v)},
        "versions_seen": {},
    }


@pytest.mark.asyncio
async def test_checkpoint_write_and_read():
    """写入 checkpoint 后可通过同一 thread_id 读回 messages."""
    config = _config()
    messages = [HumanMessage(content="你好"), AIMessage(content="你好，有什么可以帮您？")]

    async with checkpointer_session() as saver:
        result = await saver.aput(config, _checkpoint(messages), {}, {"messages": "1"})

        # 通过返回的 checkpoint_id 精确读取
        state = await saver.aget_tuple(result)
        assert state is not None
        restored = state.checkpoint["channel_values"].get("messages", [])
        assert len(restored) == 2
        assert restored[0].content == "你好"
        assert restored[1].content == "你好，有什么可以帮您？"


@pytest.mark.asyncio
async def test_different_thread_isolation():
    """不同 thread_id 的 checkpoint 互不干扰."""
    config_a = _config()
    config_b = _config()

    async with checkpointer_session() as saver:
        result_a = await saver.aput(
            config_a,
            _checkpoint([HumanMessage(content="A的消息")]),
            {},
            {"messages": "1"},
        )
        result_b = await saver.aput(
            config_b,
            _checkpoint([HumanMessage(content="B的消息")]),
            {},
            {"messages": "1"},
        )

        state_a = await saver.aget_tuple(result_a)
        state_b = await saver.aget_tuple(result_b)

        msgs_a = state_a.checkpoint["channel_values"]["messages"]
        msgs_b = state_b.checkpoint["channel_values"]["messages"]

        assert msgs_a[0].content == "A的消息"
        assert msgs_b[0].content == "B的消息"


@pytest.mark.asyncio
async def test_multi_turn_same_thread():
    """同一 thread_id 多次写入后，可按 thread 读取最新 checkpoint."""
    tid = uuid.uuid4().hex
    config = _config(tid)

    async with checkpointer_session() as saver:
        await saver.aput(
            config,
            _checkpoint([
                HumanMessage(content="第一轮"),
                AIMessage(content="第一轮回復"),
            ]),
            {},
            {"messages": "1"},
        )
        result2 = await saver.aput(
            config,
            _checkpoint([
                HumanMessage(content="第一轮"),
                AIMessage(content="第一轮回復"),
                HumanMessage(content="第二轮"),
                AIMessage(content="第二轮回復"),
            ],
            v=2),
            {},
            {"messages": "2"},
        )

        # 按返回的 checkpoint_id 精确读取第二轮
        state = await saver.aget_tuple(result2)
        msgs = state.checkpoint["channel_values"]["messages"]
        assert len(msgs) == 4
        assert msgs[2].content == "第二轮"
        assert msgs[3].content == "第二轮回復"


@pytest.mark.asyncio
async def test_unused_thread_returns_none():
    """不存在的 thread_id 返回 None."""
    async with checkpointer_session() as saver:
        state = await saver.aget_tuple(_config("nonexistent-thread"))
        assert state is None
