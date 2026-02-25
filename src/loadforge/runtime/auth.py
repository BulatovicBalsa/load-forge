from typing import Any

import httpx
from jsonpath_ng.ext import parse as jsonpath_parse

from .context import resolve_value_or_ref
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
