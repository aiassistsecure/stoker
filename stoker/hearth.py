"""Hearth adapter — talks to the live Hearth API.

v0.1.2: Replaced assumed `hearth list/load/unload` CLI calls with actual
Hearth contracts:
  GET /residency          live residency state for all declared models
  GET /v1/models          serving availability (inference-ready models)

This slice is READ-ONLY. Model lifecycle mutations (load/unload) and shell
access are out of scope until adapters are verified against live Hearth.
"""
import asyncio
from typing import Optional

import httpx
from pydantic_settings import BaseSettings

from .models import ModelInfo, OpState, VramInfo


class Settings(BaseSettings):
    # Hearth API base URL on HashFactory
    hearth_url: str = "http://127.0.0.1:8377"

    class Config:
        env_file = ".env"


settings = Settings()

_client: Optional[httpx.AsyncClient] = None


def _client_get() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=settings.hearth_url.rstrip("/"), timeout=15)
    return _client


def _map_state(raw: str) -> OpState:
    try:
        return OpState[str(raw).upper()]
    except KeyError:
        return OpState.UNKNOWN


async def _get(path: str) -> Optional[dict]:
    try:
        r = await _client_get().get(path)
        if r.status_code != 200:
            return None
        return r.json()
    except (httpx.ConnectError, httpx.TimeoutException):
        return None


async def list_models() -> list[ModelInfo]:
    """Live residency state from GET /residency."""
    data = await _get("/residency")
    if not data:
        return []
    items = data if isinstance(data, list) else data.get("models", [])
    out: list[ModelInfo] = []
    for m in items:
        out.append(ModelInfo(
            id=str(m.get("id", m.get("name", "unknown"))),
            state=_map_state(m.get("state", "unknown")),
            residency_detail=m.get("detail") or m.get("reason"),
            vram_bytes=m.get("vram_bytes"),
            endpoint_ready=bool(m.get("endpoint_ready", False)),
        ))
    return out


async def list_serving() -> list[ModelInfo]:
    """Inference-ready models from GET /v1/models.

    Residency != readiness: a model in VRAM is not necessarily serving.
    This endpoint is the source of truth for the chat model picker.
    """
    data = await _get("/v1/models")
    if not data:
        return []
    items = data if isinstance(data, list) else data.get("data", [])
    out: list[ModelInfo] = []
    for m in items:
        mid = str(m.get("id", m.get("name", "unknown")))
        out.append(ModelInfo(
            id=mid,
            state=OpState.SERVING,
            vram_bytes=m.get("vram_bytes"),
            endpoint_ready=True,
        ))
    return out


async def get_vram() -> VramInfo:
    """VRAM breakdown: Hearth residency + NVML ground truth."""
    models = await list_models()
    total = used = None
    try:
        from .system import get_gpu_memory
        total, used = get_gpu_memory()
    except Exception:
        pass
    free = (total - used) if total is not None and used is not None else None
    # Cross-check: sum of model VRAM vs NVML used (informational only)
    return VramInfo(
        total_bytes=total,
        used_bytes=used,
        free_bytes=free,
        models=models,
    )


async def hearth_reachable() -> bool:
    """Quick liveness probe for the acceptance test."""
    return await _get("/residency") is not None
