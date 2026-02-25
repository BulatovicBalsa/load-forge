from typing import Optional

import httpx

from .auth import run_auth_login
from .context import (
    resolve_env,
    resolve_variables,
    build_context,
    resolve_target,
)
from .executor import run_scenario
from .run_result import RunResult, ScenarioResult, AuthResult
from .timing import timed
from ..model import TestFile


def _get_test(model: TestFile):
    if model.test is None:
        raise RuntimeError("Invalid model: missing test block.")
    return model.test


def _build_runtime_context(t) -> tuple[str, dict[str, str]]:
    env_map = resolve_env(t.environment)
    vars_map = resolve_variables(t.variables, env_map)
    ctx = build_context(env_map, vars_map)

    base_url = resolve_target(t.target, ctx)
    if not base_url:
        raise RuntimeError("Missing target.")

    return base_url, ctx


def _run_auth_if_present(client, t, ctx) -> Optional[AuthResult]:
    if t.auth is None:
        return None

    try:
        _, duration = _run_auth_timed(client, t, ctx)
        success = True
        error = None
    except Exception as e:
        duration = 0.0
        success = False
        error = str(e)

    endpoint_str = "<missing-endpoint>"
    if t.auth.endpoint is not None:
        if getattr(t.auth.endpoint, "value", ""):
            endpoint_str = t.auth.endpoint.value.strip().strip('"')
        elif getattr(t.auth.endpoint, "ref", None) is not None:
            endpoint_str = f"#{t.auth.endpoint.ref.name}"

    return AuthResult(
        endpoint=endpoint_str,
        method=t.auth.method,
        duration_seconds=duration,
        success=success,
        error=error,
    )


def _execute_auth(client, t, ctx):
    token = run_auth_login(client, t.auth, ctx)

    if "authToken" in ctx:
        raise RuntimeError("Reserved name conflict: 'authToken' already defined.")

    ctx["authToken"] = token
    client.headers["Authorization"] = f"Bearer {token}"

    return token


@timed
def _run_auth_timed(client, t, ctx):
    return _execute_auth(client, t, ctx)


def _run_scenarios(
    client: httpx.Client,
    t,
    ctx: dict[str, str],
) -> list[ScenarioResult]:
    results: list[ScenarioResult] = []

    for sc in t.scenarios:
        name = sc.name.strip().strip('"')
        r = ScenarioResult(name=name)

        try:
            r.requests = run_scenario(client, sc, ctx)
            r.success = True
        except Exception as e:
            r.success = False
            r.error = str(e)

        results.append(r)

    return results


def _run_test_internal(model: TestFile, transport=None) -> RunResult:
    t = _get_test(model)
    base_url, ctx = _build_runtime_context(t)

    with httpx.Client(base_url=base_url, transport=transport) as client:
        auth_result = _run_auth_if_present(client, t, ctx)
        if auth_result and not auth_result.success:
            return RunResult(
                test_name=t.name.strip().strip('"'),
                duration_seconds=0.0,
                scenarios=[],
                auth=auth_result,
            )

        scenarios = _run_scenarios(client, t, ctx)

    return RunResult(
        test_name=t.name.strip().strip('"'),
        duration_seconds=0.0,
        scenarios=scenarios,
        auth=auth_result,
    )


@timed
def _run_test_timed(model: TestFile, transport=None):
    return _run_test_internal(model, transport)


def run_test(model: TestFile, *, transport=None) -> RunResult:
    result, duration = _run_test_timed(model, transport)
    result.duration_seconds = duration
    return result
