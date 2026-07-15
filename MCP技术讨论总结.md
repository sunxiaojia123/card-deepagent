# MCP 与内部工具体系的工程化讨论

> 独立技术讨论，不依赖具体项目。记录关于"AI Agent 工具集成策略"的架构思考。

---

## 1. 背景：两种工具集成思路

当构建一个 AI Agent 项目，需要让 LLM 调用外部 API 时，有两种主流思路：

| | MCP（Model Context Protocol） | 内部 Skill + API Schema |
|------|------|------|
| **本质** | 标准化协议，社区现成工具即插即用 | 内部标准，自建工具描述与路由体系 |
| **工具提供方** | 第三方（Gate、Brave、Filesystem 等） | 我们自己 |
| **LLM 看到的** | N 个独立 Tool，每个有 name + description + schema | 1 个 Tool（call_internal_api），内部按 api_name 路由 |
| **维护成本** | 零（提供方维护） | 需要维护 schema 文件 |
| **灵活性** | 受限于 Server 暴露的 Tool 列表 | 完全可控，可精确选择所需的接口 |
| **SOP 支持** | 无，Tool 之间无关联 | 有，SKILL.md 定义业务流程 |

---

## 2. MCP 技术原理

### 2.1 协议本质

MCP（Model Context Protocol）是 Anthropic 提出的一种开放协议，用于 AI 模型与外部工具之间的标准化通信。底层协议是 **JSON-RPC 2.0**。

一个 MCP 体系中有两个角色：

- **MCP Client**：AI Agent，需要调用外部工具
- **MCP Server**：工具提供方，暴露一系列 Tool 供 Agent 调用

Agent 通过 MCP 协议与 Server 通信，自动发现可用工具、传递参数、接收结果。整个过程是标准化的，不依赖具体 Server 的实现语言或部署方式。

### 2.2 通信流程

MCP 的完整调用分为三步：

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

Agent 通过 `spawn` 启动一个本地子进程作为 MCP Server。Agent 向子进程的 **stdin** 写入 JSON 请求，从 **stdout** 读取 JSON 响应。MCP Server 是本地代理程序，外部 API 的 HTTP 请求是从本地发出的。

```python
# 配置示例
StdioConnection(
    transport="stdio",
    command="npx",                     # 启动命令
    args=["-y", "gate-mcp"],           # npm 包名
    env={"GATE_API_KEY": "sk-xxx"},   # API Key 通过环境变量注入
)
```

**生命周期：** 每次 Agent 请求时启动子进程，请求结束 `SIGTERM` 杀掉。由 `langchain-mcp-adapters` 内部管理，开发者不需要手写进程管理代码。但每次都有冷启动开销（启动 Node.js 进程、下载 npm 包依赖）。

| 优点 | 缺点 |
|------|------|
| 零网络延迟（本机管道通信） | 每次请求有冷启动开销 |
| 不需要暴露网络端口，安全 | 仅限本机，不能跨机器部署 |
| 同一份代码在任何机器上都能跑 | 进程管理复杂（僵尸进程、资源泄漏） |
| 适合 Node.js/Go 编写的 MCP Server | 不适合跨团队共享 |

#### SSE（Server-Sent Events）

```
Agent (Python) ───HTTP─── 远程 MCP Server ───HTTP─── 外部 API
     (你的机器)             (远程服务器)
```

MCP Server 作为独立 HTTP 服务部署在远程。Agent 通过 HTTP 发送 JSON-RPC 请求，Server 通过 SSE（Server-Sent Events）推送响应和通知。

```python
# 配置示例
SSEConnection(
    transport="sse",
    url="https://mcp.example.com/sse",
    headers={"Authorization": "Bearer token-xxx"},
)
```

**生命周期：** Agent 启动时建立 HTTP 连接（长连接或短连接），请求结束时关闭。

