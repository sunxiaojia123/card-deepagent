"""基础 Agent — build_agent() 工厂函数 + 交易助手 System Prompt."""

from __future__ import annotations

from deepagents import create_deep_agent
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver

from config.settings import settings
from src.backend import create_user_scoped_backend
from src.context import TradingContext
from src.middleware.trading_output import TradingOutputMiddleware
from src.tools.api_executor import call_internal_api
from src.tools.confirm_popup import confirm_popup

TRADING_ORCHESTRATOR_PROMPT = """\
你是一个专业的加密货币交易助手。

## 角色与能力
- 帮助用户查询行情、持仓、订单、交易对信息。
- 根据用户的交易需求，引导用户完成下单流程。
- 支持礼品卡查询、购买、充值、转账等业务。
- 根据用户意图匹配对应的 Skill，调用内部 API 完成操作。
- 提供客观的市场信息，不给出投资建议。

## 话术边界
- 语气专业、简洁、友好。
- 不承诺收益、不预测价格走势、不喊单。
- 涉及资金操作时，必须提醒用户确认。
- 用户意图不明确时，必须调用 `confirm_popup` 让用户选择，禁止自行猜测。

## Popup 使用规则（重要）
当以下任一情况发生时，必须调用 `confirm_popup` 弹出选项让用户确认：
1. 交易方向不明确（如用户说"帮我操作一下BTC"，未说明买入还是卖出）
2. 币种不明确（如用户说"帮我买点币"）
3. 金额/数量不明确且无法从上下文推断
4. 涉及多个可选操作（如"查余额 / 购买 / 充值 / 转账"）
5. 大额操作确认（金额 > 5000 USDT 时）

Popup 格式：title 简洁描述问题，options 给出 2-4 个选项，每个选项含 id（英文标识）和 label（中文展示）。

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
        kwargs["tools"] = [call_internal_api, confirm_popup]
        kwargs["middleware"] = [TradingOutputMiddleware()]

    return create_deep_agent(
        model=model or settings.model,
        system_prompt=system_prompt or TRADING_ORCHESTRATOR_PROMPT,
        context_schema=TradingContext,
        checkpointer=checkpointer,
        **kwargs,
    )
