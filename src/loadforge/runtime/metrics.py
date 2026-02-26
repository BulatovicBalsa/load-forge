from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RequestRecord:
    """A single recorded HTTP request during a load test."""

    scenario: str
    method: str
    path: str
    timestamp: float
    latency_ms: float
    status_code: int
    success: bool
    error: Optional[str] = None


@dataclass
class ScenarioSummary:
    """Aggregate metrics for a single scenario."""

    name: str
    total_requests: int
    successful_requests: int
    failed_requests: int
    error_rate: float
    latency_min_ms: float
    latency_max_ms: float
    latency_avg_ms: float
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    requests_per_sec: float


@dataclass
class MetricsSummary:
    """Aggregate metrics for the entire load test."""

    total_requests: int
    successful_requests: int
    failed_requests: int
    error_rate: float
    latency_min_ms: float
    latency_max_ms: float
    latency_avg_ms: float
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    requests_per_sec: float
    duration_seconds: float
    scenarios: list[ScenarioSummary] = field(default_factory=list)


def _percentile(sorted_values: list[float], p: float) -> float:
    """
    Compute the p-th percentile from an already-sorted list.
    Uses linear interpolation
    """
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]

    k = (p / 100.0) * (len(sorted_values) - 1)
    floor = int(k)
    ceil = floor + 1
    if ceil >= len(sorted_values):
        return sorted_values[-1]
    frac = k - floor
    return sorted_values[floor] + frac * (sorted_values[ceil] - sorted_values[floor])


def _compute_latency_stats(
    latencies: list[float],
) -> tuple[float, float, float, float, float, float]:
    """
    Returns (min, max, avg, p50, p95, p99) from a list of latency values.
    """
    if not latencies:
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0

    sorted_lat = sorted(latencies)
    return (
        sorted_lat[0],
        sorted_lat[-1],
        statistics.mean(sorted_lat),
        _percentile(sorted_lat, 50),
        _percentile(sorted_lat, 95),
        _percentile(sorted_lat, 99),
    )


class MetricsCollector:
    """
    Collects per-request metrics during a load test.

    Safe for use in a single-threaded asyncio context (no locking needed).
    Records are appended during the test and summarized once at the end.
    """

    def __init__(self) -> None:
        self._records: list[RequestRecord] = []
        self._start_time: float = 0.0
        self._end_time: float = 0.0

    @property
    def records(self) -> list[RequestRecord]:
        return self._records

    def start(self) -> None:
        """Mark the beginning of the load test."""
        self._start_time = time.monotonic()

    def stop(self) -> None:
        """Mark the end of the load test."""
        self._end_time = time.monotonic()

    @property
    def elapsed_seconds(self) -> float:
        if self._start_time == 0.0:
            return 0.0
        end = self._end_time if self._end_time > 0.0 else time.monotonic()
        return end - self._start_time

    def record(
        self,
        scenario: str,
        method: str,
        path: str,
        latency_ms: float,
        status_code: int,
        success: bool,
        error: Optional[str] = None,
    ) -> None:
        self._records.append(
            RequestRecord(
                scenario=scenario,
                method=method,
                path=path,
                timestamp=time.monotonic(),
                latency_ms=latency_ms,
                status_code=status_code,
                success=success,
                error=error,
            )
        )

    def _build_scenario_summary(
        self, name: str, records: list[RequestRecord], duration: float
    ) -> ScenarioSummary:
        total = len(records)
        successful = sum(1 for r in records if r.success)
        failed = total - successful
        latencies = [r.latency_ms for r in records]
        lat_min, lat_max, lat_avg, p50, p95, p99 = _compute_latency_stats(latencies)
        rps = total / duration if duration > 0 else 0.0

        return ScenarioSummary(
            name=name,
            total_requests=total,
            successful_requests=successful,
            failed_requests=failed,
            error_rate=(failed / total * 100.0) if total > 0 else 0.0,
            latency_min_ms=lat_min,
            latency_max_ms=lat_max,
            latency_avg_ms=lat_avg,
            latency_p50_ms=p50,
            latency_p95_ms=p95,
            latency_p99_ms=p99,
            requests_per_sec=rps,
        )

    def summary(self) -> MetricsSummary:
        """
        Compute aggregate metrics from all collected records.
        Should be called after stop().
        """
        duration = self.elapsed_seconds
        records = self._records
        total = len(records)
        successful = sum(1 for r in records if r.success)
        failed = total - successful

        latencies = [r.latency_ms for r in records]
        lat_min, lat_max, lat_avg, p50, p95, p99 = _compute_latency_stats(latencies)
        rps = total / duration if duration > 0 else 0.0

        # Per-scenario breakdown
        scenarios_map: dict[str, list[RequestRecord]] = {}
        for r in records:
            scenarios_map.setdefault(r.scenario, []).append(r)

        scenario_summaries = [
            self._build_scenario_summary(name, recs, duration)
            for name, recs in scenarios_map.items()
        ]

        return MetricsSummary(
            total_requests=total,
            successful_requests=successful,
            failed_requests=failed,
            error_rate=(failed / total * 100.0) if total > 0 else 0.0,
            latency_min_ms=lat_min,
            latency_max_ms=lat_max,
            latency_avg_ms=lat_avg,
            latency_p50_ms=p50,
            latency_p95_ms=p95,
            latency_p99_ms=p99,
            requests_per_sec=rps,
            duration_seconds=duration,
            scenarios=scenario_summaries,
        )
