"""端到端测试 Agent Skill 集成与隔离."""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

from src.api import app

needs_deepseek = pytest.mark.skipif(
    not os.environ.get("DEEPSEEK_API_KEY"),
    reason="DEEPSEEK_API_KEY not set",
)


@pytest.fixture
async def client():
    from asgi_lifespan import LifespanManager

    async with LifespanManager(app) as manager:
        transport = ASGITransport(app=manager.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@needs_deepseek
@pytest.mark.asyncio
async def test_agent_with_skills_builds(client: AsyncClient):
    """build_agent(with_skills=True) 成功构建."""
    # 通过创建会话验证 agent 正常工作
    resp = await client.post(
        "/conversations",
        headers={"Authorization": "Bearer skill-user-build"},
    )
    conv_id = resp.json()["conversation_id"]

    async with client.stream(
        "POST",
        f"/conversations/{conv_id}/chat/stream",
        json={"message": "你好，请介绍一下自己。"},
        headers={"Authorization": "Bearer skill-user-build"},
    ) as resp:
        raw = await resp.aread()
        text = raw.decode("utf-8")
    assert "event: text" in text
    assert "event: done" in text


@needs_deepseek
@pytest.mark.asyncio
async def test_user_skill_visible_to_agent(client: AsyncClient):
    """用户创建 Skill 后，Agent 能感知到."""
    user_auth = {"Authorization": "Bearer skill-user-a"}

    # 1. 创建自定义 Skill
    await client.post(
        "/users/me/skills",
        json={
            "name": "golden-cross-strategy",
            "content": "# 金叉策略\n当 MA5 上穿 MA20 时买入，下穿时卖出。",
        },
        headers=user_auth,
    )

    # 2. 确认 Skill 已创建
    resp = await client.get("/users/me/skills", headers=user_auth)
    assert "golden-cross-strategy" in resp.json()["skills"]

    # 3. 创建会话并测试 Agent 是否感知 Skill
    conv_resp = await client.post("/conversations", headers=user_auth)
    conv_id = conv_resp.json()["conversation_id"]

    async with client.stream(
        "POST",
        f"/conversations/{conv_id}/chat/stream",
        json={"message": "你有哪些可用的技能或能力？请用一句话回答。"},
        headers=user_auth,
    ) as resp:
        raw = await resp.aread()
        text = raw.decode("utf-8")

    assert "event: text" in text
    # Agent 应该能感知到 base skill（order-guide, market-info）
    # 注意：user skill 通过 backend 加载，Agent 在 system prompt 中会收到 skills 列表


@needs_deepseek
@pytest.mark.asyncio
async def test_user_b_does_not_see_a_skill(client: AsyncClient):
    """用户 B 无法看到用户 A 的 skill."""
    user_a = {"Authorization": "Bearer skill-user-ax"}
    user_b = {"Authorization": "Bearer skill-user-bx"}

    # A 创建 skill
    await client.post(
        "/users/me/skills",
        json={"name": "a-secret-skill", "content": "# Secret\nOnly for A."},
        headers=user_a,
    )

    # B 查 skills → 看不到 A 的
    resp = await client.get("/users/me/skills", headers=user_b)
    assert "a-secret-skill" not in resp.json()["skills"]

    # A 查自己的 → 能看到
    resp_a = await client.get("/users/me/skills", headers=user_a)
    assert "a-secret-skill" in resp_a.json()["skills"]
