# 长对话 Summarization 方案书

> 版本：v1.0 | 日期：2026-07-14 | 作者：Agent 架构设计

---

## 1. 问题定义

### 1.1 现状

每次 Agent 调用 LLM 时，`messages` 列表包含自会话开始以来的**所有消息**——用户的每一句话、LLM 的每一次回复、每一次工具调用的返回结果。随着对话轮次增加，messages 线性增长。

### 1.2 风险

| 风险 | 触发条件 | 后果 |
|------|------|------|
| Context 溢出 | messages token 数 > DeepSeek 128K | API 调用报错，对话中断 |
| 延迟飙升 | messages 接近 100K tokens | 单次 LLM 调用耗时 10s+ |
| 早期信息淹没 | 新消息不断追加 | LLM "忘记"用户最早说的偏好和关键信息 |
| Token 成本 | 每轮都传全量历史 | 费用与对话轮次成正比增长 |

### 1.3 目标

- 对话 100 轮以上，LLM context token 数始终 < 60K
- 早期关键信息（用户名、偏好、重要决策）不丢失
- 前端历史展示不受影响（完整原文）
- 对现有架构零破坏

---

## 2. 核心设计

### 2.1 双通道存储

```
┌─ Checkpoint State ─────────────────────────────────┐
│                                                    │
│  messages :             [msg1, msg2, ..., msgN]     │  ← 全量原文
│  accumulated_summary :  "第1-80轮摘要：..."          │  ← 增量累积
│                                                    │
└────────────────────────────────────────────────────┘
         │                               │
         ▼                               ▼
    前端历史 API                     LLM 调用前拼接
    GET /history                    SystemMessage(摘要)
    → 读 messages                   + messages[-20:]
    → 完整原文，不受影响               → 上下文不超限
```

**设计原则：**

- `messages` 是**完整原文**——前端什么时候打开历史，看到的就是完整对话，不做任何删减
- `accumulated_summary` 是**增量累积摘要**——覆盖从第 1 条到截止点的所有内容，与 `messages[-20:]` 无缝衔接
- LLM 看到的是 `摘要 + 最近 20 条原文`，而非 `截断的历史`

### 2.2 增量累积机制

关键设计：摘要是**累积**的，不是**替换**的。每次压缩不是"重新总结一批旧消息然后丢弃"，而是"把新的内容追加合并到已有摘要中"。

```
第一轮超阈值（例如 msg 累积到 80 条，token 超过 60K）：

  压缩范围: msg[1..60]
  新摘要 = LLM("请总结以下对话: {msg[1..60]}")
  state.accumulated_summary = "用户咨询了BTC行情..."
  state.messages = [msg1..msg80]  ← 不删

又聊了 40 轮，再次超阈值：

  压缩范围: msg[61..100]
  合并 = LLM("已有摘要: {old_summary}\n\n新增内容: {msg[61..100]}\n\n合并为一份完整摘要")
  state.accumulated_summary = "用户先咨询了BTC行情，随后查询ETH持仓，..."
  state.messages = [msg1..msg120]  ← 不删

又过了 30 轮：

  压缩范围: msg[101..130]
  合并 = LLM("已有摘要: {old}\n\n新增内容: {msg[101..130]}\n\n合并")
  state.accumulated_summary = "..."
  state.messages = [msg1..msg150]  ← 不删
```

**无缝隙证明：**

- 任何时刻，`accumulated_summary` 覆盖 `msg[1..cutoff]` 的全部内容
- LLM 上下文 = `accumulated_summary` (代表 1..cutoff) + `messages[cutoff+1..N]`（最近 20 条原文）
- cutoff 两边连续，不丢任何信息

### 2.3 摘要元压缩

当 `accumulated_summary` 自身 token 数超过 30K 时，对摘要自身做压缩：

```
accumulated_summary = LLM(
    "请将以下对话摘要进一步浓缩，保留所有关键信息（用户名、偏好、重要数字、决策）:\n{old}"
)
```

