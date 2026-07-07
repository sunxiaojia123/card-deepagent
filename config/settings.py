from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    # 模型
    model: str = os.getenv("LLM_MODEL", "deepseek:deepseek-v4-pro")

    # Postgres
    postgres_uri: str = os.getenv(
        "POSTGRES_URI",
        "postgresql://trading:trading123@localhost:5432/trading_agent",
    )

    # API
    api_host: str = os.getenv("API_HOST", "0.0.0.0")
    api_port: int = int(os.getenv("API_PORT", "8000"))

    # Deep Agents
    skills_base_dir: str = os.getenv("SKILLS_BASE_DIR", "skills/base")
    skills_user_prefix: str = "/skills/user/"

    # LangSmith
    langsmith_api_key: str | None = os.getenv("LANGCHAIN_API_KEY", None)
    langsmith_project: str = os.getenv("LANGCHAIN_PROJECT", "trading-agent")

    # MCP
    mcp_connect_timeout: float = float(os.getenv("MCP_CONNECT_TIMEOUT", "30.0"))
    mcp_request_timeout: float = float(os.getenv("MCP_REQUEST_TIMEOUT", "60.0"))

    # 限流
    rate_limit_per_minute: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "20"))

    # Agent
    agent_timeout: float = float(os.getenv("AGENT_TIMEOUT", "60.0"))


settings = Settings()
