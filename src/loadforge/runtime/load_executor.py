from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

import httpx
from jsonpath_ng.ext import parse as jsonpath_parse

from loadforge.model import (
    ExpectJson,
    ExpectStatus,
    JsonCheckKind,
    Request,
    Scenario,
    Test,
)
from loadforge.runtime.context import resolve_value_or_ref
from loadforge.runtime.interpolate import interpolate
from loadforge.runtime.metrics import MetricsCollector


# ---------------------------------------------------------------------------
# Async step runners
# ---------------------------------------------------------------------------


async def _run_request_step_async(
    client: httpx.AsyncClient,
    step: Request,
    ctx: dict[str, str],
) -> httpx.Response:
    path = interpolate(step.path, ctx)
    return await client.request(step.method, path)


def _run_expect_status_step(
    last_response: httpx.Response, step: ExpectStatus
) -> None:
    if last_response.status_code != step.code:
        raise AssertionError(
            f"Expected status {step.code}, got {last_response.status_code}"
        )


def _jsonpath_find(data: Any, json_path_literal: str):
    expr = jsonpath_parse(json_path_literal.strip().strip('"'))
    return expr.find(data)


def _first_match_value(matches, json_path_literal: str) -> Any:
    if not matches:
        raise AssertionError(
            f"JSONPath did not match anything: {json_path_literal.strip().strip('\"')}"
        )
    return matches[0].value


def _run_expect_json_step(
    last_response: httpx.Response, step: ExpectJson, ctx: dict[str, str]
) -> None:
    data = last_response.json()
    matches = _jsonpath_find(data, step.path)
    kind = step.check.kind

    match kind:
        case JsonCheckKind.isArray:
            value = _first_match_value(matches, step.path)
            if not isinstance(value, list):
                raise AssertionError(
                    f"Expected JSON path to be array, got: {type(value)}"
                )
        case JsonCheckKind.notEmpty:
            value = _first_match_value(matches, step.path)
            if not value:
                raise AssertionError(
                    f"Expected JSON path to be not empty, got: {value!r}"
                )
        case JsonCheckKind.equals:
            expected = resolve_value_or_ref(step.check.value, ctx)
            value = _first_match_value(matches, step.path)
            if value != expected:
                raise AssertionError(
                    f"JSON value mismatch, expected: {expected!r}, got: {value!r}"
                )
        case JsonCheckKind.hasSize:
            value = _first_match_value(matches, step.path)
            if not isinstance(value, (list, dict, str)):
                raise AssertionError(
                    f"Expected JSON path to be sized (list/dict/str), got: {type(value)}"
                )
            actual = len(value)
            if actual != step.check.size:
                raise AssertionError(
                    f"JSON size mismatch, expected: {step.check.size}, got: {actual}"
                )
        case _:
            raise RuntimeError(f"Unsupported JsonCheckKind: {kind!r}")


# ---------------------------------------------------------------------------
# Async scenario runner — records metrics for every request
# ---------------------------------------------------------------------------


async def run_scenario_async(
    client: httpx.AsyncClient,
    scenario: Scenario,
    ctx: dict[str, str],
    metrics: MetricsCollector,
) -> None:
    """
    Execute one full pass of a scenario, recording each request into *metrics*.
    Expect steps also run — assertion failures count towards the error rate.
    """
    scenario_name = scenario.name.strip().strip('"')
    last_response: Optional[httpx.Response] = None

    for step in scenario.steps:
        if isinstance(step, Request):
            path = interpolate(step.path, ctx)
            start = time.perf_counter()
            try:
                last_response = await client.request(step.method, path)
                latency_ms = (time.perf_counter() - start) * 1000.0
                metrics.record(
                    scenario=scenario_name,
                    method=step.method,
                    path=path,
                    latency_ms=latency_ms,
                    status_code=last_response.status_code,
                    success=True,
                )
            except Exception as exc:
                latency_ms = (time.perf_counter() - start) * 1000.0
                metrics.record(
                    scenario=scenario_name,
                    method=step.method,
                    path=path,
                    latency_ms=latency_ms,
                    status_code=0,
                    success=False,
                    error=str(exc),
                )
                # Skip in this loop
                return

        elif isinstance(step, ExpectStatus):
            if last_response is None:
                raise RuntimeError("expect status used before any request")
            try:
                _run_expect_status_step(last_response, step)
            except AssertionError:
                # Mark the *most recent* request record as failed.
                _mark_last_record_failed(metrics, str(step.code))
                return

        elif isinstance(step, ExpectJson):
            if last_response is None:
                raise RuntimeError("expect json used before any request")
            try:
                _run_expect_json_step(last_response, step, ctx)
            except AssertionError as exc:
                _mark_last_record_failed(metrics, str(exc))
                return

        else:
            raise RuntimeError(f"Unsupported step type: {type(step).__name__}")