| 优点 | 缺点 |
|------|------|
| 跨机器部署，适合生产环境 | 网络延迟 |
| 水平扩展 | 需要鉴权和 TLS |
| 第三方即开即用，无需下载依赖 | 服务端需要保持在线 |
| 多租户共享同一个 Server | 连接中断需要重连 |

#### 关键理解

**Stdio 模式中，MCP Server 是你本地的代理。** 外部 API 永远从你的机器发出，MCP Server 只做翻译。不存在"MCP Server 代你访问 Gate API 所以更快"的说法——HTTP 请求还是你本地发的。

**SSE 模式中，MCP Server 是别人的服务。** 你不需要知道对方 API 的任何细节，只需要知道对方的 MCP Server 地址。适合 SaaS 化的工具平台。

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

这 428 个 Tool 合并到 Agent 的 tool 列表中。每个 Tool 有三个核心属性：

```python
Tool(
    name="cex_spot_get_spot_tickers",       # Agent 通过名字引用
    description="Get ticker information...", # LLM 靠这个决定是否调用
    args_schema={                            # LLM 靠这个生成参数
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

```
用户: "BTC 现在什么价格？"

LLM 收到 430 个 Tool 的描述（call_internal_api + confirm_popup + 428 gate tools）:

  LLM 扫描所有 Tool 的 description:
    → call_internal_api: "调用内部业务 API" → 语义不匹配
    → confirm_popup: "弹出确认窗口" → 不匹配
    → cex_spot_list_currencies: "List all currencies" → 不够精确
    → cex_spot_get_spot_tickers: "Get ticker information" → 匹配！价格查询就是 ticker

  LLM 选择 cex_spot_get_spot_tickers
  LLM 根据 args_schema 生成参数: currency_pair="BTC_USDT"
```

**关键设计：** LLM 是靠 Tool 的 `description` 做语义匹配，不是硬编码的映射表。428 个 Tool 对 LLM 来说就是 428 条描述文本，它自己判断哪一个最匹配用户意图。

#### 执行阶段

```
LangGraph Tool Node:
  1. 在 430 个 Tool 中找到 name="cex_spot_get_spot_tickers"
  2. 调 tool.ainvoke({"currency_pair": "BTC_USDT"})
  3. Tool 内部 → MCP stdio 子进程 → 发 JSON-RPC tools/call
  4. MCP Server → 调 Gate API → GET /api/v4/spot/tickers?currency_pair=BTC_USDT
  5. 返回 → ToolMessage(content="BTC_USDT: last=43500, ...")
  6. ToolMessage 写入 state.messages → LLM 看到结果 → 回复用户
```

### 2.5 具体案例：Gate MCP

Gate 交易所的 MCP Server 可通过 npm 获取：

```bash
npx -y gate-mcp
```

实际测试结果：**暴露了 428 个 Tool**，涵盖现货、合约、钱包、行情等全部 Gate API。前 10 个 Tool 示例：

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

这些 Tool 全部由 Gate 团队维护。我们不需要写一行代码就能让 Agent 拥有 Gate 的全部交易能力。

---

## 3. 内部 Skill + API Schema 方案

### 3.1 设计思路

不是把每个 API 变成一个独立的 Tool，而是**整个系统只有一个 Tool（`call_internal_api`）**，所有 API 调用通过统一入口路由：

```
用户: "帮我查下 BTC 行情"

LLM → 匹配 gift-card Skill → 读取 apis.yaml → 找到 query_gift_card 接口
LLM → 调 call_internal_api("query_gift_card", {card_no: "GIFT-..."})
     → Tool 内部 HTTP 请求 Mock API → 返回 {code, message, data}
     → 根据 show_type 决定输出方式（card 卡片 / text 文本）
```

### 3.2 Skill 结构

```
skills/base/gift-card/
  ├── SKILL.md       # 业务描述、SOP 流程、何时使用
  └── apis.yaml      # API 定义：name, method, path, show_type, params
