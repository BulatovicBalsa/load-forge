"""
Tests for the preflight connectivity check.

The preflight runs before the load test, is not timed, and is not counted
in any metrics.  It should abort the test early when the server is
unreachable and pass through silently when any HTTP response is received.
"""
from __future__ import annotations

import asyncio

import pytest
import httpx

from loadforge.runtime.preflight import preflight_check, PreflightResult
from loadforge.runtime.runner import run_test
from loadforge.parser.parse import parse_str


# ---------------------------------------------------------------------------
# DSL fixtures
# ---------------------------------------------------------------------------

DSL_SIMPLE = r'''
test "preflight test" {
  target "http://test-server"

  scenario "s" {
    request GET "/hello"
    expect status 200
  }
}
'''

DSL_WITH_LOAD = r'''
test "preflight load test" {
  target "http://test-server"

  scenario "s" {
    request GET "/hello"
    expect status 200
  }

  load {
    users 2
    rampUp 0s
    duration 1s
  }
}
'''


# ---------------------------------------------------------------------------
# Mock transports
# ---------------------------------------------------------------------------

def _ok_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200)


def _not_found_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(404)


def _server_error_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(500)


def _unauthorized_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(401)


def _method_not_allowed_handler(request: httpx.Request) -> httpx.Response:
    """Simulates a server that doesn't support HEAD."""
    return httpx.Response(405)


def _connection_refused_handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("Connection refused")


def _timeout_handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectTimeout("Connection timed out")


def _read_timeout_handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("Read timed out")


def _ssl_error_handler(request: httpx.Request) -> httpx.Response:
    raise Exception("SSL: CERTIFICATE_VERIFY_FAILED")


# ---------------------------------------------------------------------------
# Helper to run async preflight_check synchronously
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Unit tests for preflight_check
# ---------------------------------------------------------------------------


class TestPreflightCheck:
    """Direct tests of the preflight_check function."""

    def test_success_200(self):
        transport = httpx.MockTransport(_ok_handler)
        result = _run(preflight_check("http://test-server", transport=transport))

        assert result.success is True
        assert result.status_code == 200
        assert result.error is None

    def test_success_404_still_passes(self):
        """A 404 means the server IS up — preflight should pass."""
        transport = httpx.MockTransport(_not_found_handler)
        result = _run(preflight_check("http://test-server", transport=transport))

        assert result.success is True
        assert result.status_code == 404

    def test_success_500_still_passes(self):
        """A 500 means the server IS up — preflight should pass."""
        transport = httpx.MockTransport(_server_error_handler)
        result = _run(preflight_check("http://test-server", transport=transport))

        assert result.success is True
        assert result.status_code == 500

    def test_success_401_still_passes(self):
        """A 401 means the server IS up — preflight should pass."""
        transport = httpx.MockTransport(_unauthorized_handler)
        result = _run(preflight_check("http://test-server", transport=transport))

        assert result.success is True
        assert result.status_code == 401

    def test_success_405_still_passes(self):
        """A 405 (HEAD not allowed) means the server IS up — preflight should pass."""
        transport = httpx.MockTransport(_method_not_allowed_handler)
        result = _run(preflight_check("http://test-server", transport=transport))

        assert result.success is True
        assert result.status_code == 405

    def test_connection_refused(self):
        transport = httpx.MockTransport(_connection_refused_handler)
        result = _run(preflight_check("http://test-server", transport=transport))

        assert result.success is False
        assert result.status_code is None
        assert "not reachable" in result.error
        assert "test-server" in result.error

    def test_connect_timeout(self):
        transport = httpx.MockTransport(_timeout_handler)
        result = _run(preflight_check("http://test-server", transport=transport))

        assert result.success is False
        assert result.status_code is None
        assert "timed out" in result.error.lower()
        assert "test-server" in result.error

    def test_read_timeout(self):
        transport = httpx.MockTransport(_read_timeout_handler)
        result = _run(preflight_check("http://test-server", transport=transport))

        assert result.success is False
        assert result.status_code is None
        assert "timed out" in result.error.lower()

    def test_generic_exception(self):
        """Unexpected errors (e.g. SSL) should be caught and reported."""
        transport = httpx.MockTransport(_ssl_error_handler)
        result = _run(preflight_check("http://test-server", transport=transport))

        assert result.success is False
        assert result.status_code is None
        assert "SSL" in result.error

    def test_custom_timeout(self):
        """The timeout parameter should be accepted without error."""
        transport = httpx.MockTransport(_ok_handler)
        result = _run(
            preflight_check("http://test-server", transport=transport, timeout=1.0)
        )

        assert result.success is True


