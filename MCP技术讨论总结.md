# MCP 与内部工具体系的工程化讨论

> 独立技术讨论，不依赖具体项目。记录关于"AI Agent 工具集成策略"的架构思考。

---

## 1. 背景：当 AI Agent 需要调用外部工具

构建一个 AI Agent（比如交易助手），让它能帮用户查行情、比价、下单，本质上需要解决一个问题：**LLM 怎么调用外部 API？**

目前有两种主流思路：

| | MCP（Model Context Protocol） | 内部 Skill + API Schema |
|---|---|---|
| **本质** | 标准化协议，社区现成工具即插即用 | 自建工具描述与路由体系 |
| **工具提供方** | 第三方（Gate、Brave、Filesystem 等） | 我们自己 |
| **LLM 看到的** | N 个独立 Tool，每个有 name + description + schema | 1 个 Tool（`call_internal_api`），内部按 `api_name` 路由 |
| **维护成本** | 零（提供方维护） | 需要维护 schema 文件 |
| **灵活性** | 受限于 Server 暴露的 Tool 列表 | 完全可控，可精确选择所需的接口 |
| **SOP 支持** | 无，Tool 之间无关联 | 有，SKILL.md 定义业务流程 |

---

## 2. MCP 技术原理

### 2.1 协议本质

MCP（Model Context Protocol）是 Anthropic 提出的开放协议，用于 AI 模型与外部工具之间的标准化通信。底层协议是 **JSON-RPC 2.0**。

两个角色：

- **MCP Client**：AI Agent，需要调用外部工具
- **MCP Server**：工具提供方，暴露一系列 Tool 供 Agent 调用

Agent 通过 MCP 协议与 Server 通信，自动发现可用工具、传递参数、接收结果。整个过程不依赖具体 Server 的实现语言或部署方式。

### 2.2 通信流程

MCP 的完整调用分三步：

```
1. initialize（握手）

   Client → Server:
     {"jsonrpc":"2.0", "method":"initialize",
      "params":{"protocolVersion":"...", "capabilities":{...}}}

   Server → Client:
     {"jsonrpc":"2.0", "result":{"protocolVersion":"...", "capabilities":{"tools":{}}}}

2. tools/list（发现工具）

   Client → Server:
     {"jsonrpc":"2.0", "method":"tools/list", "params":{}}

   Server → Client:
     {"jsonrpc":"2.0", "result":{"tools":[
       {"name":"cex_spot_get_spot_tickers",
        "description":"Get ticker information for one or all currency pairs",
        "inputSchema":{"type":"object","properties":{"currency_pair":{"type":"string"}},"required":["currency_pair"]}},
       {"name":"cex_spot_list_currencies",
        "description":"List all currencies supported",
        "inputSchema":{"type":"object","properties":{}}},
       ...
     ]}}

3. tools/call（调用工具）

   Client → Server:
     {"jsonrpc":"2.0", "method":"tools/call",
      "params":{"name":"cex_spot_get_spot_tickers", "arguments":{"currency_pair":"BTC_USDT"}}}

   Server → Client:
     {"jsonrpc":"2.0", "result":{"content":[
       {"type":"text","text":"BTC_USDT: last=43500, high=44000, low=43000, vol=1234.5"}
     ]}}
```

### 2.3 两种传输模式

MCP 支持两种传输层，本质区别在于 **Server 进程的位置**。

#### Stdio（标准输入输出）

```
Agent (Python) ───stdin/stdout─── MCP Server 子进程 ───HTTP─── 外部 API
     (你的机器)                   (你的机器)                (远程)
```

Agent 通过 `spawn` 启动本地子进程作为 MCP Server，通过 **stdin** 写入 JSON 请求，从 **stdout** 读取 JSON 响应。MCP Server 是本地代理，外部 API 的 HTTP 请求仍从本地发出。

```python
# 配置示例
StdioConnection(
    transport="stdio",
    command="npx",                     # 启动命令
    args=["-y", "gate-mcp"],           # npm 包名
    env={"GATE_API_KEY": "sk-xxx"},   # API Key 通过环境变量注入
)
```

**生命周期：** 每次 Agent 请求时启动子进程，请求结束 `SIGTERM` 杀掉。由 `langchain-mcp-adapters` 内部管理。存在冷启动开销（启动 Node.js 进程）。

