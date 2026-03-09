"""
Authentication helpers for load testing.

Provides a single async ``authenticate`` entry-point used by both the
shared-token (static) and per-user (CSV) auth flows.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx
from jsonpath_ng.ext import parse as jsonpath_parse

from .context import resolve_value_or_ref
from .interpolate import interpolate
from .user import User
from ..model import AuthLogin


def _strip_quotes(s: str) -> str:
    return s.strip().strip('"')


@dataclass(frozen=True)
class AuthResult:
    """Outcome of a single authentication attempt."""

    success: bool
    user_display_name: str
    latency_ms: float
    token: Optional[str] = None
    error: Optional[str] = None

    @property
    def headers(self) -> dict[str, str]:
        """Return the Authorization header dict, empty when auth failed."""
        if self.success and self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return {}


def build_auth_payload(
    auth: AuthLogin,
    ctx: dict[str, str],
    user: User,
) -> dict[str, Any]:
    """
    Build the JSON payload for an auth request.
    """
    if auth.body is None:
        raise RuntimeError("auth.login missing body")

    merged_ctx = {**ctx, **user.credentials}

    payload: dict[str, Any] = {}
    for f in auth.body.fields:
        if f.value is None:
            raise RuntimeError(f"auth.login body field '{f.name}' missing value")
        value_str = resolve_value_or_ref(f.value, merged_ctx)
        payload[f.name] = interpolate(value_str, merged_ctx)
    return payload


def extract_token(data: Any, format_expr: str) -> str:
    """
    Extract the auth token from a parsed JSON response using a JSONPath
    *format_expr* (e.g. ``$.access_token``).
    """
    fmt = _strip_quotes(format_expr)
    expr = jsonpath_parse(fmt)
    matches = expr.find(data)
    if not matches:
        raise RuntimeError(f"auth.login token not found using format {fmt}")

    token = matches[0].value
    if not isinstance(token, str) or not token:
        raise RuntimeError("auth.login extracted token is not a non-empty string")
    return token


async def authenticate(
    client: httpx.AsyncClient,
    auth: AuthLogin,
    ctx: dict[str, str],
    user: User,
) -> AuthResult:
    """
    Authenticate *user* against the configured auth endpoint and return an
    ``AuthResult`` containing the token, latency, and success/failure info.
    """
    if auth.endpoint is None:
        return AuthResult(
            success=False,
            user_display_name=user.display_name,
            latency_ms=0.0,
            error="auth.login missing endpoint",
        )

    merged_ctx = {**ctx, **user.credentials}

    start = time.perf_counter()
    try:
        endpoint = resolve_value_or_ref(auth.endpoint, merged_ctx)
        method = auth.method.value
        payload = build_auth_payload(auth, ctx, user)

        resp = await client.request(method, endpoint, json=payload)
        latency_ms = (time.perf_counter() - start) * 1000.0

        resp.raise_for_status()
        token = extract_token(resp.json(), auth.format)

        return AuthResult(
            success=True,
            user_display_name=user.display_name,
            latency_ms=latency_ms,
            token=token,
        )
    except Exception as exc:
        return AuthResult(
            success=False,
            user_display_name=user.display_name,
            latency_ms=(time.perf_counter() - start) * 1000.0,
            error=str(exc),
        )
