"""Inference proxy — forwards chat to the model's inference endpoint.

Stoker never runs inference. It proxies to llama-server (or equivalent),
streams tokens back via SSE with typed events, and supports explicit
cancellation. Prompt bodies are never written to logs.
"""
import asyncio
import json
import uuid
from typing import AsyncGenerator, Optional

import httpx
from pydantic_settings import BaseSettings

from .models import ChatRequest, ChatSession, utcnow


class Settings(BaseSettings):
    inference_url: str = "http://127.0.0.1:8080"

    class Config:
        env_file = ".env"


settings = Settings()

# In-memory session store (v0.1). Metadata only — prompt bodies excluded
# from all operational logging per Oracle P1-7.
_sessions: dict[str, ChatSession] = {}
# in-flight generation tasks for cancellation
_tasks: dict[str, asyncio.Task] = {}


def create_session(model: str) -> ChatSession:
    s = ChatSession(id=f"sess_{uuid.uuid4().hex[:12]}", model=model)
    _sessions[s.id] = s
    return s


def get_session(sid: str) -> Optional[ChatSession]:
    return _sessions.get(sid)


def delete_session(sid: str) -> bool:
    return _sessions.pop(sid, None) is not None


def list_sessions() -> list[ChatSession]:
    return list(_sessions.values())


async def stream_chat(req: ChatRequest) -> AsyncGenerator[str, None]:
    """Yield SSE-formatted typed events. Never logs prompt bodies."""
    op_id = f"op_{uuid.uuid4().hex[:12]}"
    yield _sse("chat.start", {"operation_id": op_id, "model": req.model,
                             "timestamp": utcnow()})
    payload = {
        "model": req.model,
        "messages": req.messages,
        "stream": True,
    }
    if req.system_prompt:
        payload["messages"] = (
            [{"role": "system", "content": req.system_prompt}]
            + req.messages
        )
    for k in ("temperature", "top_p", "max_tokens"):
        v = getattr(req, k)
        if v is not None:
            payload[k] = v

    url = settings.inference_url.rstrip("/") + "/v1/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream("POST", url, json=payload) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode()[:500]
                    yield _sse("chat.error", {
                        "operation_id": op_id,
                        "message": f"inference endpoint returned {resp.status_code}",
                        "detail": body,
                        "timestamp": utcnow(),
                    })
                    return
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk["choices"][0]["delta"].get("content", "")
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                    if delta:
                        yield _sse("chat.token", {
                            "operation_id": op_id, "delta": delta,
                            "timestamp": utcnow(),
                        })
    except httpx.ConnectError:
        yield _sse("chat.error", {
            "operation_id": op_id,
            "message": "cannot reach inference endpoint",
            "detail": settings.inference_url,
            "timestamp": utcnow(),
        })
        return
    yield _sse("chat.done", {"operation_id": op_id,
                            "timestamp": utcnow()})


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def cancel_generation(operation_id: str) -> bool:
    task = _tasks.pop(operation_id, None)
    if task and not task.done():
        task.cancel()
        return True
    return False