| 优点 | 缺点 |
|---|---|
| 零网络延迟（本机管道通信） | 每次请求有冷启动开销 |
| 不需要暴露网络端口，安全 | 仅限本机，不能跨机器部署 |
| 同一份代码在任何机器上都能跑 | 进程管理复杂（僵尸进程、资源泄漏） |

#### SSE（Server-Sent Events）

```
Agent (Python) ───HTTP─── 远程 MCP Server ───HTTP─── 外部 API
     (你的机器)             (远程服务器)
```

MCP Server 作为独立 HTTP 服务部署在远程。Agent 通过 HTTP 发送 JSON-RPC 请求，Server 通过 SSE 推送响应。

```python
# 配置示例
SSEConnection(
    transport="sse",
    url="https://mcp.example.com/sse",
    headers={"Authorization": "Bearer token-xxx"},
)
```

| 优点 | 缺点 |
|---|---|
| 跨机器部署，适合生产环境 | 网络延迟 |
| 水平扩展 | 需要鉴权和 TLS |
| 第三方即开即用，无需下载依赖 | 服务端需要保持在线 |

#### 关键理解

**Stdio 模式中，MCP Server 是你本地的代理。** 外部 API 永远从你的机器发出，MCP Server 只做翻译。不存在"MCP Server 代你访问 Gate API 所以更快"的说法——HTTP 请求还是你本地发的。

**SSE 模式中，MCP Server 是别人的服务。** 你不需要知道对方 API 的任何细节，只需要知道对方的 MCP Server 地址。

### 2.4 Agent 如何发现和选择 MCP Tool

#### 加载阶段

```python
# langchain-mcp-adapters 封装了整个过程
client = MultiServerMCPClient(connections={
    "gate": StdioConnection(transport="stdio", command="npx", args=["-y", "gate-mcp"])
})
tools = await client.get_tools()
# → 返回 428 个 LangChain BaseTool
```

每个 Tool 有三个核心属性，就是 `tools/list` 返回的内容：

```python
Tool(
    name="cex_spot_get_spot_tickers",       # 名称，Agent 通过名字引用
    description="Get ticker information...", # 描述，LLM 靠这个决定是否调用
    args_schema={                            # 参数定义，LLM 靠这个生成参数
        "type": "object",
        "properties": {
            "currency_pair": {
                "type": "string",
                "description": "Currency pair, e.g. BTC_USDT"
            }
        },
        "required": ["currency_pair"]
    }
)
```

#### 选择阶段（LLM 推理）

对 LLM 来说，这些 Tool 全部以 **function calling 的原生机制** 工作。LLM 扫描所有 Tool 的 `description` 字段做语义匹配，自己判断哪一个最匹配用户意图——不是硬编码的映射表，428 个 Tool 就是 428 条描述文本。

```
用户: "BTC 现在什么价格？"

LLM 收到 430 个 Tool 的定义（call_internal_api + confirm_popup + 428 gate tools）:

  LLM 扫描所有 Tool 的 description:
    → call_internal_api: "调用内部业务 API" → 语义不匹配
    → confirm_popup: "弹出确认窗口" → 不匹配
    → cex_spot_list_currencies: "List all currencies" → 不够精确
    → cex_spot_get_spot_tickers: "Get ticker information" → 匹配！价格查询就是 ticker

  LLM 选择 cex_spot_get_spot_tickers
  LLM 根据 args_schema 生成参数: currency_pair="BTC_USDT"
```

#### 执行阶段

```
LangGraph ToolNode:
  1. 在 430 个 Tool 中找到 name="cex_spot_get_spot_tickers"
  2. 调 tool.ainvoke({"currency_pair": "BTC_USDT"})
  3. Tool 内部 → MCP stdio 子进程 → 发 JSON-RPC tools/call
  4. MCP Server → 调 Gate API → GET /api/v4/spot/tickers?currency_pair=BTC_USDT
  5. 返回 → ToolMessage(content="BTC_USDT: last=43500, ...")
  6. ToolMessage 写入 state.messages → LLM 看到结果 → 回复用户
```

### 2.5 Tool 如何装入 LLM 请求

一个常见的误解是"Tool 描述会拼到 system prompt 里"。实际上，在现代 LLM API（OpenAI / Anthropic）中，Tool 的定义是 **独立的 `tools` 参数**，不在 messages 里：

