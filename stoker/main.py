"""Stoker backend — FastAPI app.

Routes:
  POST /api/v1/auth/login      token -> session cookie
  POST /api/v1/auth/logout     revoke session
  POST /api/v1/auth/rotate     rotate session
  GET  /api/v1/hearth/models
  POST /api/v1/hearth/models/{id}/load
  POST /api/v1/hearth/models/{id}/unload
  GET  /api/v1/hearth/models/{id}/operations/{op}
  GET  /api/v1/hearth/vram
  GET  /api/v1/hearth/events            (SSE, typed)
  POST /api/v1/inference/chat           (SSE streaming)
  POST /api/v1/inference/chat/{op}/cancel
  GET  /api/v1/inference/models         (SERVING only)
  GET  /api/v1/inference/sessions
  DELETE /api/v1/inference/sessions/{id}
  GET  /api/v1/system/health
  GET  /api/v1/system/health/stream     (SSE 1Hz)
  GET  /api/v1/system/alerts
  GET  /                              (serves PWA)

Binds to the Tailscale interface only. Never 0.0.0.0.
"""
import asyncio
import json
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from . import auth
from . import hearth as hearth_mod
from . import inference as infer_mod
from . import system as sys_mod
from .models import (
    AcceptedOperation, Alert, ChatRequest, ErrorDetail, ErrorEnvelope,
    HealthInfo, ModelInfo, OpState, PinStatus, VramInfo, new_op_id, utcnow,
)
from .operations import registry


class LoginBody(BaseModel):
    token: str


class LoadBody(BaseModel):
    idempotency_key: Optional[str] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="Stoker", version="0.1.0", lifespan=lifespan)


def err(code: str, message: str, status: int = 500,
        operation_id: Optional[str] = None,
        retryable: bool = False) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=ErrorEnvelope(error=ErrorDetail(
            code=code, message=message, operation_id=operation_id,
            retryable=retryable)).model_dump(),
    )


# --- Auth ---

@app.post("/api/v1/auth/login")
async def login(body: LoginBody):
    if not auth.verify_init_token(body.token):
        return err("INVALID_TOKEN", "invalid token", 401)
    sid = auth.create_session()
    return auth.session_cookie_response(sid, {
        "status": "ok", "timestamp": utcnow()})


@app.post("/api/v1/auth/logout")
async def logout(sid: str = Depends(auth.require_session)):
    auth.revoke_session(sid)
    return auth.clear_session_cookie(JSONResponse({"status": "ok"}))


@app.post("/api/v1/auth/rotate")
async def rotate(sid: str = Depends(auth.require_session)):
    new_sid = auth.rotate_session(sid)
    if not new_sid:
        return err("SESSION_INVALID", "session invalid", 401)
    return auth.session_cookie_response(new_sid, {"status": "rotated"})


# --- Hearth ---

@app.get("/api/v1/hearth/models", response_model=list[ModelInfo])
async def hearth_models(sid: str = Depends(auth.require_session)):
    return await hearth_mod.list_models()


# NOTE (v0.1.2): Model lifecycle mutations (load/unload) are out of scope
# for the first integration slice. They return 501 until the adapters are
# verified against live Hearth. Read-only telemetry only.

@app.post("/api/v1/hearth/models/{model_id}/load")
async def hearth_load(model_id: str, body: LoadBody,
                      sid: str = Depends(auth.require_session)):
    return err("NOT_IMPLEMENTED",
               "model lifecycle mutations disabled in v0.1.2 "
               "(read-only integration slice)", 501)


@app.post("/api/v1/hearth/models/{model_id}/unload")
async def hearth_unload(model_id: str, body: LoadBody,
                        sid: str = Depends(auth.require_session)):
    return err("NOT_IMPLEMENTED",
               "model lifecycle mutations disabled in v0.1.2 "
               "(read-only integration slice)", 501)


