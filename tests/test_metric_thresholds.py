import httpx

from loadforge.parser.parse import parse_str
from loadforge.runtime.runner import run_test


DSL_METRICS_PASS = r'''
test "t" {
  target "http://api.test"

  scenario "s" {
    request GET "/x"
    expect status 200
  }

  load {
    users 1
    rampUp 0s
    duration 1s
  }

  metrics {
    p95 < 1000ms
    errorRate < 1%
  }
}
'''


DSL_METRICS_FAIL = r'''
test "t" {
  target "http://api.test"

  scenario "s" {
    request GET "/x"
    expect status 200
  }

  load {
    users 1
    rampUp 0s
    duration 1s
  }

  metrics {
    p95 < 0ms
    errorRate < 1%
  }
}
'''


DSL_METRICS_SECONDS_PASS = r'''
test "t" {
  target "http://api.test"

  scenario "s" {
    request GET "/x"
    expect status 200
  }

  load {
    users 1
    rampUp 0s
    duration 1s
  }

  metrics {
    p95 < 1s
  }
}
'''


DSL_METRICS_MICROSECONDS_FAIL = r'''
test "t" {
  target "http://api.test"

  scenario "s" {
    request GET "/x"
    expect status 200
  }

  load {
    users 1
    rampUp 0s
    duration 1s
  }

  metrics {
    p95 < 1us
  }
}
'''


def _ok_handler(_: httpx.Request) -> httpx.Response:
    return httpx.Response(200)


def test_metrics_block_is_parsed():
    model = parse_str(DSL_METRICS_PASS)
    assert model.test is not None
    assert model.test.metrics is not None
    assert len(model.test.metrics.checks) == 2

    first = model.test.metrics.checks[0]
    second = model.test.metrics.checks[1]
    assert first.metric == "p95"
    assert first.op == "<"
    assert first.value == "1000"
    assert first.unit == "ms"
    assert second.metric == "errorRate"
    assert second.unit == "%"


def test_metrics_thresholds_pass():
    model = parse_str(DSL_METRICS_PASS)
    result = run_test(model, transport=httpx.MockTransport(_ok_handler))

    assert result.failed == 0
    assert result.success is True
    assert result.metric_threshold_checks == 2
    assert result.metric_threshold_failures == []

    output = str(result)
    assert "Metric thresholds:" in output
    assert "Result: PASS" in output


def test_metrics_thresholds_fail_even_when_requests_pass():
    model = parse_str(DSL_METRICS_FAIL)
    result = run_test(model, transport=httpx.MockTransport(_ok_handler))

    assert result.failed == 0
    assert result.success is False
    assert result.metric_threshold_checks == 2
    assert len(result.metric_threshold_failures) == 1
    assert "p95 < 0ms failed" in result.metric_threshold_failures[0]

    output = str(result)
    assert "Metric thresholds:" in output
    assert "Result: FAIL" in output


def test_metrics_thresholds_support_seconds_unit():
    model = parse_str(DSL_METRICS_SECONDS_PASS)
    result = run_test(model, transport=httpx.MockTransport(_ok_handler))

    assert result.success is True
    assert result.metric_threshold_failures == []


def test_metrics_thresholds_support_microseconds_unit_failure():
    model = parse_str(DSL_METRICS_MICROSECONDS_FAIL)
    result = run_test(model, transport=httpx.MockTransport(_ok_handler))

    assert result.success is False
    assert len(result.metric_threshold_failures) == 1
    assert "us" in result.metric_threshold_failures[0]
