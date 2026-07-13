"""测试 Skill 文件加载."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.middleware.skills import SkillsMiddleware


def _runtime():
    rt = MagicMock()
    rt.stream_writer = MagicMock()
    return rt


def _config():
    return {"configurable": {"thread_id": "test"}}



@pytest.mark.asyncio
async def test_load_base_skills():
    """SkillsMiddleware 能加载 skills/base/ 下的 SKILL.md 文件."""
    backend = FilesystemBackend(root_dir="skills", virtual_mode=True)
    middleware = SkillsMiddleware(
        backend=backend,
        sources=["/base/"],
    )

    state = {"messages": [], "files": {}}
    result = middleware.before_agent(state, runtime=_runtime(), config=_config())
    metadata = result.get("skills_metadata", [])
    assert len(metadata) >= 1

    names = [m.get("name") for m in metadata]
    assert "order-guide" in names or "market-info" in names


@pytest.mark.asyncio
async def test_load_both_base_skills():
    """SkillsMiddleware 加载两个 base skill."""
    backend = FilesystemBackend(root_dir="skills", virtual_mode=True)
    middleware = SkillsMiddleware(
        backend=backend,
        sources=["/base/"],
    )

    state = {"messages": [], "files": {}}
    result = middleware.before_agent(state, runtime=_runtime(), config=_config())
    metadata = result.get("skills_metadata", [])
    names = {m.get("name") for m in metadata}
    assert "order-guide" in names
    assert "market-info" in names


@pytest.mark.asyncio
async def test_skill_metadata_structure():
    """Skill metadata 包含 name 和 description."""
    backend = FilesystemBackend(root_dir="skills", virtual_mode=True)
    middleware = SkillsMiddleware(
        backend=backend,
        sources=["/base/"],
    )

    state = {"messages": [], "files": {}}
    result = middleware.before_agent(state, runtime=_runtime(), config=_config())
    metadata = result.get("skills_metadata", [])

    for m in metadata:
        assert "name" in m
        assert "description" in m
        assert "path" in m


@pytest.mark.asyncio
async def test_order_guide_has_allowed_tools():
    """order-guide skill 的 YAML frontmatter 包含 allowed_tools."""
    backend = FilesystemBackend(root_dir="skills", virtual_mode=True)
    middleware = SkillsMiddleware(backend=backend, sources=["/base/"])

    state = {"messages": [], "files": {}}
    result = middleware.before_agent(state, runtime=_runtime(), config=_config())
    metadata = {m.get("name"): m for m in result.get("skills_metadata", [])}

    order_guide = metadata.get("order-guide")
    assert order_guide is not None
    # YAML frontmatter 中配置的 allowed_tools
    assert "query_positions" in order_guide.get("allowed_tools", "")


def test_skill_files_exist():
    """验证物理 SKILL.md 文件存在."""
    import os
    base = os.path.join(os.path.dirname(__file__), "..", "skills", "base")
    assert os.path.isfile(os.path.join(base, "order-guide", "SKILL.md"))
    assert os.path.isfile(os.path.join(base, "market-info", "SKILL.md"))
    assert os.path.isfile(os.path.join(base, "gift-card", "SKILL.md"))


def test_apis_yaml_exist():
    """验证 apis.yaml 文件存在."""
    import os
    base = os.path.join(os.path.dirname(__file__), "..", "skills", "base")
    assert os.path.isfile(os.path.join(base, "order-guide", "apis.yaml"))
    assert os.path.isfile(os.path.join(base, "market-info", "apis.yaml"))
    assert os.path.isfile(os.path.join(base, "gift-card", "apis.yaml"))


def test_load_gift_card_schemas():
    """加载礼品卡 Skill 的 API schema."""
    import os
    from src.tools.api_schema import load_api_schemas

    skill_dir = os.path.join(os.path.dirname(__file__), "..", "skills", "base", "gift-card")
    schemas = load_api_schemas(skill_dir)
    assert len(schemas) == 4
    names = {s.name for s in schemas}
    assert "query_gift_card" in names
    assert "create_gift_card" in names
    assert "top_up_gift_card" in names
    assert "transfer_gift_card" in names

    # 验证 query_gift_card 的 schema
    q = next(s for s in schemas if s.name == "query_gift_card")
    assert q.show_type == "card"
    assert q.method == "GET"
    assert len(q.params) == 1
    assert q.params[0].name == "card_no"
    assert q.params[0].required is True


def test_load_order_guide_schemas():
    """加载订单 Skill 的 API schema."""
    import os
    from src.tools.api_schema import load_api_schemas

    skill_dir = os.path.join(os.path.dirname(__file__), "..", "skills", "base", "order-guide")
    schemas = load_api_schemas(skill_dir)
    assert len(schemas) == 3


def test_load_market_schemas():
    """加载行情 Skill 的 API schema，包含 text 类型."""
    import os
    from src.tools.api_schema import load_api_schemas

    skill_dir = os.path.join(os.path.dirname(__file__), "..", "skills", "base", "market-info")
    schemas = load_api_schemas(skill_dir)
    assert len(schemas) == 2
    info = next(s for s in schemas if s.name == "query_market_info")
    assert info.show_type == "text"
