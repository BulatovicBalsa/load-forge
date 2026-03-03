from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from loadforge.runtime.metrics import MetricsSummary


class Color:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    DIM = "\033[2m"


@dataclass
class LoadTestResult:
    """
    Final report object for a load test run.

    Wraps a MetricsSummary and an optional auth result
    """

    test_name: str
    users: int
    ramp_up_seconds: float
    target_duration_seconds: float
    summary: MetricsSummary
    auth_success: Optional[bool] = None
    auth_error: Optional[str] = None
    interrupted: bool = False
    stop_reason: Optional[str] = None
    metric_threshold_checks: int = 0
    metric_threshold_failures: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        if self.interrupted:
            return False
        if self.auth_success is False:
            return False
        if self.metric_threshold_failures:
            return False
        return self.summary.error_rate == 0.0

    @property
    def total_requests(self) -> int:
        return self.summary.total_requests

    @property
    def failed(self) -> int:
        return self.summary.failed_requests

    def _render_header(self) -> list[str]:
        lines = [
            f"{Color.BOLD}{Color.CYAN}LoadForge Load Test Report{Color.RESET}",
            f"Test: {Color.BOLD}{self.test_name}{Color.RESET}",
            f"Duration: {self.summary.duration_seconds:.1f}s "
            f"{Color.DIM}|{Color.RESET} Users: {self.users} "
            f"{Color.DIM}|{Color.RESET} Ramp-up: {self.ramp_up_seconds:.0f}s",
            "",
        ]
        return lines

    def _render_auth(self) -> list[str]:
        if self.auth_success is None:
            return []
        if self.auth_success:
            status = f"{Color.GREEN}✔ PASS{Color.RESET}"
        else:
            status = f"{Color.RED}✘ FAIL{Color.RESET}"
        lines = [f"{Color.BOLD}Auth:{Color.RESET}  {status}"]
        if self.auth_error:
            lines.append(f"  {Color.YELLOW}{self.auth_error}{Color.RESET}")
        lines.append("")
        return lines

    def _render_interrupted(self) -> list[str]:
        if not self.interrupted:
            return []
        suffix = f" ({self.stop_reason})" if self.stop_reason else ""
        return [
            f"{Color.BOLD}{Color.YELLOW}Stopped early{Color.RESET}{suffix}",
            f"{Color.DIM}Showing partial metrics collected so far.{Color.RESET}",
            "",
        ]

    def _render_throughput(self) -> list[str]:
        s = self.summary
        return [
            f"{Color.BOLD}Throughput:{Color.RESET}",
            f"  Total requests: {s.total_requests:,}",
            f"  Requests/sec:   {s.requests_per_sec:.1f}",
            "",
        ]

    def _render_latency(self) -> list[str]:
        s = self.summary
        return [
            f"{Color.BOLD}Latency (ms):{Color.RESET}",
            f"  Min: {s.latency_min_ms:<8.1f} "
            f"Avg: {s.latency_avg_ms:<8.1f} "
            f"p50: {s.latency_p50_ms:<8.1f}",
            f"  p95: {s.latency_p95_ms:<8.1f} "
            f"p99: {s.latency_p99_ms:<8.1f} "
            f"Max: {s.latency_max_ms:<8.1f}",
            "",
        ]

    def _render_errors(self) -> list[str]:
        s = self.summary
        if s.failed_requests == 0:
            color = Color.GREEN
        else:
            color = Color.RED
        return [
            f"{Color.BOLD}Errors:{Color.RESET}",
            f"  Error rate: {color}{s.error_rate:.1f}%{Color.RESET} "
            f"({s.failed_requests:,}/{s.total_requests:,})",
            "",
        ]

    def _render_scenario_table(self) -> list[str]:
        scenarios = self.summary.scenarios
        if not scenarios:
            return []

        lines: list[str] = [f"{Color.BOLD}Per-scenario breakdown:{Color.RESET}"]

        # Find the longest scenario name for alignment.
        max_name = max(len(sc.name) for sc in scenarios) if scenarios else 0
        max_name = max(max_name, 8)  # minimum column width

        for sc in scenarios:
            err_color = Color.GREEN if sc.failed_requests == 0 else Color.RED
            lines.append(
                f"  {sc.name:<{max_name}}  "
                f"reqs: {sc.total_requests:>6,}  "
                f"rps: {sc.requests_per_sec:>6.1f}  "
                f"p95: {sc.latency_p95_ms:>7.1f}ms  "
                f"err: {err_color}{sc.error_rate:.1f}%{Color.RESET}"
            )

        lines.append("")
        return lines

    def _render_metric_thresholds(self) -> list[str]:
        if self.metric_threshold_checks <= 0:
            return []

        if self.metric_threshold_failures:
            status = f"{Color.RED}✘ FAIL{Color.RESET}"
        else:
            status = f"{Color.GREEN}✔ PASS{Color.RESET}"

        lines = [
            f"{Color.BOLD}Metric thresholds:{Color.RESET}  {status}",
        ]

        for failure in self.metric_threshold_failures:
            lines.append(f"  {Color.RED}{failure}{Color.RESET}")

        lines.append("")
        return lines

    def _render_result_line(self) -> list[str]:
        if self.interrupted:
            return [f"{Color.BOLD}{Color.YELLOW}Result: STOPPED{Color.RESET}"]
        if self.success:
            return [f"{Color.BOLD}{Color.GREEN}Result: PASS{Color.RESET}"]
        else:
            return [f"{Color.BOLD}{Color.RED}Result: FAIL{Color.RESET}"]

    def __str__(self) -> str:
        parts: list[str] = []
        parts += self._render_header()
        parts += self._render_auth()
        parts += self._render_interrupted()
        parts += self._render_throughput()
        parts += self._render_latency()
        parts += self._render_errors()
        parts += self._render_scenario_table()
        parts += self._render_metric_thresholds()
        parts += self._render_result_line()
        return "\n".join(parts)
