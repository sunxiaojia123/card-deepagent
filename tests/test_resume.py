"""测试 Resume API."""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from src.api import app


@pytest.fixture
async def client():
    from asgi_lifespan import LifespanManager

    async with LifespanManager(app) as manager:
        transport = ASGITransport(app=manager.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.mark.asyncio
async def test_resume_missing_option_id(client: AsyncClient):
    """option_id 为空返回 400."""
    resp = await client.post(
        "/conversations/c1/resume",
        json={"option_id": ""},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_resume_nonexistent_conversation(client: AsyncClient):
    """不存在的会话返回 404."""
    resp = await client.post(
        "/conversations/deadbeef/resume",
        json={"option_id": "spot"},
        headers={"Authorization": "Bearer user-resume"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_resume_user_isolation(client: AsyncClient):
    """用户 A 的会话，用户 B 不能 resume."""
    # 创建会话
    r = await client.post("/conversations", headers={"Authorization": "Bearer user-a-resume"})
    conv_id = r.json()["conversation_id"]

    # B 尝试 resume
    resp = await client.post(
        f"/conversations/{conv_id}/resume",
        json={"option_id": "spot"},
        headers={"Authorization": "Bearer user-b-resume"},
    )
    assert resp.status_code == 404
