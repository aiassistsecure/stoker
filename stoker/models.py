"""Shared Pydantic models: envelopes, operations, telemetry."""
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field
import uuid


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_op_id() -> str:
    return f"op_{uuid.uuid4().hex[:12]}"


# --- Standard envelopes (Oracle P0-4) ---

class ErrorDetail(BaseModel):
    code: str
    message: str
    operation_id: Optional[str] = None
    timestamp: str = Field(default_factory=utcnow)
    retryable: bool = False


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


class AcceptedOperation(BaseModel):
    operation_id: str = Field(default_factory=new_op_id)
    status: str = "accepted"
    resource: Optional[str] = None
    timestamp: str = Field(default_factory=utcnow)


# --- Operation state machine (Oracle P0-3) ---

class OpState(str, Enum):
    DECLARED = "DECLARED"
    LOADING = "LOADING"
    WARMING = "WARMING"
    RESIDENT = "RESIDENT"
    SERVING = "SERVING"
    FAILED = "FAILED"
    STOPPED = "STOPPED"
    LOST = "LOST"
    UNKNOWN = "UNKNOWN"


class Operation(BaseModel):
    operation_id: str = Field(default_factory=new_op_id)
    kind: str  # "load" | "unload" | "restart" | "chat"
    resource: Optional[str] = None
    state: OpState = OpState.DECLARED
    detail: Optional[str] = None
    idempotency_key: Optional[str] = None
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)


# --- Hearth ---

class ModelInfo(BaseModel):
    id: str
    state: OpState
    residency_detail: Optional[str] = None  # e.g. Lost reason
    vram_bytes: Optional[int] = None
    endpoint_ready: bool = False  # inference readiness ≠ residency
    last_updated: str = Field(default_factory=utcnow)


class VramInfo(BaseModel):
    total_bytes: Optional[int] = None
    used_bytes: Optional[int] = None
    free_bytes: Optional[int] = None
    models: list[ModelInfo] = []
    timestamp: str = Field(default_factory=utcnow)
    stale: bool = False


# --- Telemetry (Oracle P1-6: null for unavailable, never fabricated) ---

class FanState(str, Enum):
    UNKNOWN = "unknown"
    RUNNING = "running"
    STOPPED = "stopped"


class HealthInfo(BaseModel):
    gpu_temp_c: Optional[float] = None
    gpu_util_pct: Optional[float] = None
    gpu_throttling: Optional[bool] = None
    fan_state: FanState = FanState.UNKNOWN
    fan_rpm: Optional[int] = None  # null when not exposed (e.g. external blower)
    cpu_pct: Optional[float] = None
    ram_pct: Optional[float] = None
    disk_free_bytes: Optional[int] = None
    uptime_s: Optional[int] = None
    timestamp: str = Field(default_factory=utcnow)
    stale: bool = False


class Alert(BaseModel):
    id: str
    severity: str  # "info" | "warning" | "critical"
    message: str
    timestamp: str = Field(default_factory=utcnow)


# --- PIN ---

class PinStatus(BaseModel):
    connected: bool
    trust_level: Optional[str] = None
    requests_per_min: Optional[float] = None
    tokens_per_sec: Optional[float] = None
    uptime_s: Optional[int] = None
    last_heartbeat: Optional[str] = None
    last_updated: str = Field(default_factory=utcnow)
    stale: bool = False


# --- Inference ---

class ChatRequest(BaseModel):
    model: str
    messages: list[dict[str, Any]]
    system_prompt: Optional[str] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None
    idempotency_key: Optional[str] = None


class ChatSession(BaseModel):
    id: str
    model: str
    created_at: str = Field(default_factory=utcnow)
    message_count: int = 0
