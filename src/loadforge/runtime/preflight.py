"""
Preflight connectivity check.

Performs a single lightweight HTTP request to the target server before the
load test begins.  The check is **not timed** and **not counted** in any
metrics
Success criterion: *any* HTTP response (even 404/500) means the server is
up.  Only transport-level failures (connection refused, DNS error, timeout,
TLS errors) count as a preflight failure.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import httpx

PREFLIGHT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class PreflightResult:
    """Outcome of the preflight connectivity check."""

    success: bool
    status_code: Optional[int] = None
    error: Optional[str] = None

    @property
    def display(self) -> str:
        if self.success:
            return f"Preflight: server is reachable (HTTP {self.status_code})"
        return f"Preflight failed: {self.error}"


async def preflight_check(
    base_url: str,
    *,
    transport: Optional[httpx.AsyncBaseTransport] = None,
    timeout: float = PREFLIGHT_TIMEOUT_SECONDS,
) -> PreflightResult:
    """
    Verify that the server at *base_url* is reachable.
    """
    client_kwargs: dict = {
        "base_url": base_url,
        "timeout": httpx.Timeout(timeout),
    }
    if transport is not None:
        client_kwargs["transport"] = transport

    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            response = await client.head("/")
            return PreflightResult(success=True, status_code=response.status_code)
    except httpx.ConnectError as exc:
        return PreflightResult(
            success=False,
            error=f"Connection failed — server at {base_url} is not reachable: {exc}",
        )
    except httpx.ConnectTimeout:
        return PreflightResult(
            success=False,
            error=f"Connection timed out — server at {base_url} did not respond within {timeout}s",
        )
    except httpx.TimeoutException as exc:
        return PreflightResult(
            success=False,
            error=f"Request timed out — server at {base_url} did not respond within {timeout}s: {exc}",
        )
    except httpx.UnsupportedProtocol as exc:
        return PreflightResult(
            success=False,
            error=f"Unsupported protocol for {base_url}: {exc}",
        )
    except Exception as exc:
        # Catch-all for unexpected transport errors (e.g. SSL failures,
        # malformed URLs, etc.) so the preflight never raises — it always
        # returns a result the caller can inspect.
        return PreflightResult(
            success=False,
            error=f"Preflight error for {base_url}: {type(exc).__name__}: {exc}",
        )
