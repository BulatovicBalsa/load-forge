from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from .context import (
    resolve_env,
    resolve_variables,
    build_context,
    resolve_target,
)
from .load_executor import run_load_test_async
from .load_result import LoadTestResult
from .metric_thresholds import evaluate_metric_thresholds
from .preflight import preflight_check
from .user import UlfUserSource, StaticUserSource, UserSource
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
# User source factory
# ---------------------------------------------------------------------------


def _build_user_source(
    t,
    ctx: dict[str, str],
    userlist_path: Optional[Path],
) -> Optional[UserSource]:
    """
    Inspect the test model and return the appropriate ``UserSource``.

    * If auth is absent → ``None`` (no auth needed).
    * If auth has a ``file`` field → ``UlfUserSource`` (per-user auth from .ulf).
      The *userlist_path* is validated and provided by the CLI.
    * Otherwise → ``StaticUserSource`` (shared token).
    """
    if t.auth is None:
        return None

    if t.auth.file:
        if not userlist_path:
            raise RuntimeError(
                "Test model requires a user list file (.ulf), but no path was provided."
            )
        return UlfUserSource(userlist_path, t.auth)

    return StaticUserSource(ctx)


# ---------------------------------------------------------------------------
# Load parameters
# ---------------------------------------------------------------------------


def _resolve_load_params(t) -> tuple[int, float, float]:
    """
    Extract (num_users, ramp_up_seconds, duration_seconds) from the test
    model.  If no load block is present, defaults to single-pass mode.
    """
    if t.load is not None and t.load.users > 0:
        return (
            t.load.users,
            t.load.ramp_up.total_seconds(),
            t.load.duration.total_seconds(),
        )
    return 1, 0.0, 0.0


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


def _run_preflight(base_url: str, transport=None) -> None:
    """
    Execute the preflight connectivity check synchronously.
    """
    result = asyncio.run(
        preflight_check(base_url, transport=transport)
    )
    if not result.success:
        raise RuntimeError(result.display)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_test(
    model: TestFile,
    *,
    transport=None,
    control_stdin: bool = False,
    userlist_path: Optional[Path] = None,
) -> LoadTestResult:
    """
    Run the test described by *model*.

    Args:
        model: Parsed test model
        transport: Optional HTTP transport (for testing)
        control_stdin: Enable stdin control
        userlist_path: Resolved absolute path to the .ulf user list file
    """
    t = _get_test(model)
    base_url, ctx = _build_runtime_context(t)

    # Preflight: abort early if the server is not reachable.
    _run_preflight(base_url, transport=transport)

    num_users, ramp_up_seconds, duration_seconds = _resolve_load_params(t)

    # Build the appropriate user source (None when no auth block).
    user_source = _build_user_source(t, ctx, userlist_path)

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
            user_source=user_source,
        )
    )

    summary = metrics.summary()
    metric_threshold_checks = len(t.metrics.checks) if t.metrics is not None else 0
    metric_threshold_failures = (
        evaluate_metric_thresholds(t.metrics, summary)
        if not metrics.interrupted
        else []
    )

    return LoadTestResult(
        test_name=t.name.strip().strip('"'),
        users=num_users,
        ramp_up_seconds=ramp_up_seconds,
        target_duration_seconds=duration_seconds,
        summary=summary,
        auth_results=list(metrics.auth_results),
        interrupted=metrics.interrupted,
        stop_reason=metrics.stop_reason,
        metric_threshold_checks=metric_threshold_checks,
        metric_threshold_failures=metric_threshold_failures,
    )
