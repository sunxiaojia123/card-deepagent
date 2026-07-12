"""测试 User Skill CRUD API."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from src.api import app


@pytest.fixture
async def client():
    """带 lifespan 的异步 HTTP 客户端."""
    from asgi_lifespan import LifespanManager

    async with LifespanManager(app) as manager:
        transport = ASGITransport(app=manager.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.mark.asyncio
async def test_list_skills_empty(client: AsyncClient):
    """新用户 skills 列表为空."""
    resp = await client.get(
        "/users/me/skills",
        headers={"Authorization": "Bearer user-skills-new"},
    )
    assert resp.status_code == 200
    assert resp.json()["skills"] == []


@pytest.mark.asyncio
async def test_create_and_list_skill(client: AsyncClient):
    """创建 skill 后可列出."""
    await client.post(
        "/users/me/skills",
        json={"name": "my-strategy", "content": "# Strategy\nBuy low!"},
        headers={"Authorization": "Bearer user-a"},
    )
    resp = await client.get(
        "/users/me/skills",
        headers={"Authorization": "Bearer user-a"},
    )
    assert resp.status_code == 200
    assert "my-strategy" in resp.json()["skills"]


@pytest.mark.asyncio
async def test_update_skill(client: AsyncClient):
    """创建后更新 skill."""
    user = {"Authorization": "Bearer user-updater"}
    await client.post(
        "/users/me/skills",
        json={"name": "test-skill", "content": "v1"},
        headers=user,
    )
    resp = await client.put(
        "/users/me/skills/test-skill",
        json={"content": "v2-updated"},
        headers=user,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "updated"


@pytest.mark.asyncio
async def test_update_nonexistent_skill(client: AsyncClient):
    """更新不存在的 skill 返回 404."""
    resp = await client.put(
        "/users/me/skills/nonexistent",
        json={"content": "x"},
        headers={"Authorization": "Bearer user-upd"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_skill(client: AsyncClient):
    """创建后删除 skill."""
    user = {"Authorization": "Bearer user-del"}
    await client.post(
        "/users/me/skills",
        json={"name": "to-delete", "content": "tmp"},
        headers=user,
    )
    resp = await client.delete(
        "/users/me/skills/to-delete",
        headers=user,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"


@pytest.mark.asyncio
async def test_delete_nonexistent_skill(client: AsyncClient):
    """删除不存在的 skill 返回 404."""
    resp = await client.delete(
        "/users/me/skills/nonexistent",
        headers={"Authorization": "Bearer user-del2"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_user_skill_isolation(client: AsyncClient):
    """用户 A 创建的 skill，用户 B 看不到."""
    await client.post(
        "/users/me/skills",
        json={"name": "alice-skill", "content": "Alice's skill"},
        headers={"Authorization": "Bearer alice"},
    )
    resp_b = await client.get(
        "/users/me/skills",
        headers={"Authorization": "Bearer bob"},
    )
    assert "alice-skill" not in resp_b.json()["skills"]


@pytest.mark.asyncio
async def test_create_skill_missing_name(client: AsyncClient):
    """缺少 name 返回 400."""
    resp = await client.post(
        "/users/me/skills",
        json={"content": "no name"},
        headers={"Authorization": "Bearer u"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_create_skill_missing_content(client: AsyncClient):
    """缺少 content 返回 400."""
    resp = await client.post(
        "/users/me/skills",
        json={"name": "x"},
        headers={"Authorization": "Bearer u"},
    )
    assert resp.status_code == 400