```
┌─────────────────────────────────────────────────────┐
│ System Prompt（system role）                         │
│ "你是一个交易助手，帮助用户..."                        │
│ → 只有角色定义 + 行为规则                             │
│ → 不包含 Tool 列表，不包含 Schema                     │
├─────────────────────────────────────────────────────┤
│ Messages（user/assistant/tool roles）                │
│ → 对话历史 + 之前的 tool call 结果                    │
│ → 不包含 Tool 定义                                   │
├─────────────────────────────────────────────────────┤
│ Tools 数组（API 的独立参数，不在 messages 里）         │
│ [{                                                   │
│   "type": "function",                                │
│   "function": {                                      │
│     "name": "cex_spot_get_spot_tickers",             │
│     "description": "Get ticker information...",      │
│     "parameters": {  ← Schema 只在这里出现一次         │
│       "type": "object",                              │
│       "properties": {...},                           │
│       "required": [...]                              │
│     }                                                │
│   }                                                  │
│ }, ...]                                              │
└─────────────────────────────────────────────────────┘
```

**Schema 只存在于 `tools` 数组中，不会在 system prompt 中重复。**

这是 Native Function Calling 机制。早期的 ReAct 模式确实会把 Tool 描述当文本拼进 system prompt，但现在的主流框架都用原生的 `tools` 参数，工具定义和对话内容在 API 层面就是分开的。

### 2.6 混合 Tool 的执行路由原理

实际项目中往往是 MCP Tool 和普通 Python Tool 混用。LLM 选中一个 function name 后，**框架怎么知道这个调用要走 MCP（JSON-RPC）还是走 HTTP？**

答案：**路由信息在 Tool 对象创建时就绑定了，执行时不做 if-else 判断。**

```python
# ======== 加载阶段：每个 Tool 在创建时就绑定了自己的执行方式 ========

# 1. 从 Gate MCP 加载 → 每个 Tool 内部持有 MCP session
gate_tools = await gate_mcp_client.get_tools()
# gate_tools[0].name = "cex_spot_get_spot_tickers"
# gate_tools[0]._arun 内部逻辑：
#   async def _arun(self, **kwargs):
#       return await self._session.call_tool(self.name, kwargs)
#       # ↑ 走 JSON-RPC 发给 Gate MCP Server

# 2. 从 Binance MCP 加载 → 同样持有自己的 MCP session
binance_tools = await binance_mcp_client.get_tools()
# binance_tools[0]._arun 内部 → JSON-RPC 发给 Binance MCP Server

# 3. 普通 Python 工具 → 没有 MCP session，直接走 HTTP
@tool
def call_internal_api(api_name: str, params: dict):
    return httpx.post(f"http://internal-api/{api_name}", json=params)

# 4. 全部合并
all_tools = gate_tools + binance_tools + [call_internal_api, confirm_popup]

# ======== 执行阶段：多态分发，不需要判断来源 ========

# LLM 返回: {"name": "cex_spot_get_spot_tickers", "arguments": {...}}
tool = find_tool_by_name(all_tools, "cex_spot_get_spot_tickers")
result = await tool.ainvoke(arguments)
# → 内部自动走 JSON-RPC → Gate MCP Server

# LLM 返回: {"name": "call_internal_api", "arguments": {...}}
tool = find_tool_by_name(all_tools, "call_internal_api")
result = await tool.ainvoke(arguments)
# → 内部自动走 HTTP → 内部 API
```

**对 LLM 来说，所有 Tool 都是 function，一视同仁。** LLM 只负责"点菜"（选 function name），至于后厨是哪个厨师（MCP Server A / MCP Server B / 本地函数），是 Tool 对象在创建时就绑定好的，框架层不需要做来源判断。

### 2.7 具体案例：Gate MCP

Gate 交易所的 MCP Server 可通过 `npx -y gate-mcp` 获取。

实际测试结果：**暴露了 428 个 Tool**，涵盖现货、合约、钱包、行情等全部 Gate API。前 10 个示例：

```
cex_spot_list_currencies       — 列出所有支持的币种
cex_spot_get_currency          — 获取单个币种详情
cex_spot_list_currency_pairs   — 列出所有交易对
cex_spot_get_currency_pair     — 获取单个交易对详情
cex_spot_get_spot_tickers      — 获取行情数据
cex_spot_get_spot_order_book   — 获取订单簿
cex_spot_get_spot_trades       — 获取最近成交
cex_spot_get_spot_candlesticks — 获取 K 线数据
cex_spot_get_spot_insurance    — 获取保险基金历史
cex_spot_get_spot_fee          — 查询手续费率
```

