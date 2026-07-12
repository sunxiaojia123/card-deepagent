"""User-scoped Backend — 按 user_id 隔离 Skill 文件，JSON 文件持久化."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from langgraph.store.memory import InMemoryStore

# 持久化文件路径
_DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "skills.json"

# 全局共享 Store，通过 namespace 区分用户
_store = InMemoryStore()


def _load_skills_from_disk() -> dict[str, dict[str, str]]:
    """从 JSON 文件加载所有 skill 数据."""
    if not _DATA_FILE.exists():
        return {}
    try:
        with open(_DATA_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_skills_to_disk(data: dict[str, dict[str, str]]) -> None:
    """保存所有 skill 数据到 JSON 文件."""
    _DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _DATA_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(_DATA_FILE)


async def _restore_from_disk() -> None:
    """启动时从磁盘恢复 skill 数据到 InMemoryStore."""
    data = _load_skills_from_disk()
    for user_id, skills in data.items():
        be = _user_backend(user_id)
        for name, content in skills.items():
            await be.awrite(_skill_path(name), content)


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
    """列出用户的所有 skill 名称（排除空内容文件，已删除标记）."""
    be = _user_backend(user_id)
    result = await be.als("/skills/user/")
    names = []
    for f in result.entries:
        fname = f.get("path", "")
        if fname.endswith(".md"):
            name = fname.replace("/skills/user/", "").replace(".md", "")
            content = await get_user_skill(user_id, name)
            if content:
                names.append(name)
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
    # 持久化
    data = _load_skills_from_disk()
    data.setdefault(user_id, {})[name] = content
    _save_skills_to_disk(data)


async def update_user_skill(user_id: str, name: str, content: str) -> bool:
    """更新用户 skill 文件，返回是否成功."""
    be = _user_backend(user_id)
    existing = await get_user_skill(user_id, name)
    if existing is None:
        return False
    await be.aedit(_skill_path(name), existing, content)
    # 持久化
    data = _load_skills_from_disk()
    if user_id in data:
        data[user_id][name] = content
        _save_skills_to_disk(data)
    return True


async def delete_user_skill(user_id: str, name: str) -> bool:
    """删除用户 skill 文件（清空内容），返回是否成功."""
    existing = await get_user_skill(user_id, name)
    if existing is None:
        return False
    be = _user_backend(user_id)
    await be.aedit(_skill_path(name), existing, "")
    # 持久化
    data = _load_skills_from_disk()
    if user_id in data and name in data[user_id]:
        del data[user_id][name]
        if not data[user_id]:
            del data[user_id]
        _save_skills_to_disk(data)
    return True
