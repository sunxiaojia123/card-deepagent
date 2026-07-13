"""call_internal_api — 通用内部 API 调用 tool."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import requests
from langchain_core.tools import tool

from config.settings import settings
from src.schemas.trading_result import TradingToolResult
from src.tools.api_schema import ApiSchema, load_api_schemas

_BASE_SKILL_DIR = Path(__file__).resolve().parent.parent.parent / "skills" / "base"


def _collect_all_schemas() -> dict[str, ApiSchema]:
    index: dict[str, ApiSchema] = {}
    if not _BASE_SKILL_DIR.exists():
        return index
    for skill_dir in _BASE_SKILL_DIR.iterdir():
        if skill_dir.is_dir():
            for schema in load_api_schemas(skill_dir):
                index[schema.name] = schema
    return index


def _http_request(url: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
    """同步 HTTP 请求，由 asyncio.to_thread 调用."""
    if method == "GET":
        resp = requests.get(url, params=params, timeout=30)
    else:
        resp = requests.post(url, json=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _validate_params(schema: ApiSchema, params: dict[str, Any]) -> list[str]:
    errors = []
    for p in schema.params:
        if p.required and p.name not in params:
            errors.append(f"缺少必填参数: {p.name}")
    return errors


@tool
async def call_internal_api(api_name: str, params: dict[str, Any]) -> TradingToolResult:
    """调用内部业务 API。

    根据 Skill 中定义的 API schema，校验参数，向内部 API 发起 HTTP 请求。
    开发阶段指向 Mock 服务 (MOCK_API_URL)，生产切换真实地址即可。

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
        url = f"{settings.mock_api_url}{schema.path}"
        body = await asyncio.to_thread(
            _http_request, url, schema.method, params
        )
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
