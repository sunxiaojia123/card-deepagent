"""call_internal_api — 通用内部 API 调用 tool（唯一 tool）."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
from langchain_core.tools import tool

from src.schemas.trading_result import TradingToolResult
from src.tools.api_schema import (
    ApiParam,
    ApiSchema,
    find_api_schema,
    load_api_schemas,
)

# 所有 base skill 目录
_BASE_SKILL_DIR = Path(__file__).resolve().parent.parent.parent / "skills" / "base"

# Mock API base URL
_MOCK_BASE_URL = "http://localhost:9000"


def _collect_all_schemas() -> dict[str, ApiSchema]:
    """收集所有 base skill 的 API schema，建立 name → schema 索引."""
    index: dict[str, ApiSchema] = {}
    if not _BASE_SKILL_DIR.exists():
        return index
    for skill_dir in _BASE_SKILL_DIR.iterdir():
        if skill_dir.is_dir():
            for schema in load_api_schemas(skill_dir):
                index[schema.name] = schema
    return index


def _validate_params(schema: ApiSchema, params: dict[str, Any]) -> list[str]:
    """验证参数，返回错误列表（空列表表示通过）."""
    errors = []
    for p in schema.params:
        if p.required and p.name not in params:
            errors.append(f"缺少必填参数: {p.name}")
    return errors


@tool
async def call_internal_api(api_name: str, params: dict[str, Any]) -> TradingToolResult:
    """调用内部业务 API。

    从 Skill 中加载 API schema，校验参数，发起 HTTP 请求，
    根据 show_type 返回 TradingToolResult。

    Args:
        api_name: API 名称（对应 apis.yaml 中的 name）。
        params: API 参数（key-value 格式）。
    """
    schemas = _collect_all_schemas()
    schema = schemas.get(api_name)
    if schema is None:
        return TradingToolResult(
            summary=f"未找到 API '{api_name}'，请检查 Skill 配置。",
            show_type="none",
        )

    errors = _validate_params(schema, params)
    if errors:
        return TradingToolResult(
            summary=f"参数错误: {'; '.join(errors)}",
            show_type="none",
        )

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            if schema.method == "GET":
                resp = await client.get(
                    f"{_MOCK_BASE_URL}{schema.path}",
                    params=params,
                )
            else:
                resp = await client.post(
                    f"{_MOCK_BASE_URL}{schema.path}",
                    json=params,
                )
            resp.raise_for_status()
            body = resp.json()
    except Exception as exc:
        return TradingToolResult(
            summary=f"API 请求失败: {exc}",
            show_type="none",
        )

    code = body.get("code", -1)
    message = body.get("message", "")
    data = body.get("data")

    if code != 0:
        return TradingToolResult(
            summary=f"[{api_name}] 错误 (code={code}): {message}",
            show_type="none",
        )

    if schema.show_type == "card":
        return TradingToolResult(
            summary=f"[{api_name}] 执行成功，已展示结果卡片。",
            show_type="card",
            data=data if isinstance(data, dict) else {"result": data},
        )
    else:
        return TradingToolResult(
            summary=f"[{api_name}] 返回数据: {json.dumps(data, ensure_ascii=False)}",
            show_type="text",
        )