```

**SKILL.md** 不仅仅是 API 列表，更是业务 SOP：

```markdown
# 礼品卡业务
## SOP
1. 识别用户意图（查余额 / 购买 / 充值 / 转账）
2. 收集必要参数
3. 调用对应 API
4. 返回卡片展示结果
```

**apis.yaml** 定义该 Skill 下可用的 API：

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

### 3.3 核心优势

**优势 1：Tool 不爆炸**

Gate MCP 暴露 428 个 Tool。每个 Tool 约 300 tokens，全部塞进 LLM context 需要 ~128K tokens。三个 MCP Server 叠加就是 338K，直接超限。

Skill 方案对外只有 1 个 Tool。LLM context 中 tool 定义的开销是固定的 O(1)，不随接入业务数量增长。

**优势 2：SOP 编排**

```
用户: "BTC 现在 43500，帮我以低于市场价买入 0.1 个"

MCP 方案:
  Gate MCP     → 查 Gate 买一价
  Binance MCP  → 查 Binance 买一价
  OKX MCP      → 查 OKX 买一价
  → 三个结果回到 context → LLM 自行比价
  → 再选最优平台 → 再调对应 MCP 下单
  → 4 次 tool call，3 个子进程，context 三份数据

Skill 方案:
  SKILL.md: "先调比价 API → 选最优 → 调下单 API"
  apis.yaml: compare_price、place_order 两个接口
  → 2 次 tool call，0 个子进程，context 两条消息
  → 平台差异在内部 HTTP 层消化，Agent 不知道有三个平台
