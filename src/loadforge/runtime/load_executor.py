from __future__ import annotations

import asyncio
import signal
import sys
import time
import re
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
from loadforge.runtime.control import (
    drain_virtual_users,
    start_stdin_control_listener,
    wait_for_stop_or_timeout,
)
from loadforge.runtime.interpolate import interpolate
from loadforge.runtime.metrics import MetricsCollector


# ---------------------------------------------------------------------------
# Live progress display
# ---------------------------------------------------------------------------

SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class _ProgressDisplay:
    """
    Prints a single status line that overwrites itself using \\r.
    Only active in continuous mode (duration > 0).
    """

    def __init__(
        self,
        metrics: MetricsCollector,
        num_users: int,
        duration_seconds: float,
        tasks: list[asyncio.Task],
    ) -> None:
        self._metrics = metrics
        self._num_users = num_users
        self._duration_seconds = duration_seconds
        self._tasks = tasks
        self._frame: int = 0
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="progress")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # Clear the status line.
        sys.stderr.write("\r\033[K")
        sys.stderr.flush()

    async def _loop(self) -> None:
        try:
            while True:
                self._render()
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            return

    def _render(self) -> None:
        spinner = SPINNER_FRAMES[self._frame % len(SPINNER_FRAMES)]
        self._frame += 1

        elapsed = self._metrics.elapsed_seconds
        total_reqs = len(self._metrics.records)
        rps = total_reqs / elapsed if elapsed > 0 else 0.0
        errors = sum(1 for r in self._metrics.records if not r.success)
        active = sum(1 for t in self._tasks if not t.done())

        line = (
            f"\r\033[K{spinner} "
            f"{elapsed:>5.1f}s / {self._duration_seconds:.0f}s"
            f" │ Users: {active}/{self._num_users}"
            f" │ Reqs: {total_reqs:,}"
            f" │ Req/s: {rps:.1f}"
            f" │ Errors: {errors:,}"
        )
        sys.stderr.write(line)
        sys.stderr.flush()


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
        case JsonCheckKind.isEmpty:
            value = _first_match_value(matches, step.path)
            if not isinstance(value, (list, dict, str)):
                raise AssertionError(
                    f"Expected '{step.path}' to be a list/dict/str for isEmpty, "
                    f"got: {type(value).__name__}"
                )
            if len(value) != 0:
                raise AssertionError(
                    f"Expected '{step.path}' to be empty, got {len(value)} elements"
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
        case JsonCheckKind.isNull:
            if not matches or matches[0].value is not None:
                actual = matches[0].value if matches else "<no match>"
                raise AssertionError(
                    f"Expected '{step.path}' to be null, got: {actual!r}"
                )
        case JsonCheckKind.notNull:
            if not matches or matches[0].value is None:
                raise AssertionError(
                    f"Expected '{step.path}' to be not null, got null or no match"
                )
        case JsonCheckKind.isObject:
            value = _first_match_value(matches, step.path)
            if not isinstance(value, dict):
                raise AssertionError(
                    f"Expected '{step.path}' to be an object, "
                    f"got: {type(value).__name__}"
                )
        case JsonCheckKind.isString:
            value = _first_match_value(matches, step.path)
            if not isinstance(value, str):
                raise AssertionError(
                    f"Expected '{step.path}' to be a string, "
                    f"got: {type(value).__name__}"
                )
        case JsonCheckKind.isNumber:
            value = _first_match_value(matches, step.path)
            # bool je subclass int u Pythonu
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise AssertionError(
                    f"Expected '{step.path}' to be a number, "
                    f"got: {type(value).__name__}"
                )
        case JsonCheckKind.isBool:
            value = _first_match_value(matches, step.path)
            if not isinstance(value, bool):
                raise AssertionError(
                    f"Expected '{step.path}' to be a boolean, "
                    f"got: {type(value).__name__}"
                )
        case JsonCheckKind.contains:
            expected = resolve_value_or_ref(step.check.value, ctx)
            value = _first_match_value(matches, step.path)
            if isinstance(value, list):
                if expected not in [str(v) for v in value]:
                    raise AssertionError(
                        f"Expected '{step.path}' to contain {expected!r}, "
                        f"got: {value!r}"
                    )
            elif isinstance(value, str):
                if expected not in value:
                    raise AssertionError(
                        f"Expected '{step.path}' to contain {expected!r}, "
                        f"got: {value!r}"
                    )
            else:
                raise AssertionError(
                    f"'contains' requires list or string at '{step.path}', "
                    f"got: {type(value).__name__}"
                )
        case JsonCheckKind.matches:
            pattern = resolve_value_or_ref(step.check.value, ctx)
            value = _first_match_value(matches, step.path)
            if not isinstance(value, str):
                raise AssertionError(
                    f"'matches' requires string at '{step.path}', "
                    f"got: {type(value).__name__}"
                )
            if not re.search(pattern, value):
                raise AssertionError(
                    f"Expected '{step.path}' to match pattern {pattern!r}, "
                    f"got: {value!r}"
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
            except AssertionError as exc:
                # Mark the *most recent* request record as failed.
                _mark_last_record_failed(metrics, str(exc))
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
            if stop_event.is_set():
                return
            await run_scenario_async(client, scenario, ctx, metrics)
        return

    # Continuous loop until told to stop.
    while not stop_event.is_set():
        for scenario in scenarios:
            if stop_event.is_set():
                return
            await run_scenario_async(client, scenario, ctx, metrics)
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
    control_stdin: bool = False,
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
    stop_reason: Optional[str] = None

    def _request_stop(reason: str) -> None:
        nonlocal stop_reason
        if stop_reason is None:
            stop_reason = reason
        metrics.mark_interrupted(reason=stop_reason)
        stop_event.set()

    client_kwargs: dict = {"base_url": base_url}
    if transport is not None:
        client_kwargs["transport"] = transport

    async with httpx.AsyncClient(**client_kwargs) as client:
        if "authToken" in ctx:
            client.headers["Authorization"] = f"Bearer {ctx['authToken']}"

        metrics.start()
        progress: Optional[_ProgressDisplay] = None
        tasks: list[asyncio.Task] = []

        loop = asyncio.get_running_loop()
        handled_signals: list[int] = []
        if hasattr(loop, "add_signal_handler"):
            try:
                loop.add_signal_handler(signal.SIGTERM, _request_stop, "SIGTERM")
                handled_signals.append(signal.SIGTERM)
            except (NotImplementedError, RuntimeError, ValueError):
                pass

        start_stdin_control_listener(
            loop=loop,
            enabled=control_stdin,
            request_stop=_request_stop,
        )

        try:
            # Spawn virtual users (with optional ramp-up delay).
            for i in range(num_users):
                if stop_event.is_set():
                    break

                task = asyncio.create_task(
                    _virtual_user(
                        i, client, test.scenarios, ctx, metrics, stop_event,
                        single_pass=single_pass,
                    ),
                    name=f"vu-{i}",
                )
                tasks.append(task)

                # Start progress display after the first user is spawned.
                if not single_pass and i == 0:
                    progress = _ProgressDisplay(
                        metrics, num_users, duration_seconds, tasks,
                    )
                    progress.start()

                if delay_between_users > 0 and i < num_users - 1:
                    stop_requested = await wait_for_stop_or_timeout(
                        stop_event, delay_between_users
                    )
                    if stop_requested:
                        break

            if single_pass:
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
            else:
                elapsed_so_far = metrics.elapsed_seconds
                remaining = duration_seconds - elapsed_so_far
                if remaining > 0:
                    timed_out = not await wait_for_stop_or_timeout(
                        stop_event, remaining
                    )
                    if timed_out:
                        stop_event.set()
                else:
                    stop_event.set()

                await drain_virtual_users(tasks, stop_event, timeout=30.0)
        except asyncio.CancelledError:
            # Ctrl+C (SIGINT) reaches us as cancellation via asyncio.run().
            _request_stop("SIGINT")
            await drain_virtual_users(tasks, stop_event, timeout=30.0)
        finally:
            for sig in handled_signals:
                loop.remove_signal_handler(sig)
            if progress is not None:
                await progress.stop()
            metrics.stop()

    return metrics