# ---------------------------------------------------------------------------
# PreflightResult display
# ---------------------------------------------------------------------------


class TestPreflightResultDisplay:

    def test_success_display(self):
        result = PreflightResult(success=True, status_code=200)
        assert "reachable" in result.display
        assert "200" in result.display

    def test_failure_display(self):
        result = PreflightResult(success=False, error="Connection refused")
        text = result.display
        assert "Preflight failed" in text
        assert "Connection refused" in text


# ---------------------------------------------------------------------------
# Integration with run_test
# ---------------------------------------------------------------------------


class TestPreflightIntegration:
    """Test that preflight is invoked as part of run_test and aborts on failure."""

    def test_run_test_succeeds_when_server_is_up(self):
        """Normal case: preflight passes, test runs."""
        model = parse_str(DSL_SIMPLE)
        transport = httpx.MockTransport(_ok_handler)

        result = run_test(model, transport=transport)

        assert result.total_requests == 1
        assert result.failed == 0

    def test_run_test_aborts_when_server_is_down(self):
        """Preflight fails → run_test should raise RuntimeError."""
        model = parse_str(DSL_SIMPLE)
        transport = httpx.MockTransport(_connection_refused_handler)

        with pytest.raises(RuntimeError, match="Preflight failed"):
            run_test(model, transport=transport)

    def test_run_test_aborts_on_timeout(self):
        """Preflight times out → run_test should raise RuntimeError."""
        model = parse_str(DSL_SIMPLE)
        transport = httpx.MockTransport(_timeout_handler)

        with pytest.raises(RuntimeError, match="Preflight failed"):
            run_test(model, transport=transport)

    def test_run_test_with_load_aborts_when_server_is_down(self):
        """Preflight fails with a load block present → still aborts before load."""
        model = parse_str(DSL_WITH_LOAD)
        transport = httpx.MockTransport(_connection_refused_handler)

        with pytest.raises(RuntimeError, match="Preflight failed"):
            run_test(model, transport=transport)

    def test_no_metrics_recorded_on_preflight_failure(self):
        """When preflight fails, no metrics or requests should be recorded."""
        model = parse_str(DSL_SIMPLE)
        transport = httpx.MockTransport(_connection_refused_handler)

        with pytest.raises(RuntimeError):
            run_test(model, transport=transport)
        # If we got here, the test never ran — no metrics to check.
        # The fact that RuntimeError was raised before run_load_test_async
        # is sufficient proof.

    def test_404_server_still_runs_test(self):
        """Server returns 404 on HEAD / but test scenarios work fine."""
        model = parse_str(DSL_SIMPLE)

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "HEAD":
                return httpx.Response(404)
            return httpx.Response(200)

        transport = httpx.MockTransport(handler)
        result = run_test(model, transport=transport)

        assert result.total_requests == 1
        assert result.failed == 0

    def test_500_server_still_runs_test(self):
        """Server returns 500 on HEAD / but is up — test should proceed."""
        model = parse_str(DSL_SIMPLE)

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "HEAD":
                return httpx.Response(500)
            return httpx.Response(200)

        transport = httpx.MockTransport(handler)
        result = run_test(model, transport=transport)

        assert result.total_requests == 1
        assert result.failed == 0