摘要 token 永远 ≤ 30K。加上最近 20 条原文（~20K）和 system prompt（~10K），总 context ≤ 60K。

---

## 3. 消息过滤

压缩时并非所有消息都值得进摘要。进入摘要的只有**核心交互内容**：

### 3.1 过滤规则

| 消息类型 | 来源 | 进摘要？ | 理由 |
|------|------|------|------|
| `HumanMessage` | 用户输入 | ✅ 全文 | 用户意图、偏好、关键信息的唯一来源 |
| `AIMessage` | LLM 回复 | ✅ 全文 | Agent 给出的信息、结论、建议 |
| `ToolMessage` (call_internal_api) | API 调用 | ✅ 摘要文本 | 短数据直接拼接，长数据 LLM 总结 |
| `ToolMessage` (read_file) | Skill 文件读取 | ❌ 跳过 | SKILL.md/apis.yaml 几百行原文，且已在 system prompt 中 |
| `AIMessage` (tool_calls 无文本) | LLM 工具决策 | ❌ 跳过 | 空内容，仅含 tool_calls 元数据 |

### 3.2 过滤实现

```python
def _filter_messages_for_summary(messages: list) -> str:
    """将消息列表转换为适合传给摘要 LLM 的文本."""
    lines = []
    for m in messages:
        if isinstance(m, HumanMessage):
            lines.append(f"用户: {m.content}")
        elif isinstance(m, AIMessage):
            if m.content and str(m.content).strip():
                lines.append(f"助手: {m.content}")
        elif isinstance(m, ToolMessage):
            content = str(m.content)
            # 排除文件读取（长内容不缓存）
            if len(content) < 500:
                lines.append(f"[API结果] {content}")
    return "\n".join(lines)
```

---

## 4. API 摘要策略（Card 数据融合）

### 4.1 问题

当前 `call_internal_api` 返回的 ToolMessage 内容为 `"[query_gift_card] 执行成功，已展示结果卡片。"`——LLM 知道调用成功了，但**不知道卡片里有什么数据**。用户追问"刚才那个卡余额多少"时，LLM 需要重复调用 API。

### 4.2 方案：长短分治

```python
FLAT_SUMMARY_MAX_CHARS = 200  # 阈值

def _build_summary(api_name: str, data: dict) -> str:
    flat_str = json.dumps(data, ensure_ascii=False)
    if len(flat_str) <= FLAT_SUMMARY_MAX_CHARS:
        # 短数据：直接拼接，零延迟
        return f"[{api_name}] {flat_str}"
    else:
        # 长数据：LLM 生成自然语言摘要
        return _llm_summary(api_name, data)
```

### 4.3 实际效果

| API | 返回数据 | JSON 长度 | 策略 | 摘要示例 |
|------|------|------|------|------|
| `query_gift_card` | `{"card": {"card_no": "GIFT-...", "balance": 500}}` | ~80 | 直接 | `[query_gift_card] {"card":{"card_no":"GIFT-12345678","balance":500}}` |
| `place_spot_order` | `{"order": {"order_id": "ord-xxx", "symbol": "BTC", ...}}` | ~120 | 直接 | `[place_spot_order] {"order":{"order_id":"ord-xxx","symbol":"BTC","side":"buy"}}` |
| `query_positions` | `{"positions": [{...}, {...}, {...}]}` | ~250 | LLM | `用户持仓 BTC 0.52, ETH 12.5, USDT 50000` |
| `query_orders` | `{"orders": [{...}, {...}, {...}]}` | ~400 | LLM | `历史订单 3 笔：BTC 买入 0.1 (已成交), ETH 卖出 5.0 (已成交), BTC 买入 0.05 (待成交)` |

### 4.4 LLM 摘要 Prompt

```python
async def _llm_summary(api_name: str, data: dict) -> str:
    prompt = f"""请用一句简短的中文总结以下 API 调用结果，提取关键数值：

API: {api_name}
数据: {json.dumps(data, ensure_ascii=False, indent=2)}

要求：只返回总结文本，不超过 80 字。"""
    response = await llm.ainvoke(prompt)
    return response.content.strip()
```

