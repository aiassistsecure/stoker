"""Operation registry: tracks async operations with explicit state machines.

Every load/unload/restart returns an operation_id. Clients poll
GET /hearth/models/{id}/operations/{op} or subscribe to SSE events.
Idempotency keys prevent duplicate destructive operations on retry.
"""
import time
from typing import Optional

from .models import OpState, Operation, utcnow


class OperationRegistry:
    def __init__(self) -> None:
        self._ops: dict[str, Operation] = {}
        # idempotency_key -> operation_id
        self._idem: dict[str, str] = {}

    def create(
        self,
        kind: str,
        resource: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Operation:
        if idempotency_key and idempotency_key in self._idem:
            # Return the existing operation — do NOT duplicate.
            return self._ops[self._idem[idempotency_key]]
        op = Operation(kind=kind, resource=resource,
                       idempotency_key=idempotency_key)
        self._ops[op.operation_id] = op
        if idempotency_key:
            self._idem[idempotency_key] = op.operation_id
        return op

    def transition(
        self,
        operation_id: str,
        state: OpState,
        detail: Optional[str] = None,
    ) -> Optional[Operation]:
        op = self._ops.get(operation_id)
        if op is None:
            return None
        op.state = state
        op.detail = detail
        op.updated_at = utcnow()
        return op

    def get(self, operation_id: str) -> Optional[Operation]:
        return self._ops.get(operation_id)

    def recent(self, limit: int = 20) -> list[Operation]:
        ops = sorted(self._ops.values(),
                     key=lambda o: o.created_at, reverse=True)
        return ops[:limit]


registry = OperationRegistry()
