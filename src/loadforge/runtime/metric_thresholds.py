from __future__ import annotations

from typing import Optional

from loadforge.model import MetricsBlock
from loadforge.runtime.metrics import MetricsSummary

_LATENCY_METRICS = {"p50", "p95", "p99", "avg", "min", "max"}
_LATENCY_UNIT_TO_MS = {
    "us": 0.001,
    "ms": 1.0,
    "s": 1000.0,
}


def _actual_metric_value(summary: MetricsSummary, metric: str) -> float:
    metric_map: dict[str, float] = {
        "p50": summary.latency_p50_ms,
        "p95": summary.latency_p95_ms,
        "p99": summary.latency_p99_ms,
        "avg": summary.latency_avg_ms,
        "min": summary.latency_min_ms,
        "max": summary.latency_max_ms,
        "errorRate": summary.error_rate,
    }
    if metric not in metric_map:
        raise RuntimeError(f"Unsupported metric check: {metric}")
    return metric_map[metric]


def _compare(actual: float, op: str, threshold: float) -> bool:
    if op == "<":
        return actual < threshold
    if op == "<=":
        return actual <= threshold
    if op == ">":
        return actual > threshold
    if op == ">=":
        return actual >= threshold
    raise RuntimeError(f"Unsupported metric operator: {op}")


def _to_ms(value: float, unit: str) -> float:
    if unit not in _LATENCY_UNIT_TO_MS:
        raise RuntimeError(f"Unsupported latency unit: {unit}")
    return value * _LATENCY_UNIT_TO_MS[unit]


def _from_ms(value_ms: float, unit: str) -> float:
    if unit not in _LATENCY_UNIT_TO_MS:
        raise RuntimeError(f"Unsupported latency unit: {unit}")
    return value_ms / _LATENCY_UNIT_TO_MS[unit]


def evaluate_metric_thresholds(
    metrics: Optional[MetricsBlock],
    summary: MetricsSummary,
) -> list[str]:
    """
    Evaluate all configured metric expectations against runtime summary.
    Returns a list of failure messages.
    """
    if metrics is None:
        return []

    failures: list[str] = []
    for check in metrics.checks:
        try:
            threshold = float(check.value)
        except ValueError as exc:
            raise RuntimeError(
                f"Invalid numeric threshold for metric '{check.metric}': {check.value!r}"
            ) from exc

        actual = _actual_metric_value(summary, check.metric)

        # Latency values in summary are stored in ms, while DSL can use
        # us/ms/s thresholds.
        if check.metric in _LATENCY_METRICS:
            threshold_cmp = _to_ms(threshold, check.unit)
            actual_cmp = actual
            actual_display = _from_ms(actual, check.unit)
        elif check.metric == "errorRate":
            if check.unit != "%":
                raise RuntimeError("errorRate metric expects '%' unit.")
            threshold_cmp = threshold
            actual_cmp = actual
            actual_display = actual
        else:
            raise RuntimeError(f"Unsupported metric check: {check.metric}")

        if not _compare(actual_cmp, check.op, threshold_cmp):
            failures.append(
                f"{check.metric} {check.op} {threshold:g}{check.unit} failed "
                f"(actual: {actual_display:.2f}{check.unit})"
            )

    return failures
