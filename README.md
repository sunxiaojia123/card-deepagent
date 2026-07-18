# 交易助手 Deep Agents

基于 [Deep Agents SDK](https://docs.langchain.com/oss/python/deepagents) 的智能加密货币交易助手框架。支持多用户隔离、三种输出类型（文本/卡片/弹窗）、动态 Skill 系统、以及按用户隔离的 MCP 工具集成。

## 项目状态

| Phase | 内容 | 状态 |
|-------|------|------|
| 1 | 基础对话 + SSE 流式 + 前端 | ✅ |
| 2 | User Skill 隔离 + CRUD | ✅ |
| 3 | Card 输出 + 通用 API 执行方案 | ✅ |
| 4 | Popup 澄清 + Resume | ✅ |
| 5 | MCP 按用户 + 前端管理面板 | ✅ |
| 6 | 生产加固（限流/超时/追踪） | ⏳ |

**128 tests, zero regression.**

## 快速开始

### 前置条件

- Python 3.12+
- Docker（用于 PostgreSQL）
- Node.js（用于 npx 启动 MCP server）

### 安装

```bash
# 创建虚拟环境
python -m venv .venv && source .venv/bin/activate

# 安装依赖
pip install -e ".[dev]"

# 配置环境变量
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY
```

### 启动

```bash
./start.sh
```

- 交易助手：http://localhost:8000
- Mock API：http://localhost:9000

### 开发安装（无 Docker）

```bash
# 安装 PostgreSQL 并创建数据库
createdb trading_agent

# 直接启动
uvicorn src.api:app --host 0.0.0.0 --port 8000 --reload
```

## 架构

```
用户浏览器 (SSE)
      │
      ▼
┌─────────────────────────────────┐
│  FastAPI (src/api.py)            │
│  - JWT mock → user_id            │
│  - thread_id → checkpoint        │
│  - SSE stream (event protocol)   │
│  - Popup resume (Command/Resume) │
└──────────────┬──────────────────┘
               │
┌──────────────▼──────────────────┐
│  Agent (src/agent.py)            │
│  create_deep_agent + Middleware  │
│  ┌─────────────────────────────┐ │
│  │ UserMCPMiddleware           │ │  按 user 动态注入 MCP tools
│  │ TradingOutputMiddleware     │ │  拦截 card 推 custom stream
│  │ SkillsMiddleware (SDK)      │ │  加载 base/user skills
│  │ FilesystemMiddleware (SDK)  │ │  文件读写工具
│  └─────────────────────────────┘ │
└──────────────┬──────────────────┘
               │
┌──────────────▼──────────────────┐
│  存储层                          │
│  ┌─────────────────────────────┐ │
│  │ PostgreSQL (Docker)         │ │
│  │ - checkpoints               │ │  LangGraph 对话状态
│  │ - conversations             │ │  业务会话映射
│  │ - user_mcp_configs          │ │  MCP 配置
│  └─────────────────────────────┘ │
│  ┌─────────────────────────────┐ │
│  │ FilesystemBackend           │ │  skills/base/ 物理文件
│  │ StoreBackend (InMemoryStore)│ │  skills/user/ 用户文件
│  └─────────────────────────────┘ │
└─────────────────────────────────┘
```

## 输出协议

所有对话输出通过 SSE（Server-Sent Events）统一推送，协议格式：

```
event: <type>
data: <json>
```

| Event | 说明 | 触发条件 |
|-------|------|---------|
| `text` | LLM 文本 token | 逐字流式输出 |
| `tool` | 工具调用结果 | ToolNode 执行完成 |
| `card` | 卡片 JSON 数据 | show_type=card 的 API 返回 |
| `popup` | 确认弹窗 | LLM 意图模糊时调用 confirm_popup |
| `status` | 执行状态 | thinking / tool_call / tool_done |
| `interrupt` | Graph 暂停信号 | popup 等待用户选择 |
| `done` | 流结束 | agent 执行完成 |
| `error` | 异常 | 捕获未处理错误 |

## 项目结构

```
├── config/
│   └── settings.py          # 配置中心（环境变量 + 默认值）
├── src/
│   ├── agent.py             # build_agent() 工厂函数 + System Prompt
│   ├── api.py               # FastAPI app + 全部 HTTP 端点
│   ├── backend.py           # CompositeBackend + Skill 文件管理
│   ├── checkpointer.py      # Postgres AsyncPostgresSaver
│   ├── context.py           # TradingContext TypedDict
│   ├── db.py                # PG 表管理 (conversations + user_mcp_configs)
│   ├── stream.py            # SSE 适配器 (agent.astream → event dict)
│   ├── mock_server.py       # Mock API 服务 (端口 9000)
│   ├── mcp/
│   │   ├── loader.py        # MCP 工具加载器 (load_mcp_tools)
│   │   └── cleanup.py       # MCP 连接管理器 (超时 + 统计)
│   ├── middleware/
│   │   ├── trading_output.py # Card 输出拦截
│   │   └── user_mcp.py      # 按用户注入 MCP tools
│   ├── schemas/
│   │   └── trading_result.py # TradingToolResult dataclass
│   └── tools/
│       ├── api_executor.py   # call_internal_api (通用 API 执行)
│       ├── api_schema.py     # API schema 加载与校验
│       └── confirm_popup.py  # Popup 确认 tool
├── skills/
│   └── base/                 # 内置 Skill (order-guide / market-info / gift-card)
│       ├── */SKILL.md        # Skill 定义 + allowed-tools
│       └── */apis.yaml       # API schema (name/path/method/params/show_type)
├── static/
│   └── index.html            # 前端 SPA (聊天 + Skills + MCP 管理)
├── tests/
│   ├── test_mcp_api.py       # MCP 配置 CRUD 测试
│   ├── test_mcp_loader.py    # MCP 加载器测试
│   ├── test_mcp_cleanup.py   # 连接管理测试
│   ├── test_mcp_e2e.py       # MCP 端到端（真实 server）
│   ├── test_user_mcp_middleware.py # 中间件测试
│   └── ...                   # 共 20 个测试文件
├── start.sh                  # 一键启动脚本
├── pyproject.toml
├── 实施文档.md                # 完整架构方案
├── 任务拆分.md                # 任务规划大纲
└── 开发进度.md                # 实际完成记录
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| POST | `/conversations` | 创建会话 |
| GET | `/conversations` | 列出用户会话 |
| POST | `/conversations/{id}/chat/stream` | SSE 流式对话 |
| GET | `/conversations/{id}/history` | 获取历史消息 |
| POST | `/conversations/{id}/resume` | Popup 选择后恢复 |
| GET | `/users/me/skills` | 列出用户 Skill |
| POST | `/users/me/skills` | 创建 Skill |
| PUT | `/users/me/skills/{name}` | 更新 Skill |
| DELETE | `/users/me/skills/{name}` | 删除 Skill |
| GET | `/users/me/mcp` | 列出 MCP 配置 |
| POST | `/users/me/mcp` | 创建 MCP 配置 |
| PUT | `/users/me/mcp/{id}` | 更新 MCP 配置 |
| DELETE | `/users/me/mcp/{id}` | 删除 MCP 配置 |

认证方式：`Authorization: Bearer <user-id>` (mock JWT)

## 前端

纯 HTML/CSS/JS 单页面应用（`static/index.html`），无框架依赖。

- 深色主题聊天 UI，SSE 流式逐字显示
- 用户切换（localStorage 持久化）：下拉选择 + 新增/删除按钮
- Skills 面板：可折叠，base skill 只读，user skill 可 CRUD，点击查看 API schema
- MCP 服务面板：可折叠，Modal 表单支持 stdio/SSE/streamable_http 三种 transport

## MCP 集成

### 架构

```
DB (user_mcp_configs)
  │
  ▼
loader.py (load_mcp_tools)
  │
  ▼
UserMCPMiddleware
  ├── awrap_model_call: 注入 MCP tools 到 LLM
  └── awrap_tool_call:   拦截未注册 tool → 执行
  │
  ▼
MCPConnectionManager (超时 + 日志 + 统计)
```

### 支持的 Transport

| Transport | 示例 |
|-----------|------|
| stdio | `npx -y @modelcontextprotocol/server-sequential-thinking` |
| sse | `https://mcp.example.com/sse` |
| streamable_http | `https://mcp.example.com/mcp` |

### 预配置测试用户

| 用户 | MCP Server | 工具数 |
|------|-----------|--------|
| user-alice | Sequential Thinking | 1 |
| user-bob | Memory Graph + Gate.io 行情 | 437 |

> `gate-mcp` 提供 428 个公开行情工具（spot/futures/options），无需 API Key。

## 配置

通过 `.env` 文件或环境变量：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_MODEL` | `deepseek:deepseek-v4-pro` | LLM 模型 |
| `POSTGRES_URI` | `postgresql://trading:trading123@localhost:5432/trading_agent` | PG 连接串 |
| `MCP_CONNECT_TIMEOUT` | `30.0` | MCP 连接超时（秒） |
| `MCP_REQUEST_TIMEOUT` | `60.0` | MCP 请求超时（秒） |
| `AGENT_TIMEOUT` | `60.0` | Agent 调用总超时（秒） |
| `RATE_LIMIT_PER_MINUTE` | `20` | 每分钟请求限制 |

## 运行测试

```bash
# 全部测试
pytest tests/ -v

# 仅非 live 测试
pytest tests/ -v -k "not e2e"
```

## 技术栈

- **Agent 运行时**: Deep Agents SDK (`create_deep_agent`)
- **流式输出**: FastAPI + SSE (event protocol)
- **对话持久化**: LangGraph `AsyncPostgresSaver` + Docker PostgreSQL
- **MCP 工具集成**: `langchain-mcp-adapters` + 自研 Middleware
- **前端**: Vanilla HTML/CSS/JS SPA
- **测试**: pytest + pytest-asyncio (128 tests)
