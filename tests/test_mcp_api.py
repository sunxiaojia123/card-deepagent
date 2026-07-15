"""测试 MCP 配置 CRUD API."""

from __future__ import annotations

import uuid

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


def _mcp(name, transport="stdio", **extra):
    return {
        "server_id": f"{name}-{uuid.uuid4().hex[:8]}",
        "server_name": name,
        "transport": transport,
        "command": "echo",
        **extra,
    }


@pytest.mark.asyncio
async def test_list_mcp_empty(client: AsyncClient):
    """新用户 MCP 列表为空."""
    uid = f"mcp-empty-{uuid.uuid4().hex[:6]}"
    resp = await client.get("/users/me/mcp", headers={"Authorization": f"Bearer {uid}"})
    assert resp.status_code == 200
    assert resp.json()["configs"] == []


@pytest.mark.asyncio
async def test_create_and_list_mcp(client: AsyncClient):
    """创建后可列出."""
    uid = f"mcp-crud-{uuid.uuid4().hex[:6]}"
    user = {"Authorization": f"Bearer {uid}"}
    await client.post("/users/me/mcp", json=_mcp("gate"), headers=user)
    resp = await client.get("/users/me/mcp", headers=user)
    assert resp.status_code == 200
    configs = resp.json()["configs"]
    assert len(configs) == 1
    assert configs[0]["server_name"] == "gate"
    assert configs[0]["enabled"] is True


@pytest.mark.asyncio
async def test_update_mcp(client: AsyncClient):
    """更新 MCP 配置."""
    uid = f"mcp-upd-{uuid.uuid4().hex[:6]}"
    user = {"Authorization": f"Bearer {uid}"}
    r = await client.post("/users/me/mcp", json=_mcp("test"), headers=user)
    sid = r.json()["server_id"]

    resp = await client.put(f"/users/me/mcp/{sid}", json={"enabled": False}, headers=user)
    assert resp.status_code == 200

    resp = await client.get("/users/me/mcp", headers=user)
    assert resp.json()["configs"][0]["enabled"] is False


@pytest.mark.asyncio
async def test_delete_mcp(client: AsyncClient):
    """删除 MCP 配置."""
    uid = f"mcp-del-{uuid.uuid4().hex[:6]}"
    user = {"Authorization": f"Bearer {uid}"}
    r = await client.post("/users/me/mcp", json=_mcp("to-del", "sse", url="http://example.com/sse"), headers=user)
    sid = r.json()["server_id"]

    resp = await client.delete(f"/users/me/mcp/{sid}", headers=user)
    assert resp.status_code == 200

    resp = await client.get("/users/me/mcp", headers=user)
    assert resp.json()["configs"] == []


@pytest.mark.asyncio
async def test_mcp_user_isolation(client: AsyncClient):
    """用户 A 的 MCP 配置，用户 B 看不到."""
    uid_a = f"mcp-iso-a-{uuid.uuid4().hex[:6]}"
    uid_b = f"mcp-iso-b-{uuid.uuid4().hex[:6]}"
    await client.post("/users/me/mcp", json=_mcp("alice-mcp"), headers={"Authorization": f"Bearer {uid_a}"})
    resp = await client.get("/users/me/mcp", headers={"Authorization": f"Bearer {uid_b}"})
    assert resp.json()["configs"] == []


@pytest.mark.asyncio
async def test_create_mcp_invalid_transport(client: AsyncClient):
    """transport 不合法返回 400."""
    uid = f"mcp-bad-{uuid.uuid4().hex[:6]}"
    resp = await client.post(
        "/users/me/mcp",
        json={"server_id": "bad", "transport": "invalid"},
        headers={"Authorization": f"Bearer {uid}"},
    )
    assert resp.status_code == 400