这些 Tool 全部由 Gate 团队维护，我们不需要写一行代码就能让 Agent 拥有 Gate 的全部交易能力。但这也带来了问题——428 个 Tool 对 LLM 来说真的太多了。

---

## 3. MCP 在实际应用中的三个核心问题

社区 MCP 的优势很明显："拿来就用"。但在实际工程中，量的积累会引发质变。

### 3.1 问题一：Tool 数量爆炸，Context 直接炸

单个 Gate MCP 就暴露了 428 个 Tool。以每个 Tool 约 300 tokens 计算，光 Gate 一家就要 ~128K tokens。如果接三个交易所：

```
Gate MCP:     428 tools × 300 tokens ≈ 128K tokens
Binance MCP:  200 tools × 300 tokens ≈  60K tokens
OKX MCP:      150 tools × 300 tokens ≈  45K tokens
─────────────────────────────────────────────────
合计:         778 tools               ≈ 233K tokens
```

这只是工具定义，还没算 system prompt、对话历史、tool call 结果。很多模型的 context window 直接超限。**MCP 的"即插即用"在单个 Server 时还很美好，多个 Server 一叠加就失控。**

### 3.2 问题二：SOP 缺失 —— "货比三家"不可靠

这是 MCP 最隐蔽但最致命的问题。看下面这个场景：

```
用户: "BTC 现在 43500，帮我以低于市场价买入 0.1 个"
```

**期望行为：** 同时查询 Gate、Binance、OKX 三家价格 → 比价 → 选最优 → 下单。

**MCP 方案的实际行为：** 看运气。

LLM 并不知道它"应该"货比三家。没有 SOP 引导，它的选择完全依赖 description 语义匹配。大概率是：

1. 匹配到某个交易所的 ticker Tool（比如 Gate 的 `cex_spot_get_spot_tickers`）
2. 查到 Gate 买一价 → 觉得满足条件 → 直接调 Gate 下单 Tool
3. **任务结束。根本没有比价。**

某些推理能力强的大模型可能会"悟"出比价策略，但这不可靠——换个模型、换个 prompt、甚至同一模型的另一次推理，行为就可能不同。

```
文档中 MCP 方案那个"三家都查"的例子，描述的其实是理想情况。
在实际工程中这不可靠——没有 SOP 保证的行为，就等于没有这个功能。
```

### 3.3 问题三：近似描述陷阱 —— LLM 会"迷路"

光 Gate 一家 MCP 里，"查价格相关"的 Tool 就有好几个：

```
cex_spot_get_spot_tickers       — "Get ticker information for currency pairs"
cex_spot_get_spot_order_book    — "Get order book of a currency pair"
cex_spot_get_spot_trades        — "Get recent trades of a currency pair"
cex_spot_get_spot_candlesticks  — "Get candlestick data"
```

用户说"帮我看看 BTC 现在什么价"。`tickers`、`order_book`、`trades`、`candlesticks` 在语义上都跟"价格"相关。选错一个：

- 选到 `candlesticks` → 拿了 500 根 K 线回来塞进 context，信息不对还浪费窗口
- 选到 `trades` → 拿了最新成交列表回来，没有买一价，无法判断能不能"低于市价买入"

**428 个 Tool 里语义相近的越多，LLM 选错的概率越高。** MCP 把选择权完全交给 LLM 的语义理解，没有前置过滤，Tool 越多噪声越大。

### 3.4 填补鸿沟：三种方式

> "加载了很多 MCP"和"LLM 知道该选哪个"之间，天然存在一道鸿沟。MCP 越多，鸿沟越大。这道鸿沟不管你用什么方式，都得补上。

**方式 A：System Prompt 写规则（最轻量）**

直接在 system prompt 里写死规则：

```
当用户要求以最优价格交易时：
1. 必须同时查询 Gate、Binance、OKX 三家的 ticker
2. 比较买一价，选最低的
3. 再调用该平台的 order 接口下单
```

- 优点：不用写额外文件，改 prompt 就行
- 缺点：prompt 会越来越长，多个规则互相干扰。三个 MCP 还行，十个 MCP、上百条规则就失控

