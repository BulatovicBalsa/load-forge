from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import httpx

from .auth import run_auth_login
from .context import (
    resolve_env,
    resolve_variables,
    build_context,
    resolve_target,
)
from .load_executor import run_load_test_async
from .load_result import LoadTestResult
from .metric_thresholds import evaluate_metric_thresholds
from .metrics import MetricsSummary
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


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


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


def _run_auth_sync(base_url: str, t, ctx, transport=None) -> tuple[Optional[bool], Optional[str]]:
    """
    Run auth login synchronously (once, before the load test begins).
    """
    if t.auth is None:
        return None, None

    sync_transport = transport if isinstance(transport, httpx.MockTransport) else None
    with httpx.Client(base_url=base_url, transport=sync_transport) as auth_client:
        try:
            _execute_auth(auth_client, t, ctx)
            return True, None
        except Exception as e:
            return False, str(e)


# ---------------------------------------------------------------------------
# Load parameters
# ---------------------------------------------------------------------------


def _resolve_load_params(t) -> tuple[int, float, float]:
    """
    Extract (num_users, ramp_up_seconds, duration_seconds) from the test
    model. If no load block is present, defaults to single-pass mode."""
    if t.load is not None and t.load.users > 0:
        return (
            t.load.users,
            t.load.ramp_up.total_seconds(),
            t.load.duration.total_seconds(),
        )
    return 1, 0.0, 0.0


# ---------------------------------------------------------------------------
# Empty summary helper
# ---------------------------------------------------------------------------

_EMPTY_SUMMARY = MetricsSummary(
    total_requests=0,
    successful_requests=0,
    failed_requests=0,
    error_rate=0.0,
    latency_min_ms=0.0,
    latency_max_ms=0.0,
    latency_avg_ms=0.0,
    latency_p50_ms=0.0,
    latency_p95_ms=0.0,
    latency_p99_ms=0.0,
    requests_per_sec=0.0,
    duration_seconds=0.0,
)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_test(
    model: TestFile,
    *,
    transport=None,
    control_stdin: bool = False,
    env_file_dir: Optional[Path] = None,
) -> LoadTestResult:
    """
    Run the test described by *model*.
    
    Args:
        model: Parsed test model
        transport: Optional HTTP transport (for testing)
        control_stdin: Enable stdin control
        env_file_dir: Directory for resolving relative CSV paths (usually .lf or .env file directory)
    """
    t = _get_test(model)
    base_url, ctx = _build_runtime_context(t)
    num_users, ramp_up_seconds, duration_seconds = _resolve_load_params(t)

    # If auth uses CSV file, skip global auth - each VU will auth individually
    use_csv_auth = t.auth and t.auth.file
    
    auth_success: Optional[bool] = None
    auth_error: Optional[str] = None
    
    if not use_csv_auth:
        # Run auth synchronously before the load test (single shared token).
        auth_success, auth_error = _run_auth_sync(base_url, t, ctx, transport=transport)

        if auth_success is False:
            return LoadTestResult(
                test_name=t.name.strip().strip('"'),
                users=num_users,
                ramp_up_seconds=ramp_up_seconds,
                target_duration_seconds=duration_seconds,
                summary=_EMPTY_SUMMARY,
                auth_success=auth_success,
                auth_error=auth_error,
                interrupted=False,
                stop_reason=None,
                metric_threshold_checks=0,
                metric_threshold_failures=[],
            )

    # Run the load test (or single-pass functional test).
    metrics = asyncio.run(
        run_load_test_async(
            test=t,
            base_url=base_url,
            ctx=ctx,
            num_users=num_users,
            ramp_up_seconds=ramp_up_seconds,
            duration_seconds=duration_seconds,
            transport=transport,
            control_stdin=control_stdin,
            env_file_dir=env_file_dir,
        )
    )

    summary = metrics.summary()
    metric_threshold_checks = len(t.metrics.checks) if t.metrics is not None else 0
    metric_threshold_failures = (
        evaluate_metric_thresholds(t.metrics, summary)
        if not metrics.interrupted
        else []
    )

    # If CSV auth was used, determine auth success based on whether any requests succeeded
    if use_csv_auth:
        # If test ran for expected duration but no requests were made, auth likely failed
        if not metrics.interrupted and summary.total_requests == 0 and duration_seconds > 0:
            auth_success = False
            auth_error = "Authentication failed for all users (no requests completed)"
        elif not metrics.interrupted:
            auth_success = True

    return LoadTestResult(
        test_name=t.name.strip().strip('"'),
        users=num_users,
        ramp_up_seconds=ramp_up_seconds,
        target_duration_seconds=duration_seconds,
        summary=summary,
        auth_success=auth_success,
        auth_error=auth_error,
        interrupted=metrics.interrupted,
        stop_reason=metrics.stop_reason,
        metric_threshold_checks=metric_threshold_checks,
        metric_threshold_failures=metric_threshold_failures,
    )
