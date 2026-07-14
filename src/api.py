"""FastAPI 对话接口 — SSE 流式端点 + 会话 CRUD."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from config.settings import settings
from src.agent import build_agent
from src.context import build_context
from fastapi.responses import PlainTextResponse

from src.backend import (
    _restore_from_disk,
    create_user_skill,
    delete_user_skill,
    get_user_skill,
    list_user_skills,
    update_user_skill,
)
from src.db import conversation_exists, create_conversation, init_db, list_conversations
from src.stream import sse_adapter


def _extract_user_id(authorization: str | None = Header(None)) -> str:
    """从 Authorization header 提取 user_id（mock JWT，后续替换为真实鉴权）。"""
    if authorization is None:
        return "anonymous"
    if authorization.startswith("Bearer "):
        return authorization.removeprefix("Bearer ")
    return authorization


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """管理 checkpointer + agent 生命周期."""
    async with AsyncPostgresSaver.from_conn_string(settings.postgres_uri) as saver:
        await saver.setup()
        agent = build_agent(checkpointer=saver, with_skills=True)
        await init_db()
        await _restore_from_disk()
        _app.state.agent = agent
        _app.state.saver = saver
        yield


app = FastAPI(
    title="交易助手 API",
    version="0.1.0",
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.post("/conversations/{conversation_id}/chat/stream")
async def chat_stream(
    conversation_id: str,
    body: dict[str, str],
    user_id: Annotated[str, Depends(_extract_user_id)],
) -> StreamingResponse:
    """SSE 流式对话。

    Path: conversation_id — 会话 ID，映射为 checkpoint thread_id。
    Header: Authorization: Bearer <user-id>
    Body: {"message": "..."}
    """
    message = body.get("message", "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message 不能为空")

    if not await conversation_exists(conversation_id, user_id):
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")

    agent = app.state.agent
    ctx = build_context(user_id, conversation_id)
    config = {
        "configurable": {
            "thread_id": conversation_id,
            "checkpoint_ns": "",
        }
    }

    stream = agent.astream(
        {"messages": [HumanMessage(content=message)]},
        config=config,
        context=ctx,
        stream_mode=["messages", "updates", "custom"],
    )

    async def generate():
        async for event in sse_adapter(stream):
            yield f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/conversations")
async def create_conversation_endpoint(
    user_id: Annotated[str, Depends(_extract_user_id)],
) -> dict:
    """创建新会话，返回 conversation_id."""
    conv = await create_conversation(user_id)
    return {
        "conversation_id": conv.conversation_id,
        "user_id": conv.user_id,
        "created_at": conv.created_at,
    }


@app.get("/conversations")
async def list_conversations_endpoint(
    user_id: Annotated[str, Depends(_extract_user_id)],
) -> dict:
    """列出当前用户的所有会话."""
    convs = await list_conversations(user_id)
    return {
        "conversations": [
            {"conversation_id": c.conversation_id, "created_at": c.created_at}
            for c in convs
        ]
    }


@app.get("/conversations/{conversation_id}/history")
async def get_conversation_history(
    conversation_id: str,
    user_id: Annotated[str, Depends(_extract_user_id)],
) -> dict:
    """获取会话历史消息（从 agent state 读取）."""
    if not await conversation_exists(conversation_id, user_id):
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")

    agent = app.state.agent
    config = {
        "configurable": {
            "thread_id": conversation_id,
            "checkpoint_ns": "",
        }
    }
    state = await agent.aget_state(config)
    if state is None or state.values is None:
        return {"messages": []}

    raw_messages = state.values.get("messages", [])
    messages = []
    for m in raw_messages:
        role = _msg_role(m)
        entry = {
            "role": role,
            "content": getattr(m, "content", ""),
        }
        # 携带 artifact（card 数据等）
        artifact = getattr(m, "artifact", None)
        if artifact:
            entry["artifact"] = artifact
        messages.append(entry)
    return {"messages": messages}


def _msg_role(msg) -> str:
    """推断消息角色."""
    type_name = type(msg).__name__
    if "Human" in type_name:
        return "user"
    if "AI" in type_name:
        return "assistant"
    if "Tool" in type_name:
        return "tool"
    return type_name


# ── User Skill CRUD ──


@app.get("/users/me/skills/{skill_name}")
async def get_skill(
    skill_name: str,
    user_id: Annotated[str, Depends(_extract_user_id)],
) -> PlainTextResponse:
    """获取 Skill 文件内容."""
    content = await get_user_skill(user_id, skill_name)
    if content is None:
        raise HTTPException(status_code=404, detail="skill 不存在")
    return PlainTextResponse(content, media_type="text/plain")


@app.get("/users/me/skills/{skill_name}/apis")
async def get_skill_apis(skill_name: str) -> dict:
    """获取 Skill 的 API schema 列表（从 skills/base/ 的 apis.yaml 读取）."""
    from pathlib import Path
    from src.tools.api_schema import load_api_schemas

    skill_dir = Path("skills/base") / skill_name
    if not skill_dir.exists():
        raise HTTPException(status_code=404, detail="skill 不存在")

    schemas = load_api_schemas(skill_dir)
    return {
        "apis": [
            {
                "name": s.name,
                "path": s.path,
                "method": s.method,
                "show_type": s.show_type,
                "description": s.description,
                "params": [
                    {"name": p.name, "type": p.type, "required": p.required, "description": p.description}
                    for p in s.params
                ],
            }
            for s in schemas
        ]
    }


@app.get("/users/me/skills")
async def list_skills(
    user_id: Annotated[str, Depends(_extract_user_id)],
) -> dict:
    """列出当前用户的 Skill 文件."""
    names = await list_user_skills(user_id)
    return {"skills": names}


@app.post("/users/me/skills")
async def create_skill(
    body: dict[str, str],
    user_id: Annotated[str, Depends(_extract_user_id)],
) -> dict:
    """创建 Skill 文件."""
    name = body.get("name", "").strip()
    content = body.get("content", "")
    if not name:
        raise HTTPException(status_code=400, detail="name 不能为空")
    if not content:
        raise HTTPException(status_code=400, detail="content 不能为空")
    await create_user_skill(user_id, name, content)
    return {"name": name, "status": "created"}


@app.put("/users/me/skills/{skill_name}")
async def update_skill(
    skill_name: str,
    body: dict[str, str],
    user_id: Annotated[str, Depends(_extract_user_id)],
) -> dict:
    """更新 Skill 文件."""
    content = body.get("content", "")
    if not content:
        raise HTTPException(status_code=400, detail="content 不能为空")
    ok = await update_user_skill(user_id, skill_name, content)
    if not ok:
        raise HTTPException(status_code=404, detail="skill 不存在")
    return {"name": skill_name, "status": "updated"}


@app.delete("/users/me/skills/{skill_name}")
async def delete_skill(
    skill_name: str,
    user_id: Annotated[str, Depends(_extract_user_id)],
) -> dict:
    """删除 Skill 文件."""
    ok = await delete_user_skill(user_id, skill_name)
    if not ok:
        raise HTTPException(status_code=404, detail="skill 不存在")
    return {"name": skill_name, "status": "deleted"}


@app.get("/health")
async def health():
    return {"status": "ok"}
