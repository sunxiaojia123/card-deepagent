"""测试 FastAPI 对话接口."""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from src.api import _lifespan, app

needs_deepseek = pytest.mark.skipif(
    not os.environ.get("DEEPSEEK_API_KEY"),
    reason="DEEPSEEK_API_KEY not set",
)


@pytest.fixture
async def client():
    """带 lifespan 的异步 HTTP 客户端."""
    async with LifespanManager(app) as manager:
        transport = ASGITransport(app=manager.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


def _parse_sse_lines(lines: list[str]) -> list[dict]:
    """解析 SSE 行列表为 event dict 列表."""
    events = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("event: "):
            event_type = line.removeprefix("event: ")
            if i + 1 < len(lines) and lines[i + 1].startswith("data: "):
                data_str = lines[i + 1].removeprefix("data: ")
                data = json.loads(data_str)
                events.append({"event": event_type, "data": data})
                i += 2
            else:
                i += 1
        else:
            i += 1
    return events


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    """GET /health 返回 200."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_chat_stream_missing_message(client: AsyncClient):
    """空 message 返回 400."""
    resp = await client.post(
        "/conversations/c1/chat/stream",
        json={"message": ""},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_chat_stream_missing_body_message(client: AsyncClient):
    """body 缺少 message 字段返回 400."""
    resp = await client.post(
        "/conversations/c1/chat/stream",
        json={},
    )
    assert resp.status_code == 400


@needs_deepseek
@pytest.mark.asyncio
async def test_chat_stream_sse_response(client: AsyncClient):
    """SSE 流式返回 text + done 事件."""
    r = await client.post("/conversations", headers={"Authorization": "Bearer user-api-test"})
    conv_id = r.json()["conversation_id"]

    async with client.stream(
        "POST",
        f"/conversations/{conv_id}/chat/stream",
        json={"message": "用一句话介绍比特币。"},
        headers={"Authorization": "Bearer user-api-test"},
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")

        raw = await resp.aread()
        text = raw.decode("utf-8")
        lines = [l for l in text.splitlines() if l]
        events = _parse_sse_lines(lines)

    assert len(events) >= 2
    text_events = [e for e in events if e["event"] == "text"]
    assert len(text_events) > 0
    assert events[-1]["event"] == "done"


@needs_deepseek
@pytest.mark.asyncio
async def test_chat_stream_text_content(client: AsyncClient):
    """SSE 流式 text 事件的 content 拼接成完整回复."""
    r = await client.post("/conversations", headers={"Authorization": "Bearer user-api-text"})
    conv_id = r.json()["conversation_id"]

    async with client.stream(
        "POST",
        f"/conversations/{conv_id}/chat/stream",
        json={"message": "回复一个：好。"},
        headers={"Authorization": "Bearer user-api-text"},
    ) as resp:
        assert resp.status_code == 200
        raw = await resp.aread()
        text = raw.decode("utf-8")
        lines = [l for l in text.splitlines() if l]
        events = _parse_sse_lines(lines)

    full_text = "".join(e["data"]["content"] for e in events if e["event"] == "text")
    assert len(full_text) > 0


# ── 会话 CRUD 测试 ──


@pytest.mark.asyncio
async def test_create_conversation(client: AsyncClient):
    """POST /conversations 创建新会话返回 conversation_id."""
    resp = await client.post(
        "/conversations",
        headers={"Authorization": "Bearer user-crud"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "conversation_id" in data
    assert len(data["conversation_id"]) == 32  # uuid4 hex
    assert data["user_id"] == "user-crud"
    assert "created_at" in data


@pytest.mark.asyncio
async def test_list_conversations(client: AsyncClient):
    """GET /conversations 列出用户会话."""
    # 先创建两个
    await client.post("/conversations", headers={"Authorization": "Bearer user-list"})
    await client.post("/conversations", headers={"Authorization": "Bearer user-list"})

    resp = await client.get(
        "/conversations",
        headers={"Authorization": "Bearer user-list"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["conversations"]) >= 2


@needs_deepseek
@pytest.mark.asyncio
async def test_get_conversation_history(client: AsyncClient):
    """GET /conversations/{id}/history 返回对话历史."""
    # 先创建会话
    r = await client.post(
        "/conversations",
        headers={"Authorization": "Bearer user-hist"},
    )
    conv_id = r.json()["conversation_id"]

    # 发送一条消息
    async with client.stream(
        "POST",
        f"/conversations/{conv_id}/chat/stream",
        json={"message": "你好，我是小明。"},
        headers={"Authorization": "Bearer user-hist"},
    ) as resp:
        await resp.aread()

    # 查历史
    resp = await client.get(
        f"/conversations/{conv_id}/history",
        headers={"Authorization": "Bearer user-hist"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "messages" in data
    assert len(data["messages"]) >= 2  # user + assistant


@pytest.mark.asyncio
async def test_empty_history(client: AsyncClient):
    """无对话的会话返回空历史."""
    r = await client.post(
        "/conversations",
        headers={"Authorization": "Bearer user-empty-hist"},
    )
    conv_id = r.json()["conversation_id"]

    resp = await client.get(
        f"/conversations/{conv_id}/history",
        headers={"Authorization": "Bearer user-empty-hist"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["messages"] == []


@needs_deepseek
@pytest.mark.asyncio
async def test_history_roles(client: AsyncClient):
    """历史消息包含 user 和 assistant 角色."""
    r = await client.post(
        "/conversations",
        headers={"Authorization": "Bearer user-roles"},
    )
    conv_id = r.json()["conversation_id"]

    async with client.stream(
        "POST",
        f"/conversations/{conv_id}/chat/stream",
        json={"message": "回复一个字：好。"},
        headers={"Authorization": "Bearer user-roles"},
    ) as resp:
        await resp.aread()

    resp = await client.get(
        f"/conversations/{conv_id}/history",
        headers={"Authorization": "Bearer user-roles"},
    )
    data = resp.json()
    roles = [m["role"] for m in data["messages"]]
    assert "user" in roles
    assert "assistant" in roles


@pytest.mark.asyncio
async def test_user_isolation_list_conversations(client: AsyncClient):
    """用户 A 看不到用户 B 的会话."""
    # A 创建会话
    r_a = await client.post("/conversations", headers={"Authorization": "Bearer user-a"})
    conv_a = r_a.json()["conversation_id"]

    # B 查看自己的列表，不应看到 A 的
    r_b = await client.get("/conversations", headers={"Authorization": "Bearer user-b"})
    b_ids = [c["conversation_id"] for c in r_b.json()["conversations"]]
    assert conv_a not in b_ids


@pytest.mark.asyncio
async def test_user_cannot_access_others_history(client: AsyncClient):
    """用户 A 无法访问用户 B 的会话历史."""
    # A 创建会话
    r_a = await client.post("/conversations", headers={"Authorization": "Bearer user-a-hist"})
    conv_a = r_a.json()["conversation_id"]

    # B 尝试访问 A 的会话历史 → 404
    resp = await client.get(
        f"/conversations/{conv_a}/history",
        headers={"Authorization": "Bearer user-b-hist"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_user_cannot_chat_in_others_conversation(client: AsyncClient):
    """用户 A 无法在用户 B 的会话中发消息."""
    # A 创建会话
    r_a = await client.post("/conversations", headers={"Authorization": "Bearer user-a-chat"})
    conv_a = r_a.json()["conversation_id"]

    # B 尝试在 A 的会话中发消息 → 404
    resp = await client.post(
        f"/conversations/{conv_a}/chat/stream",
        json={"message": "hello"},
        headers={"Authorization": "Bearer user-b-chat"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_nonexistent_conversation_returns_404(client: AsyncClient):
    """不存在的会话返回 404."""
    resp = await client.get(
        "/conversations/deadbeef1234/history",
        headers={"Authorization": "Bearer someone"},
    )
    assert resp.status_code == 404