@app.get("/api/v1/hearth/models/{model_id}/operations/{op_id}")
async def hearth_op(model_id: str, op_id: str,
                    sid: str = Depends(auth.require_session)):
    op = registry.get(op_id)
    if not op:
        return err("OP_NOT_FOUND", "operation not found", 404,
                   operation_id=op_id)
    return op


@app.get("/api/v1/hearth/vram", response_model=VramInfo)
async def hearth_vram(sid: str = Depends(auth.require_session)):
    return await hearth_mod.get_vram()


@app.get("/api/v1/hearth/reachable")
async def hearth_reachable(sid: str = Depends(auth.require_session)):
    """Liveness probe for the acceptance test."""
    ok = await hearth_mod.hearth_reachable()
    return {"hearth_reachable": ok, "timestamp": utcnow()}


@app.get("/api/v1/hearth/events")
async def hearth_events(request: Request,
                        sid: str = Depends(auth.require_session)):
    async def gen():
        last: dict[str, str] = {}
        while True:
            if await request.is_disconnected():
                break
            models = await hearth_mod.list_models()
            changed = False
            for m in models:
                if last.get(m.id) != m.state.value:
                    last[m.id] = m.state.value
                    changed = True
                    yield {"event": "model.state",
                           "data": json.dumps(m.model_dump())}
            if not changed:
                yield {"event": "ping",
                       "data": json.dumps({"timestamp": utcnow()})}
            await asyncio.sleep(2)
    return EventSourceResponse(gen())


# --- Inference ---

@app.post("/api/v1/inference/chat")
async def inference_chat(req: ChatRequest,
                         sid: str = Depends(auth.require_session)):
    # Source of truth: Hearth /v1/models (serving availability).
    # Residency != readiness — only SERVING models are chattable.
    serving = await hearth_mod.list_serving()
    serving_ids = {m.id for m in serving}
    if req.model not in serving_ids:
        return err("MODEL_NOT_SERVING",
                   f"model '{req.model}' is not serving "
                   f"(residency != readiness)", 409)
    return EventSourceResponse(infer_mod.stream_chat(req))


@app.post("/api/v1/inference/chat/{op_id}/cancel")
async def inference_cancel(op_id: str,
                           sid: str = Depends(auth.require_session)):
    ok = infer_mod.cancel_generation(op_id)
    return {"cancelled": ok}


@app.get("/api/v1/inference/models")
async def inference_models(sid: str = Depends(auth.require_session)):
    return await hearth_mod.list_serving()


@app.get("/api/v1/inference/sessions")
async def inference_sessions(sid: str = Depends(auth.require_session)):
    return infer_mod.list_sessions()


@app.delete("/api/v1/inference/sessions/{sess_id}")
async def inference_del_session(sess_id: str,
                                sid: str = Depends(auth.require_session)):
    if not infer_mod.delete_session(sess_id):
        return err("SESSION_NOT_FOUND", "session not found", 404)
    return {"status": "deleted"}


# --- System ---

@app.get("/api/v1/system/health", response_model=HealthInfo)
async def system_health(sid: str = Depends(auth.require_session)):
    return sys_mod.get_health()


@app.get("/api/v1/system/health/stream")
async def system_health_stream(request: Request,
                               sid: str = Depends(auth.require_session)):
    async def gen():
        while True:
            if await request.is_disconnected():
                break
            h = sys_mod.get_health()
            yield {"event": "health",
                   "data": json.dumps(h.model_dump())}
            await asyncio.sleep(1)
    return EventSourceResponse(gen())


@app.get("/api/v1/system/alerts")
async def system_alerts(sid: str = Depends(auth.require_session)):
    h = sys_mod.get_health()
    alerts = sys_mod.check_alerts(h)
    # VRAM alert
    total, used = sys_mod.get_gpu_memory()
    if total and used and used / total > 0.95:
        alerts.append({"id": "vram-critical", "severity": "critical",
                       "message": "VRAM usage exceeds 95%",
                       "timestamp": utcnow()})
    return alerts


# --- PWA static ---

app.mount("/", StaticFiles(directory="static", html=True), name="static")
