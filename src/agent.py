"""基础 Agent — build_agent() 工厂函数 + 交易助手 System Prompt."""

from __future__ import annotations

from deepagents import create_deep_agent
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver

from config.settings import settings
from src.backend import create_user_scoped_backend
from src.context import TradingContext

TRADING_ORCHESTRATOR_PROMPT = """\
你是一个专业的加密货币交易助手。

## 角色与能力
- 帮助用户查询行情、持仓、订单、交易对信息。
- 根据用户的交易需求，引导用户完成下单流程。
- 提供客观的市场信息，不给出投资建议。

## 话术边界
- 语气专业、简洁、友好。
- 不承诺收益、不预测价格走势、不喊单。
- 涉及资金操作时，必须提醒用户确认。
- 用户意图不明确时，主动询问澄清，不要猜测。

## 合规要求
- 不提供杠杆倍数建议。
- 不鼓励过度交易或非理性操作。
- 涉及法币出入金问题时，引导用户咨询官方客服。
"""


def build_agent(
    *,
    model: str | BaseChatModel | None = None,
    system_prompt: str | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    with_skills: bool = False,
) -> BaseChatModel:
    """构建交易助手 Deep Agent。

    Args:
        model: 模型标识或实例，默认取 settings.model。
        system_prompt: 自定义 system prompt，默认取 TRADING_ORCHESTRATOR_PROMPT。
        checkpointer: 持久化 checkpointer，用于多轮对话。不传则无持久化。
        with_skills: 是否启用 User Skill 隔离（Phase 2 功能）。

    Returns:
        编译后的 agent（CompiledStateGraph）。
    """
    kwargs = {}
    if with_skills:
        kwargs["skills"] = ["/skills/base/", "/skills/user/"]
        kwargs["backend"] = create_user_scoped_backend

    return create_deep_agent(
        model=model or settings.model,
        system_prompt=system_prompt or TRADING_ORCHESTRATOR_PROMPT,
        context_schema=TradingContext,
        checkpointer=checkpointer,
        **kwargs,
    )
