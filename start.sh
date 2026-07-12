#!/bin/bash
set -e

cd "$(dirname "$0")"

# 确保 PG 容器运行
if ! docker ps --filter name=trading-pg --format '{{.Names}}' | grep -q trading-pg; then
    echo ">>> 启动 PostgreSQL 容器..."
    docker start trading-pg 2>/dev/null || docker run -d \
        --name trading-pg \
        -e POSTGRES_USER=trading \
        -e POSTGRES_PASSWORD=trading123 \
        -e POSTGRES_DB=trading_agent \
        -p 5432:5432 \
        postgres:16-alpine
    echo ">>> 等待 PG 就绪..."
    sleep 2
fi

echo ">>> 启动服务 http://localhost:8000"
.venv/bin/uvicorn src.api:app --host 0.0.0.0 --port 8000 --reload