def _mark_last_record_failed(metrics: MetricsCollector, error: str) -> None:
    """
    Mark the last recorded request as failed because a
    subsequent expect step did not pass.
    """
    if metrics.records:
        last = metrics.records[-1]
        last.success = False
        last.error = error


# ---------------------------------------------------------------------------
# Virtual user coroutine
# ---------------------------------------------------------------------------


async def _virtual_user(
    user_id: int,
    client: httpx.AsyncClient,
    scenarios: list[Scenario],
    ctx: dict[str, str],
    metrics: MetricsCollector,
    stop_event: asyncio.Event,
    single_pass: bool = False,
) -> None:
    """
    A single virtual user that executes scenarios.
    """
    if single_pass:
        for scenario in scenarios:
            try:
                await run_scenario_async(client, scenario, ctx, metrics)
            except Exception:
                pass
        return

    # Continuous loop until told to stop.
    while not stop_event.is_set():
        for scenario in scenarios:
            if stop_event.is_set():
                return
            try:
                await run_scenario_async(client, scenario, ctx, metrics)
            except Exception:
                pass
            # Yield control briefly so other users get a chance to run and
            # the stop-event can be checked promptly.
            await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# Load test orchestrator
# ---------------------------------------------------------------------------


async def run_load_test_async(
    test: Test,
    base_url: str,
    ctx: dict[str, str],
    num_users: int = 1,
    ramp_up_seconds: float = 0.0,
    duration_seconds: float = 0.0,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> MetricsCollector:
    """
    Run the load test for the given *test*.
    Parameters are supplied explicitly by the caller.
    Single-pass mode is triggered by setting duration_seconds <= 0 (non-existing load block in grammar)
    """
    if num_users <= 0:
        raise RuntimeError("load.users must be > 0")

    single_pass = duration_seconds <= 0

    # Ramp-up cannot exceed total duration
    if not single_pass and ramp_up_seconds > duration_seconds:
        ramp_up_seconds = duration_seconds

    delay_between_users = (
        ramp_up_seconds / num_users if ramp_up_seconds > 0 and not single_pass else 0.0
    )

    metrics = MetricsCollector()
    stop_event = asyncio.Event()

    client_kwargs: dict = {"base_url": base_url}
    if transport is not None:
        client_kwargs["transport"] = transport

    async with httpx.AsyncClient(**client_kwargs) as client:
        # Copy auth header if present in ctx.
        if "authToken" in ctx:
            client.headers["Authorization"] = f"Bearer {ctx['authToken']}"

        metrics.start()
        tasks: list[asyncio.Task] = []

        # Spawn virtual users (with optional ramp-up delay).
        for i in range(num_users):
            task = asyncio.create_task(
                _virtual_user(
                    i, client, test.scenarios, ctx, metrics, stop_event,
                    single_pass=single_pass,
                ),
                name=f"vu-{i}",
            )
            tasks.append(task)
            if delay_between_users > 0 and i < num_users - 1:
                await asyncio.sleep(delay_between_users)

        if single_pass:
            await asyncio.gather(*tasks, return_exceptions=True)
        else:
            elapsed_so_far = metrics.elapsed_seconds
            remaining = duration_seconds - elapsed_so_far
            if remaining > 0:
                await asyncio.sleep(remaining)

            stop_event.set()

            # Wait for in-flight iterations to finish (with a safety timeout).
            done, pending = await asyncio.wait(tasks, timeout=30.0)
            for t in pending:
                t.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        metrics.stop()

    return metrics