```

**优势 3：问题到 Skill 的动态映射**

当业务增长到几十上百个 Skill 时，不可能把所有 Skill 的完整内容一次性加载到 prompt 中。

Skill 方案的解决方式：**按用户问题动态选择 Skill 组**。

```
Phase 1（当前）:  所有 Skill 元数据一次性加载
Phase 2（演进中）: 问题 → 语义匹配 → 只加载匹配的 Skill 组
Phase 3（蓝图）:   问题 → Skill 路由 → 加载 Skill + 关联的子 Skill / 上下文
```

MCP 没有这个能力——428 个 Tool 要么全加载要么白名单过滤（用户手动配置，不灵活）。

**优势 4：内部标准，完全可控**

- 接口粒度由我们自己决定（只暴露需要的，不暴露无关的）
- 返回格式统一（`{code, message, data}`）
- 业务逻辑和接口定义放在一起（SKILL.md + apis.yaml 同目录）
- 跨平台聚合可以在内部 HTTP 层完成，Agent 无感知

---

## 4. MCP vs Skill：什么时候用哪个

### 4.1 MCP 的价值：解决"有没有"

社区有现成的 MCP Server，一行命令就能用。不需要了解对方的 API 细节，不需要维护接口文档。

**适用场景：**

- 接入第三方外部工具（Brave Search、Gate、Filesystem）
- 快速原型验证（"先跑起来看看效果"）
- 跨语言工具（Node.js、Go 写的 MCP Server）

### 4.2 Skill 的价值：解决"好不好"

不是"能不能调这个接口"，而是"怎么调得更好、更精准、更高效"。

**适用场景：**

- 内部业务系统，接口我们可以定义和控制
- 需要跨平台/多来源聚合为一个统一接口
- 需要业务 SOP 编排（不是孤立的 Tool 调用）
- 需要精准控制 context 大小和 prompt 质量
- 需要按用户问题动态选择工具集

### 4.3 本质区别

```
MCP:   解决 "有没有" — 社区有现成的，拿来就用，平台方维护
Skill: 解决 "好不好" — 知道要用哪些、如何编排成 SOP、怎么把质量做好
```

两者不是替代关系。MCP 适合"我不知道要不要用，先用社区的试试"；Skill 适合"我清楚要做什么，我需要把这件事做到极致"。

---

## 5. 关于"为什么不用 MCP"的工程化论证

> 这是一段附加讨论，源自真实工程场景中的技术选型辩论。我们选择了 Skill + apis.yaml 方案而没有使用 MCP，以下是对这个决策的完整论证。

### 5.1 反驳"Skill 是多余工作"

常见质疑：*"MCP 已经是行业标准了，你们自己封装 apis.yaml 是不是在重复造轮子？"*

**不是。** MCP 和我们做的是两个不同层面的问题：

| MCP 解决的 | Skill 解决的 |
|------|------|
| Tool 的**通信协议**标准化 | Tool 的**业务编排**标准化 |
| Agent 怎么**发现**工具 | Agent 怎么**用好**工具 |
| 连接层 | 应用层 |

MCP 定义了"Agent 和 Server 之间怎么传 JSON"，Skill 定义了"这个业务有什么 API、调用的先后顺序是什么、参数怎么组合"。

两者不在同一个抽象层上。MCP 不能替代 Skill 中的 SOP、跨平台聚合、动态 Skill 加载、context 精确控制。Skill 也不能替代 MCP 的标准化通信协议（如果需要对接外部 MCP Server 的话）。

### 5.2 为什么 Skill 方案在工程化中更优

**第一，Tool 数量控制。**

一个 MCP Server 动辄暴露几百个 Tool。三个外部平台就是上千个。LLM context 直接炸。Skill 方案中永远只有 1 个 `call_internal_api`，context 是 O(1) 的。**这就是为什么大型 AI Agent 系统几乎不直接用 MCP，而是在自己的体系内部做 Tool 聚合。**

**第二，SOP 是 LLM 的"导航"。**

没有 SOP 的 428 个 Tool 就像给一个人一张没有路径的地图。有 SOP 的 Skill 给了一张有路线指引的地图。LLM 不是不会用 428 个 Tool，而是会迷路——选错 Tool、漏掉步骤、参数拼错。**SOP 的价值不是"能不能"，而是"好不好"。**

**第三，动态 Skill 加载是 LLM 上下文管理的关键。**

当 Skill 库增长到几十上百个时，一次性全量加载 = prompt 污染。我们的方案可以通过"问题 → Skill 组"的映射实现按需加载，MCP 只能靠用户手动配置白名单。

**第四，跨平台聚合能力。**

如果需要同时对接 Gate、Binance、OKX 三家交易所的行情数据，MCP 方案需要分别连接三个 Server，三次 tool call，三份数据塞进 context。Skill 方案在内部 HTTP 层做聚合，对外只有一个 `compare_price` 接口，Agent 无感知。

### 5.3 我们的方案本质上是在做什么

不是"不用 MCP"，是**建了一个比 MCP 更高层的、面向业务的 Tool 编排层**。底层通信可以是 HTTP、可以是内部 RPC，未来也可以接 MCP。LLM 不需要知道底层是怎么实现的，它只需要看到精炼后的、带有 SOP 的、按意图分组的 Tool。

```
┌──────────────────────────────────────────────────────┐
│                   Skill 编排层（我们做的）              │
│  - SOP 流程定义                                       │
│  - 问题→Skill 组映射                                  │
│  - 跨平台聚合                                         │
│  - Context 精确控制                                    │
├──────────────────────────────────────────────────────┤
│                   Tool 通信层                          │
│  - HTTP（当前主力）                                    │
│  - MCP（未来可接入的扩展通道）                          │
│  - gRPC / 内部 RPC                                   │
└──────────────────────────────────────────────────────┘
```

**我们建的是上层，MCP 是底层通道之一。两者不是一个层面的东西。**

---

## 6. 总结

- MCP 提供标准化通信，适合快速接入社区工具
- Skill 提供业务编排，适合构建高质量的内部 Agent 系统
- 两者互补：日常主力用 Skill，MCP 作为外部扩展通道
- 工程化角度，Skill 在 Tool 数量控制、SOP 编排、动态加载、跨平台聚合四个维度上显著优于直接使用多个 MCP Server
- 本质上不是"用不用 MCP"的问题，而是"在哪一层做 Tool 编排"的问题——我们选择在更高层做