**方式 B：每个跨 MCP 场景写一个 Skill**

"货比三家"写一个 Skill，"套利检测"写一个 Skill，"多平台资产汇总"写一个 Skill……

- 优点：每个场景行为精准可控
- 缺点：场景多了 Skill 也爆炸，变成另一种形式的 Tool 爆炸

**方式 C：代码层聚合（本文推荐的路线）**

不在 LLM 层面解决，在代码层面把多个 MCP 的调用聚合成一个 Tool：

```python
# LLM 只看到一个 Tool
def compare_price(symbol):
    results = [
        gate_mcp.call("ticker", symbol),
        binance_mcp.call("ticker", symbol),
        okx_mcp.call("ticker", symbol),
    ]
    return min(results, key=lambda r: r.bid)
```

- 优点：LLM 不需要知道底层有几个平台，"货比三家"是代码保证的，不是 LLM 推理保证的
- 缺点：每次新增 MCP 需要改代码

---

## 4. 内部 Skill + API Schema 方案

### 4.1 设计思路

不是把每个 API 变成独立的 Tool，而是**整个系统只有一个 Tool（`call_internal_api`）**，所有 API 调用通过统一入口路由：

```
用户: "帮我查下 BTC 行情"

LLM → 匹配 gift-card Skill → 读取 apis.yaml → 找到 query_gift_card 接口
LLM → 调 call_internal_api("query_gift_card", {card_no: "GIFT-..."})
     → Tool 内部 HTTP 请求 Mock API → 返回 {code, message, data}
     → 根据 show_type 决定输出方式（card 卡片 / text 文本）
```

### 4.2 Skill 结构

```
skills/base/gift-card/
  ├── SKILL.md       # 业务描述、SOP 流程、何时使用
  └── apis.yaml      # API 定义：name, method, path, show_type, params
```

**SKILL.md**——不仅是 API 列表，更是业务 SOP：

```markdown
# 礼品卡业务
## SOP
1. 识别用户意图（查余额 / 购买 / 充值 / 转账）
2. 收集必要参数
3. 调用对应 API
4. 返回卡片展示结果
```

**apis.yaml**——定义该 Skill 下可用的 API：

```yaml
apis:
  - name: query_gift_card
    path: /api/v1/gift-card/query
    method: POST
    show_type: card
    params:
      - name: card_no
        type: string
        required: true
```

### 4.3 核心优势

**优势 1：Tool 不爆炸。** Skill 方案对外只有 1 个 Tool，LLM context 中工具定义的开销是固定的 O(1)，不随接入业务数量增长。Gate MCP 的 428 个 Tool 在 Skill 方案中会被收敛为 apis.yaml 里精挑细选的几个接口。

**优势 2：SOP 强制执行。** 回头对比第 3.2 节的例子：

```
MCP 方案（无 SOP，不可靠）:
  Gate MCP     → 查 Gate 买一价 → 直接下单？（可能跳过了比价）
  → 行为依赖 LLM "悟性"，不可控

Skill 方案（有 SOP，可靠）:
  SKILL.md: "先调比价 API → 选最优 → 调下单 API"
  → LLM 按 SOP 走：compare_price → 拿到聚合结果 → place_order
  → 2 次 tool call，平台差异在内部 HTTP 层消化，Agent 不知道有三个平台
```

**优势 3：语义边界清晰，不会"迷路"。** 回到第 3.3 节的问题——MCP 里有四个跟"价格"相关的 Tool，LLM 容易选错。Skill 方案中 `apis.yaml` 只暴露：

```yaml
- name: query_price      # "查询当前行情价格"
- name: query_kline      # "查询历史K线数据"
```

几个接口语义边界清晰，LLM 不可能把"现在什么价"匹配到 K 线上去。前置过滤替 LLM 把噪音剪掉了。

**优势 4：动态加载。** 当业务增长到几十上百个 Skill 时，不可能全部一次性加载到 prompt。

```
Phase 1（当前）:  所有 Skill 元数据一次性加载
Phase 2（演进中）: 问题 → 语义匹配 → 只加载匹配的 Skill 组
Phase 3（蓝图）:   问题 → Skill 路由 → 加载 Skill + 关联的子 Skill / 上下文
```

MCP 没有这个能力——428 个 Tool 要么全加载，要么靠用户手动配置白名单过滤，不灵活。

