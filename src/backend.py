"""User-scoped Backend — 按 user_id 隔离 Skill 文件."""

from __future__ import annotations

from dataclasses import dataclass

from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from langgraph.store.memory import InMemoryStore

# 全局共享 Store，通过 namespace 区分用户
_store = InMemoryStore()


def _user_backend(user_id: str) -> StoreBackend:
    """为指定用户创建一个 StoreBackend 实例."""
    return StoreBackend(
        store=_store,
        namespace=lambda rt=None, uid=user_id: (uid, "skills"),
    )


def create_user_scoped_backend(runtime):
    """创建按 user_id 隔离的 CompositeBackend。

    /skills/base/ → StateBackend（全局公共，各用户共享）
    /skills/user/ → StoreBackend（按 user_id namespace 隔离）
    """
    user_id = runtime.context["user_id"]
    return CompositeBackend(
        default=StateBackend(),
        routes={
            "/skills/user/": _user_backend(user_id),
        },
    )


@dataclass
class SkillInfo:
    name: str
    content: str


# ── Skill CRUD helpers ──


def _skill_path(name: str) -> str:
    """将 skill 名称转换为 StoreBackend 路径."""
    safe = name.replace("..", "").replace("/", "-")
    return f"/skills/user/{safe}.md"


async def list_user_skills(user_id: str) -> list[str]:
    """列出用户的所有 skill 名称."""
    be = _user_backend(user_id)
    result = await be.als("/skills/user/")
    names = []
    for f in result.entries:
        fname = f.get("path", "")
        if fname.endswith(".md"):
            names.append(fname.replace("/skills/user/", "").replace(".md", ""))
    return names


async def get_user_skill(user_id: str, name: str) -> str | None:
    """获取用户 skill 内容，不存在返回 None."""
    be = _user_backend(user_id)
    result = await be.aread(_skill_path(name))
    if result.error:
        return None
    return result.file_data["content"]


async def create_user_skill(user_id: str, name: str, content: str) -> None:
    """创建用户 skill 文件."""
    be = _user_backend(user_id)
    await be.awrite(_skill_path(name), content)


async def update_user_skill(user_id: str, name: str, content: str) -> bool:
    """更新用户 skill 文件，返回是否成功."""
    be = _user_backend(user_id)
    existing = await get_user_skill(user_id, name)
    if existing is None:
        return False
    await be.aedit(_skill_path(name), existing, content)
    return True


async def delete_user_skill(user_id: str, name: str) -> bool:
    """删除用户 skill 文件（通过写入空内容实现），返回是否成功."""
    existing = await get_user_skill(user_id, name)
    if existing is None:
        return False
    # InMemoryStore/StoreBackend 不支持直接删除，用 aedit 清空
    be = _user_backend(user_id)
    await be.aedit(_skill_path(name), existing, "")
    return True
