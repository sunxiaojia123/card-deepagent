"""API Schema 加载 — 从 Skill 目录加载 apis.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ApiParam:
    name: str
    type: str  # string | number | boolean
    required: bool = False
    default: str | int | float | bool | None = None
    description: str = ""


@dataclass
class ApiSchema:
    name: str
    path: str
    method: str
    show_type: str  # card | text | none
    description: str = ""
    params: list[ApiParam] = field(default_factory=list)


def load_api_schemas(skill_dir: str | Path) -> list[ApiSchema]:
    """从 Skill 目录加载 apis.yaml，返回该 Skill 的所有 API schema 列表."""
    yaml_path = Path(skill_dir) / "apis.yaml"
    if not yaml_path.exists():
        return []

    with open(yaml_path) as f:
        data = yaml.safe_load(f)

    if not data or "apis" not in data:
        return []

    schemas = []
    for item in data["apis"]:
        params = [
            ApiParam(
                name=p["name"],
                type=p.get("type", "string"),
                required=p.get("required", False),
                default=p.get("default"),
                description=p.get("description", ""),
            )
            for p in item.get("params", [])
        ]
        schemas.append(ApiSchema(
            name=item["name"],
            path=item["path"],
            method=item.get("method", "POST"),
            show_type=item.get("show_type", "text"),
            description=item.get("description", ""),
            params=params,
        ))
    return schemas


def find_api_schema(api_name: str, skill_dirs: list[str]) -> ApiSchema | None:
    """在所有 Skill 目录中查找指定 API 的 schema."""
    for d in skill_dirs:
        for schema in load_api_schemas(d):
            if schema.name == api_name:
                return schema
    return None