---

## 5. 实现计划

### 5.1 涉及文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/middleware/summarization.py` | **新建** | `SummarizationMiddleware` — 核心逻辑 |
| `src/tools/api_executor.py` | 修改 | `_build_summary()` 替换现有固定文本 |
| `src/agent.py` | 修改 | `state_schema` 增加 `accumulated_summary` 字段，注入 middleware |
| `config/settings.py` | 修改 | 新增 `max_context_tokens`、`summary_max_chars` |
| `tests/test_summarization.py` | **新建** | 单元测试 |
| `tests/test_api_summary.py` | **新建** | API 摘要测试 |

### 5.2 Middleware 伪代码

```python
class SummarizationMiddleware(AgentMiddleware):
    """长对话自动摘要 Middleware。

    before_model hook：每次 LLM 调用前检查 token 数，超阈值则压缩历史。
    """

    def __init__(self, max_tokens: int = 60000, keep_recent: int = 20):
        self.max_tokens = max_tokens
        self.keep_recent = keep_recent

    async def abefore_model(self, state, runtime, config):
        messages = state.get("messages", [])
        if _estimate_tokens(messages) < self.max_tokens:
            return None  # 不超限，无需压缩

        # 确定压缩截止点
        cutoff = len(messages) - self.keep_recent
        if cutoff <= 0:
            return None

        to_summarize = _filter_messages(messages[:cutoff])
        old_summary = state.get("accumulated_summary", "")

        if old_summary:
            new_summary = await _merge_summaries(old_summary, to_summarize)
        else:
            new_summary = await _generate_summary(to_summarize)

        return {"accumulated_summary": new_summary}

    def wrap_model_call(self, request, handler):
        # 拼接上下文：摘要 + 最近 N 条
        summary = request.state.get("accumulated_summary", "")
        if summary:
            # 在 messages 前插入摘要 SystemMessage
            ...
        return handler(request)
```

### 5.3 自定义 State Schema

Agent state 增加 `accumulated_summary` 字段：

```python
from deepagents.graph import DeepAgentState

class TradingAgentState(DeepAgentState):
    accumulated_summary: str | None = None
```

`DeepAgentState` 是 deepagents 提供的基础 state 类型，我们扩展它增加自己的字段，checkpointer 会自动持久化。

### 5.4 Token 估算

```python
def _estimate_tokens(messages: list) -> int:
    """粗略估算 messages 总 token 数."""
    total = 0
    for m in messages:
        content = str(getattr(m, "content", ""))
        total += max(1, len(content) // 3)
    return total
```

中文 ~1.5 字符/token，英文 ~4 字符/token。`len // 3` 是一个安全的粗略估算，实际 tokens 通常比估算值略少。

---

## 6. 集成测试

### 6.1 单元测试

| 测试 | 验证内容 |
|------|------|
| `test_estimate_tokens` | 估算值在合理范围 |
| `test_filter_messages` | 文件读取消息被排除，核心消息保留 |
| `test_build_summary_short` | 短 JSON 直接拼接 |
| `test_build_summary_long` | 长 JSON 调 LLM 总结 |
| `test_accumulated_summary` | 增量合并无缝隙 |

### 6.2 集成测试

| 测试 | 验证内容 |
|------|------|
| `test_150_turn_conversation` | 150 轮对话后 token 数 < 60K |
| `test_early_info_preserved` | 第 1 轮的用户名在第 150 轮仍可被引用 |
| `test_summary_persists` | 重启服务后摘要仍在 checkpoint 中 |
| `test_frontend_unaffected` | 历史 API 返回完整原文 |

---

## 7. 验收标准

- 对话 100+ 轮，LLM context 的 token 估算值 < 60K
- `accumulated_summary` 覆盖第 1 条到 cutoff 的所有关键信息
- 文件读取 ToolMessage 不出现在摘要中
- Card 短数据直接拼接，长数据 LLM 总结
- 前端历史 API 返回完整 messages，不受影响
- 服务重启后摘要从 checkpoint 恢复
