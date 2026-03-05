from typing import Any, Optional

import httpx
from jsonpath_ng.ext import parse as jsonpath_parse

from .context import resolve_value_or_ref
from .interpolate import interpolate
from ..model import AuthLogin


def _strip_quotes(s: str) -> str:
    return s.strip().strip('"')


def run_auth_login(client: httpx.Client, auth: AuthLogin, ctx: dict[str, str]) -> str:
    if auth.endpoint is None:
        raise RuntimeError("auth.login missing endpoint")
    if auth.body is None:
        raise RuntimeError("auth.login missing body")

    endpoint = resolve_value_or_ref(auth.endpoint, ctx)
    method = auth.method

    payload: dict[str, Any] = {}
    for f in auth.body.fields:
        if f.value is None:
            raise RuntimeError(f"auth.login body field '{f.name}' missing value")
        payload[f.name] = resolve_value_or_ref(f.value, ctx)

    resp = client.request(method, endpoint, json=payload)
    resp.raise_for_status()

    fmt = _strip_quotes(auth.format)
    data = resp.json()

    expr = jsonpath_parse(fmt)
    matches = expr.find(data)
    if not matches:
        raise RuntimeError(f"auth.login token not found using format {fmt}")

    token = matches[0].value
    if not isinstance(token, str) or not token:
        raise RuntimeError("auth.login extracted token is not a non-empty string")

    return token


async def authenticate_user_async(
    client: httpx.AsyncClient,
    auth: AuthLogin,
    ctx: dict[str, str],
    user_data: Optional[dict[str, str]] = None,
) -> str:
    """
    Authenticate a user asynchronously with optional CSV user data.
    """
    import re
    
    if auth.endpoint is None:
        raise RuntimeError("auth.login missing endpoint")
    if auth.body is None:
        raise RuntimeError("auth.login missing body")
    
    extended_ctx = {**ctx}
    if user_data:
        extended_ctx.update(user_data)
    
    endpoint = resolve_value_or_ref(auth.endpoint, extended_ctx)
    method = auth.method
    
    # Build request body
    payload: dict[str, Any] = {}
    for f in auth.body.fields:
        if f.value is None:
            raise RuntimeError(f"auth.login body field '{f.name}' missing value")
        
        value_str = resolve_value_or_ref(f.value, extended_ctx)
        
        interpolated_value = interpolate(value_str, extended_ctx)
        
        if "${" in interpolated_value and "}" in interpolated_value:
            placeholders = re.findall(r'\$\{([^}]+)\}', interpolated_value)
            if placeholders and user_data:
                missing_cols = [p for p in placeholders if p not in user_data]
                if missing_cols:
                    raise ValueError(
                        f"CSV missing required column(s): {missing_cols}. "
                        f"Available columns: {list(user_data.keys())}"
                    )
        
        payload[f.name] = interpolated_value
    
    # Send auth request
    resp = await client.request(method, endpoint, json=payload)
    resp.raise_for_status()
    
    # Extract token using JSON path
    fmt = _strip_quotes(auth.format)
    data = resp.json()
    
    expr = jsonpath_parse(fmt)
    matches = expr.find(data)
    if not matches:
        raise RuntimeError(f"auth.login token not found using format {fmt}")
    
    token = matches[0].value
    if not isinstance(token, str) or not token:
        raise RuntimeError("auth.login extracted token is not a non-empty string")
    
    return token
