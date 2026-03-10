from __future__ import annotations

import asyncio
import signal
import sys
import time
from typing import Optional

import httpx

from loadforge.model import (
    ExpectJson,
    ExpectStatus,
    Request,
    Scenario,
    Test,
    AuthLogin,
)
from loadforge.runtime.auth import AuthResult, authenticate
from loadforge.runtime.control import (
    drain_virtual_users,
    start_stdin_control_listener,
    wait_for_stop_or_timeout,
)
from loadforge.runtime.interpolate import interpolate
from loadforge.runtime.checks import run_expect_json_step, run_expect_status_step
from loadforge.runtime.metrics import MetricsCollector
from loadforge.runtime.user import User, UserSource


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
# Async scenario runner — records metrics for every request
# ---------------------------------------------------------------------------
async def run_scenario_async(
    client: httpx.AsyncClient,
    scenario: Scenario,
    ctx: dict[str, str],
    metrics: MetricsCollector,
    headers: Optional[dict[str, str]] = None,
) -> None:
    """
    Execute one full pass of a scenario, recording each request into *metrics*.
    Expect steps also run — assertion failures count towards the error rate.
    """
    scenario_name = scenario.name.strip().strip('"')
    last_response: Optional[httpx.Response] = None

    for step in scenario.steps:
        try:
            if isinstance(step, Request):
                start = time.perf_counter()
                try:
                    path = interpolate(step.path, ctx)
                    method = step.method.value
                    last_response = await client.request(method, path, headers=headers)
                    latency_ms = (time.perf_counter() - start) * 1000.0
                    metrics.record(
                        scenario=scenario_name,
                        method=method,
                        path=path,
                        latency_ms=latency_ms,
                        status_code=last_response.status_code,
                        success=True,
                    )
                except Exception as exc:
                    latency_ms = (time.perf_counter() - start) * 1000.0
                    metrics.record(
                        scenario=scenario_name,
                        method=step.method.value,
                        path=step.path.strip().strip('"'),
                        latency_ms=latency_ms,
                        status_code=0,
                        success=False,
                        error=str(exc),
                    )
                    return

            elif isinstance(step, ExpectStatus):
                if last_response is None:
                    raise RuntimeError("expect status used before any request")
                try:
                    run_expect_status_step(last_response, step)
                except AssertionError as exc:
                    _mark_last_record_failed(metrics, str(exc))
                    return

            elif isinstance(step, ExpectJson):
                if last_response is None:
                    raise RuntimeError("expect json used before any request")
                try:
                    run_expect_json_step(last_response, step, ctx)
                except AssertionError as exc:
                    _mark_last_record_failed(metrics, str(exc))
                    return

            else:
                raise RuntimeError(f"Unsupported step type: {type(step).__name__}")

        except Exception as exc:
            # Safety net: catch any error that escapes the inner handlers
            # (e.g. RuntimeError from interpolation, expect-before-request,
            # resolve_value_or_ref inside json checks, unsupported step type).
            # Record it as a failure so it surfaces in the report instead of
            # silently killing the virtual user.
            if metrics.records:
                _mark_last_record_failed(metrics, str(exc))
            else:
                metrics.record(
                    scenario=scenario_name,
                    method=getattr(step, "method", "").value if hasattr(getattr(step, "method", None), "value") else "",
                    path=getattr(step, "path", "").strip().strip('"') if getattr(step, "path", "") else "",
                    latency_ms=0.0,
                    status_code=0,
                    success=False,
                    error=str(exc),
                )
            return


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
    auth_config: Optional[AuthLogin] = None,
    user: Optional[User] = None,
) -> None:
    """
    A single virtual user that executes scenarios.
    """
    user_headers: dict[str, str] = {}

    if auth_config and user:
        result = await authenticate(client, auth_config, ctx, user)
        metrics.record_auth(result)
        if not result.success:
            return
        user_headers = result.headers

    # EXECUTE scenarios with per-user headers
    if single_pass:
        for scenario in scenarios:
            if stop_event.is_set():
                return
            await run_scenario_async(client, scenario, ctx, metrics, user_headers)
        return

    # Continuous loop until told to stop.
    while not stop_event.is_set():
        for scenario in scenarios:
            if stop_event.is_set():
                return
            await run_scenario_async(client, scenario, ctx, metrics, user_headers)
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
    user_source: Optional[UserSource] = None,
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

    auth_config: Optional[AuthLogin] = test.auth

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
        # Shared-token auth: authenticate once before spawning VUs.
        if auth_config and user_source and not user_source.per_user_auth:
            shared_user = user_source.get_user(0)
            result = await authenticate(client, auth_config, ctx, shared_user)
            metrics.record_auth(result)
            if not result.success:
                metrics.mark_interrupted(reason=f"auth failed: {result.error}")
                return metrics
            client.headers["Authorization"] = f"Bearer {result.token}"
            ctx["authToken"] = result.token

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

                # Assign user for this VU (per-user auth sources get
                # their own User; shared auth has already been handled).
                vu_user: Optional[User] = None
                vu_auth: Optional[AuthLogin] = None
                if user_source and user_source.per_user_auth and auth_config:
                    vu_user = user_source.get_user(i)
                    vu_auth = auth_config

                task = asyncio.create_task(
                    _virtual_user(
                        i, client, test.scenarios, ctx, metrics, stop_event,
                        single_pass=single_pass,
                        auth_config=vu_auth,
                        user=vu_user,
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
