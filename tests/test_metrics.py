import time

from loadforge.runtime.metrics import MetricsCollector, _percentile


def test_empty_summary():
    mc = MetricsCollector()
    mc.start()
    mc.stop()

    s = mc.summary()

    assert s.total_requests == 0
    assert s.successful_requests == 0
    assert s.failed_requests == 0
    assert s.error_rate == 0.0
    assert s.latency_min_ms == 0.0
    assert s.latency_max_ms == 0.0
    assert s.latency_avg_ms == 0.0
    assert s.latency_p50_ms == 0.0
    assert s.latency_p95_ms == 0.0
    assert s.latency_p99_ms == 0.0
    assert s.requests_per_sec == 0.0
    assert s.scenarios == []


def test_single_record_summary():
    mc = MetricsCollector()
    mc.start()
    mc.record("s1", "GET", "/x", latency_ms=42.0, status_code=200, success=True)
    mc.stop()

    s = mc.summary()

    assert s.total_requests == 1
    assert s.successful_requests == 1
    assert s.failed_requests == 0
    assert s.error_rate == 0.0
    assert s.latency_min_ms == 42.0
    assert s.latency_max_ms == 42.0
    assert s.latency_avg_ms == 42.0
    assert s.latency_p50_ms == 42.0
    assert s.latency_p95_ms == 42.0
    assert s.latency_p99_ms == 42.0


def test_percentile_with_known_values():
    values = list(range(1, 101))  # [1, 2, ..., 100]
    sorted_values = sorted(values)

    assert _percentile(sorted_values, 50) == 50.5
    assert _percentile(sorted_values, 95) == 95.05
    assert _percentile(sorted_values, 99) == 99.01
    assert _percentile(sorted_values, 0) == 1.0
    assert _percentile(sorted_values, 100) == 100.0


def test_percentile_single_value():
    assert _percentile([7.0], 50) == 7.0
    assert _percentile([7.0], 99) == 7.0


def test_percentile_empty():
    assert _percentile([], 50) == 0.0


def test_scenario_breakdown():
    mc = MetricsCollector()
    mc.start()
    mc.record("search", "GET", "/a", latency_ms=10.0, status_code=200, success=True)
    mc.record("search", "GET", "/a", latency_ms=20.0, status_code=200, success=True)
    mc.record("details", "GET", "/b", latency_ms=30.0, status_code=200, success=True)
    mc.stop()

    s = mc.summary()

    assert s.total_requests == 3
    assert len(s.scenarios) == 2

    by_name = {sc.name: sc for sc in s.scenarios}
    assert "search" in by_name
    assert "details" in by_name

    assert by_name["search"].total_requests == 2
    assert by_name["search"].latency_min_ms == 10.0
    assert by_name["search"].latency_max_ms == 20.0

    assert by_name["details"].total_requests == 1
    assert by_name["details"].latency_avg_ms == 30.0


def test_error_rate():
    mc = MetricsCollector()
    mc.start()
    mc.record("s", "GET", "/ok", latency_ms=1.0, status_code=200, success=True)
    mc.record("s", "GET", "/ok", latency_ms=1.0, status_code=200, success=True)
    mc.record("s", "GET", "/ok", latency_ms=1.0, status_code=200, success=True)
    mc.record("s", "GET", "/err", latency_ms=1.0, status_code=500, success=False, error="boom")
    mc.stop()

    s = mc.summary()

    assert s.total_requests == 4
    assert s.successful_requests == 3
    assert s.failed_requests == 1
    assert s.error_rate == 25.0


def test_elapsed_seconds():
    mc = MetricsCollector()
    mc.start()
    time.sleep(0.05)
    mc.stop()

    assert mc.elapsed_seconds >= 0.04
    assert mc.elapsed_seconds < 0.2


def test_elapsed_seconds_before_start():
    mc = MetricsCollector()
    assert mc.elapsed_seconds == 0.0


def test_requests_per_sec():
    mc = MetricsCollector()
    mc.start()
    for _ in range(100):
        mc.record("s", "GET", "/x", latency_ms=1.0, status_code=200, success=True)
    time.sleep(0.05)
    mc.stop()

    s = mc.summary()

    assert s.requests_per_sec > 0
    assert s.total_requests == 100


def test_record_stores_error_message():
    mc = MetricsCollector()
    mc.start()
    mc.record("s", "GET", "/x", latency_ms=5.0, status_code=0, success=False, error="connection refused")
    mc.stop()

    assert len(mc.records) == 1
    assert mc.records[0].error == "connection refused"
    assert mc.records[0].success is False
    assert mc.records[0].status_code == 0