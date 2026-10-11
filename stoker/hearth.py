"""Hearth adapter — dual-uses the hearth CLI, never reimplements residency.

All state transitions flow through the operation registry with explicit
states: DECLARED → LOADING → WARMING → RESIDENT → SERVING.
Residency (VRAM) is tracked independently from inference readiness.
"""
import asyncio
import json
import shutil
import subprocess
from typing import Optional

from pydantic_settings import BaseSettings

from .models import ModelInfo, OpState, VramInfo, utcnow
from .operations import registry


class Settings(BaseSettings):
    hearth_bin: str = "hearth"

    class Config:
        env_file = ".env"


settings = Settings()


def _hearth_bin() -> Optional[str]:
    return shutil.which(settings.hearth_bin)


async def _run_hearth(*args: str, timeout: int = 30) -> tuple[int, str, str]:
    """Run hearth CLI, return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        settings.hearth_bin, *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "", "hearth command timed out"
    return proc.returncode or 0, out.decode(), err.decode()


def _parse_models(raw: str) -> list[ModelInfo]:
    """Parse `hearth list --json` output into ModelInfo list."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    items = data if isinstance(data, list) else data.get("models", [])
    out: list[ModelInfo] = []
    for m in items:
        state_raw = str(m.get("state", "unknown")).upper()
        try:
            state = OpState[state_raw]
        except KeyError:
            state = OpState.UNKNOWN
        out.append(ModelInfo(
            id=str(m.get("id", m.get("name", "unknown"))),
            state=state,
            residency_detail=m.get("detail"),
            vram_bytes=m.get("vram_bytes"),
            endpoint_ready=bool(m.get("endpoint_ready", False)),
        ))
    return out


async def list_models() -> list[ModelInfo]:
    if not _hearth_bin():
        return []
    rc, out, _ = await _run_hearth("list", "--json")
    if rc != 0:
        return []
    return _parse_models(out)


async def get_vram() -> VramInfo:
    """VRAM breakdown. Falls back to NVML when hearth doesn't report."""
    models = await list_models()
    total = used = None
    try:
        from .system import get_gpu_memory
        total, used = get_gpu_memory()
    except Exception:
        pass
    free = (total - used) if total is not None and used is not None else None
    return VramInfo(
        total_bytes=total,
        used_bytes=used,
        free_bytes=free,
        models=models,
    )


async def load_model(
    model_id: str,
    idempotency_key: Optional[str] = None,
) -> str:
    """Start async load. Returns operation_id immediately."""
    op = registry.create("load", resource=model_id,
                         idempotency_key=idempotency_key)
    asyncio.create_task(_do_load(op.operation_id, model_id))
    return op.operation_id


async def _do_load(operation_id: str, model_id: str) -> None:
    registry.transition(operation_id, OpState.LOADING,
                        "dispatching to hearth")
    if not _hearth_bin():
        registry.transition(operation_id, OpState.FAILED,
                            "hearth CLI not found")
        return
    registry.transition(operation_id, OpState.LOADING,
                        "weights streaming into VRAM")
    rc, _, err = await _run_hearth("load", model_id, timeout=600)
    if rc != 0:
        registry.transition(operation_id, OpState.FAILED,
                            err.strip() or "hearth load failed")
        return
    registry.transition(operation_id, OpState.WARMING,
                        "runtime initializing")
    # Verify residency via fresh list
    models = await list_models()
    match = next((m for m in models if m.id == model_id), None)
    if match is None:
        registry.transition(operation_id, OpState.FAILED,
                            "model not found after load")
    elif match.state == OpState.RESIDENT and match.endpoint_ready:
        registry.transition(operation_id, OpState.SERVING, "ready")
    elif match.state == OpState.RESIDENT:
        registry.transition(operation_id, OpState.RESIDENT,
                            "warm in VRAM, endpoint not ready")
    else:
        registry.transition(operation_id, match.state,
                            match.residency_detail)


async def unload_model(
    model_id: str,
    idempotency_key: Optional[str] = None,
) -> str:
    op = registry.create("unload", resource=model_id,
                         idempotency_key=idempotency_key)
    asyncio.create_task(_do_unload(op.operation_id, model_id))
    return op.operation_id


async def _do_unload(operation_id: str, model_id: str) -> None:
    registry.transition(operation_id, OpState.LOADING, "unloading")
    if not _hearth_bin():
        registry.transition(operation_id, OpState.FAILED,
                            "hearth CLI not found")
        return
    rc, _, err = await _run_hearth("unload", model_id, timeout=120)
    if rc != 0:
        registry.transition(operation_id, OpState.FAILED,
                            err.strip() or "hearth unload failed")
        return
    registry.transition(operation_id, OpState.STOPPED, "evicted from VRAM")
