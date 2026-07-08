"""TradingContext — 用户上下文类型，用于 create_deep_agent 的 context_schema."""

from __future__ import annotations

from typing import TypedDict


class TradingContext(TypedDict, total=False):
    """交易助手用户上下文。

    total=False 表示所有字段均为可选，每次请求按需传入。
    """

    user_id: str
    conversation_id: str
    enabled_skills: list[str] | None
    mcp_server_ids: list[str] | None
    tenant_id: str | None


def build_context(
    user_id: str,
    conversation_id: str,
    *,
    enabled_skills: list[str] | None = None,
    mcp_server_ids: list[str] | None = None,
    tenant_id: str | None = None,
) -> TradingContext:
    """构造 TradingContext 的便捷函数。

    Args:
        user_id: 当前用户 ID（必填）。
        conversation_id: 当前会话 ID（必填）。
        enabled_skills: 可选的能力白名单。
        mcp_server_ids: 该用户启用的 MCP server ID 列表。
        tenant_id: 可选的多租户标识。

    Returns:
        填充了所有传入字段的 TradingContext。
    """
    ctx: TradingContext = {
        "user_id": user_id,
        "conversation_id": conversation_id,
    }
    if enabled_skills is not None:
        ctx["enabled_skills"] = enabled_skills
    if mcp_server_ids is not None:
        ctx["mcp_server_ids"] = mcp_server_ids
    if tenant_id is not None:
        ctx["tenant_id"] = tenant_id
    return ctx
