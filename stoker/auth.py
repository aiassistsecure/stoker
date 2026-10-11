"""Cookie-session auth (Oracle P0-1).

Browsers cannot set Authorization headers on EventSource or WebSocket.
Stoker uses short-lived, server-managed sessions via Secure/HttpOnly/
SameSite cookies. Initial login exchanges the high-entropy init token
for a session. Sessions support rotation and revocation.
"""
import secrets
import time
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    stoker_init_token: str = "change-me-on-first-run"
    session_secret: str = "change-me-on-first-run"
    session_ttl_min: int = 120

    class Config:
        env_file = ".env"


settings = Settings()

# In-memory session store: session_id -> expires_at.
# Single-operator tool; a persistent store is unnecessary for v0.1.
_sessions: dict[str, float] = {}

SESSION_COOKIE = "stoker_session"


def _new_session() -> str:
    sid = secrets.token_urlsafe(32)
    _sessions[sid] = time.time() + settings.session_ttl_min * 60
    return sid


def create_session() -> str:
    """Create a session after successful token login."""
    return _new_session()


def revoke_session(sid: str) -> None:
    _sessions.pop(sid, None)


def revoke_all() -> None:
    _sessions.clear()


def rotate_session(old_sid: str) -> Optional[str]:
    """Rotate: revoke old, issue new. Returns None if old was invalid."""
    if not is_valid(old_sid):
        return None
    revoke_session(old_sid)
    return _new_session()


def is_valid(sid: Optional[str]) -> bool:
    if not sid:
        return False
    exp = _sessions.get(sid)
    if exp is None:
        return False
    if time.time() > exp:
        _sessions.pop(sid, None)
        return False
    return True


def verify_init_token(token: str) -> bool:
    # Constant-time compare against the configured init token.
    return secrets.compare_digest(token, settings.stoker_init_token)


async def require_session(
    request: Request,
    stoker_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE),
) -> str:
    # Also accept the session via X-Session header for non-browser clients.
    sid = stoker_session or request.headers.get("X-Session")
    if not is_valid(sid):
        raise HTTPException(status_code=401, detail="unauthorized")
    return sid  # type: ignore[return-value]


def session_cookie_response(sid: str, body: dict) -> JSONResponse:
    resp = JSONResponse(body)
    resp.set_cookie(
        SESSION_COOKIE,
        sid,
        max_age=settings.session_ttl_min * 60,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    return resp


def clear_session_cookie(resp: JSONResponse) -> JSONResponse:
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp
