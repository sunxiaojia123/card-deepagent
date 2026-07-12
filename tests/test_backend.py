"""测试 User-scoped Backend — StoreBackend 按 user_id 隔离文件."""

from __future__ import annotations

import pytest
from deepagents.backends import StoreBackend
from langgraph.store.memory import InMemoryStore


def _store_backend(user_id: str) -> StoreBackend:
    """创建一个按 user_id namespace 隔离的 StoreBackend."""
    return StoreBackend(
        store=InMemoryStore(),
        namespace=lambda rt=None, uid=user_id: (uid, "skills"),
    )


def _content(result) -> str:
    """从 aread 返回值提取文件内容字符串."""
    if result.error:
        return ""
    return result.file_data["content"]


@pytest.mark.asyncio
async def test_user_isolation_write_read():
    """不同 user_id 写入同名文件互不覆盖."""
    be_a = _store_backend("user-a")
    be_b = _store_backend("user-b")

    await be_a.awrite("/skills/user/config.md", "alice-config")
    await be_b.awrite("/skills/user/config.md", "bob-config")

    assert _content(await be_a.aread("/skills/user/config.md")) == "alice-config"
    assert _content(await be_b.aread("/skills/user/config.md")) == "bob-config"


@pytest.mark.asyncio
async def test_same_user_read_write():
    """同一 user_id 写入后可读回."""
    be = _store_backend("user-x")
    await be.awrite("/skills/user/strategy.md", "# Strategy\nbuy low sell high")
    content = _content(await be.aread("/skills/user/strategy.md"))
    assert "# Strategy" in content


@pytest.mark.asyncio
async def test_multiple_files_per_user():
    """同一用户可管理多个 Skill 文件."""
    be = _store_backend("user-m")
    await be.awrite("/skills/user/skill-a.md", "A")
    await be.awrite("/skills/user/skill-b.md", "B")
    assert _content(await be.aread("/skills/user/skill-a.md")) == "A"
    assert _content(await be.aread("/skills/user/skill-b.md")) == "B"


@pytest.mark.asyncio
async def test_different_users_independent_namespace():
    """不同用户写入不同文件，各自独立."""
    be_a = _store_backend("alice")
    be_b = _store_backend("bob")

    await be_a.awrite("/skills/user/a.md", "a-content")
    await be_b.awrite("/skills/user/b.md", "b-content")

    assert _content(await be_a.aread("/skills/user/a.md")) == "a-content"
    assert _content(await be_a.aread("/skills/user/b.md")) == ""


@pytest.mark.asyncio
async def test_overwrite_same_user():
    """同一用户覆盖写入后读取最新内容."""
    be = _store_backend("user-o")
    await be.awrite("/skills/user/note.md", "v1")

    # 验证第一次写入
    assert _content(await be.aread("/skills/user/note.md")) == "v1"

    # awrite 不会覆盖已有文件，需用 aedit
    await be.aedit("/skills/user/note.md", "v1", "v2")
    assert _content(await be.aread("/skills/user/note.md")) == "v2"
