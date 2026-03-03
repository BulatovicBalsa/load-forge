import asyncio
import queue
import sys

import httpx

from loadforge.parser.parse import parse_str
from loadforge.runtime.load_executor import run_load_test_async
from loadforge.runtime.load_result import LoadTestResult
from loadforge.runtime.metrics import MetricsSummary


class _QueueStdin:
    def __init__(self) -> None:
        self._q: queue.Queue[str] = queue.Queue()
        self.closed = False

    def isatty(self) -> bool:
        return False

    def readline(self) -> str:
        return self._q.get()

    def push_line(self, line: str) -> None:
        self._q.put(line)


DSL_LONG_LOAD = r'''
test "interrupt-demo" {
  target "http://api.test"

  scenario "loop" {
    request GET "/x"
    expect status 200
  }

  load {
    users 2
    rampUp 0s
    duration 10s
  }
}
'''


def test_cancelled_load_returns_partial_metrics():
    model = parse_str(DSL_LONG_LOAD)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)

    async def _run_and_cancel():
        task = asyncio.create_task(
            run_load_test_async(
                test=model.test,
                base_url="http://api.test",
                ctx={},
                num_users=2,
                ramp_up_seconds=0.0,
                duration_seconds=10.0,
                transport=transport,
            )
        )
        await asyncio.sleep(0.2)
        task.cancel()
        return await task

    metrics = asyncio.run(_run_and_cancel())
    summary = metrics.summary()

    assert metrics.interrupted is True
    assert metrics.stop_reason == "SIGINT"
    assert summary.total_requests > 0


def test_load_result_marks_stopped_run():
    summary = MetricsSummary(
        total_requests=5,
        successful_requests=5,
        failed_requests=0,
        error_rate=0.0,
        latency_min_ms=1.0,
        latency_max_ms=5.0,
        latency_avg_ms=3.0,
        latency_p50_ms=3.0,
        latency_p95_ms=5.0,
        latency_p99_ms=5.0,
        requests_per_sec=10.0,
        duration_seconds=0.5,
    )
    result = LoadTestResult(
        test_name="t",
        users=2,
        ramp_up_seconds=0.0,
        target_duration_seconds=10.0,
        summary=summary,
        interrupted=True,
        stop_reason="SIGTERM",
    )

    rendered = str(result)
    assert result.success is False
    assert "Stopped early" in rendered
    assert "Result: STOPPED" in rendered


def test_stdin_stop_command_interrupts_load(monkeypatch):
    model = parse_str(DSL_LONG_LOAD)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    fake_stdin = _QueueStdin()
    monkeypatch.setattr(sys, "stdin", fake_stdin)

    async def _run_and_stop():
        task = asyncio.create_task(
            run_load_test_async(
                test=model.test,
                base_url="http://api.test",
                ctx={},
                num_users=2,
                ramp_up_seconds=0.0,
                duration_seconds=10.0,
                transport=transport,
                control_stdin=True,
            )
        )
        await asyncio.sleep(0.2)
        fake_stdin.push_line("STOP\n")
        return await task

    metrics = asyncio.run(_run_and_stop())
    summary = metrics.summary()

    assert metrics.interrupted is True
    assert metrics.stop_reason == "STDIN"
    assert summary.total_requests > 0