**优势 5：内部标准，完全可控。** 接口粒度由我们自己决定（只暴露需要的），返回格式统一（`{code, message, data}`），业务逻辑和接口定义放在一起（SKILL.md + apis.yaml 同目录），跨平台聚合可在内部 HTTP 层完成，Agent 无感知。

---

## 5. MCP vs Skill：什么时候用哪个

### 5.1 MCP 的价值：解决"有没有"

社区有现成的 MCP Server，一行命令就能用。不需要了解对方 API 细节，不需要维护接口文档。

**适用场景：**

- 接入第三方外部工具（Brave Search、Gate、Filesystem）
- 快速原型验证（"先跑起来看看效果"）
- 跨语言工具（Node.js、Go 写的 MCP Server）

### 5.2 Skill 的价值：解决"好不好"

不是"能不能调这个接口"，而是"怎么调得更好、更精准、更高效"。

**适用场景：**

- 内部业务系统，接口我们可以定义和控制
- 需要跨平台 / 多来源聚合为一个统一接口
- 需要业务 SOP 编排（不是孤立的 Tool 调用）
- 需要精准控制 context 大小和 prompt 质量
- 需要按用户问题动态选择工具集

### 5.3 本质区别

```
MCP:   解决 "有没有" — 社区有现成的，拿来就用，平台方维护
Skill: 解决 "好不好" — 知道要用哪些、如何编排成 SOP、怎么把质量做好
```

两者不是替代关系。MCP 适合"我不知道要不要用，先用社区的试试"；Skill 适合"我清楚要做什么，我需要把这件事做到极致"。

---

## 6. 架构分层：我们做的是哪一层

关于"为什么不用 MCP"的常见质疑：*"MCP 已经是行业标准了，你们自己封装是不是在重复造轮子？"*

**不是。** MCP 和我们做的是两个不同层面的问题：

| MCP 解决的 | Skill 解决的 |
|---|---|
| Tool 的**通信协议**标准化 | Tool 的**业务编排**标准化 |
| Agent 怎么**发现**工具 | Agent 怎么**用好**工具 |
| 连接层 | 应用层 |

```
┌──────────────────────────────────────────────────────┐
│                   Skill 编排层（我们做的）              │
│  - SOP 流程定义                                       │
│  - 问题 → Skill 组映射                                │
│  - 跨平台聚合                                         │
│  - Context 精确控制                                    │
├──────────────────────────────────────────────────────┤
│                   Tool 通信层                          │
│  - HTTP（当前主力）                                    │
│  - MCP（未来可接入的扩展通道）                          │
│  - gRPC / 内部 RPC                                   │
└──────────────────────────────────────────────────────┘
```

MCP 定义了"Agent 和 Server 之间怎么传 JSON"，Skill 定义了"这个业务有什么 API、调用的先后顺序是什么、参数怎么组合"。两者不在一个抽象层上。

**我们建的是上层，MCP 是底层通道之一。底层仍然可以用 MCP 接入社区工具，但 LLM 不需要知道底层有 MCP、有几个平台、Tool 有多少。它只需要看到精炼后的、带有 SOP 的、按意图分组的 Tool。**

---

## 7. 总结

1. **MCP 的"即插即用"很美好，但有两个工程限制：** Tool 数量爆炸导致 context 超限；缺少 SOP 导致 LLM 行为不可靠（"货比三家"不会必然发生）。

2. **近似描述是 MCP 的放大器问题：** 工具越多、description 越相似，LLM 选错的概率越高。MCP 没有前置过滤机制。

3. **"加载 MCP"和"LLM 正确使用"之间有一道鸿沟，** 必须用某种编排层（system prompt 规则 / Skill / 聚合层）填充。不存在"只加载 MCP 就能自动正确编排"这回事。

4. **MCP Tool 和普通 Tool 在框架层是统一的多态分发：** 每个 Tool 在创建时就绑定了自己的执行方式（JSON-RPC 或 HTTP），LLM 选择后框架按 name 查找并调用，路由对 LLM 透明。

5. **MCP 和 Skill 解决不同层面的问题：** MCP 是通信协议标准化（连接层），Skill 是业务编排标准化（应用层）。两者互补——日常主力用 Skill，MCP 作为底层的外部扩展通道。

6. **本质上不是"用不用 MCP"的问题，而是"在哪一层做 Tool 编排"的问题——我们选择在更高层做。**
