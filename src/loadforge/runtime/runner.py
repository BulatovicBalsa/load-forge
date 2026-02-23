import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

from .auth import run_auth_login
from ..model import TestFile
from .context import (
    resolve_env,
    resolve_variables,
    build_context,
    resolve_target,
)
from .executor import run_scenario


class Color:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"


@dataclass
class AuthResult:
    endpoint: str
    method: str
    duration_seconds: float
    success: bool
    error: Optional[str] = None


@dataclass
class ScenarioResult:
    name: str
    requests: int = 0
    success: bool = True
    error: Optional[str] = None


@dataclass
class RunResult:
    test_name: str
    duration_seconds: float
    scenarios: list[ScenarioResult] = field(default_factory=list)
    auth: Optional[AuthResult] = None

    @property
    def total_requests(self) -> int:
        total = sum(s.requests for s in self.scenarios)
        if self.auth:
            total += 1
        return total

    @property
    def failed(self) -> int:
        failures = sum(1 for s in self.scenarios if not s.success)
        if self.auth and not self.auth.success:
            failures += 1
        return failures

    @property
    def scenario_passed(self) -> int:
        return sum(1 for s in self.scenarios if s.success)

    @property
    def scenario_failed(self) -> int:
        return sum(1 for s in self.scenarios if not s.success)

    @property
    def total_steps(self) -> int:
        # auth + scenarios
        return len(self.scenarios) + (1 if self.auth else 0)

    @property
    def steps_passed(self) -> int:
        return self.total_steps - self.failed

    @staticmethod
    def _fmt_status(ok: bool) -> str:
        return f"{Color.GREEN}✔ PASS{Color.RESET}" if ok else f"{Color.RED}✘ FAIL{Color.RESET}"

    def _render_header(self) -> str:
        return (
            f"{Color.BOLD}{Color.CYAN}LoadForge Test Report{Color.RESET}\n"
            f"Test: {Color.BOLD}{self.test_name}{Color.RESET}\n"
            f"Duration: {self.duration_seconds:.3f}s\n"
        )

    def _render_auth(self) -> list[str]:
        if not self.auth:
            return []
        lines = [
            f"{Color.BOLD}Auth:{Color.RESET}\n"
            f"  {self._fmt_status(self.auth.success)}  {self.auth.method} {self.auth.endpoint} "
            f"({self.auth.duration_seconds:.3f}s)"
        ]
        if self.auth.error:
            lines.append(f"      {Color.YELLOW}{self.auth.error}{Color.RESET}")
        lines.append("")
        return lines

    def _render_scenarios(self) -> list[str]:
        lines: list[str] = []
        for s in self.scenarios:
            lines.append(f"  {self._fmt_status(s.success)}  {s.name}  (requests: {s.requests})")
            if s.error:
                lines.append(f"      {Color.YELLOW}{s.error}{Color.RESET}")
        return lines

    def _render_summary(self) -> str:
        summary = (
            f"\n{Color.BOLD}Summary:{Color.RESET}\n"
            f"  Scenarios: {len(self.scenarios)} "
            f"({Color.GREEN}{self.scenario_passed} passed{Color.RESET}, "
            f"{Color.RED}{self.scenario_failed} failed{Color.RESET})\n"
        )
        if self.auth:
            auth_status = f"{Color.GREEN}PASS{Color.RESET}" if self.auth.success else f"{Color.RED}FAIL{Color.RESET}"
            summary += f"  Auth: {auth_status}\n"
        summary += (
            f"  Total steps: {self.total_steps} "
            f"({Color.GREEN}{self.steps_passed} passed{Color.RESET}, "
            f"{Color.RED}{self.failed} failed{Color.RESET})\n"
            f"  Total requests: {self.total_requests}\n"
        )
        return summary

    def __str__(self) -> str:
        lines: list[str] = [self._render_header()]
        lines += self._render_auth()
        lines += self._render_scenarios()

        summary_color = Color.GREEN if self.failed == 0 else Color.RED
        lines.append(summary_color + self._render_summary() + Color.RESET)
        return "\n".join(lines)


def run_test(
    model: TestFile,
    *,
    transport: Optional[httpx.BaseTransport] = None,
) -> RunResult:

    if model.test is None:
        raise RuntimeError("Invalid model: missing test block.")

    t = model.test

    start = time.perf_counter()

    env_map = resolve_env(t.environment)
    vars_map = resolve_variables(t.variables, env_map)
    ctx = build_context(env_map, vars_map)

    base_url = resolve_target(t.target, ctx)
    if not base_url:
        raise RuntimeError("Missing target.")

    scenario_results: list[ScenarioResult] = []
    auth_result: Optional[AuthResult] = None

    with httpx.Client(base_url=base_url, transport=transport) as client:
        if t.auth is not None:
            auth_start = time.perf_counter()
            try:
                token = run_auth_login(client, t.auth, ctx)

                if "authToken" in ctx:
                    raise RuntimeError("Reserved name conflict: 'authToken' already defined.")
                ctx["authToken"] = token

                client.headers["Authorization"] = f"Bearer {token}"

                auth_success = True
                auth_error = None
            except Exception as e:
                auth_success = False
                auth_error = str(e)

            auth_duration = time.perf_counter() - auth_start

            endpoint_str = (
                t.auth.endpoint.value.strip('"')
                if t.auth.endpoint.value
                else f"#{t.auth.endpoint.ref.name}"
            )

            auth_result = AuthResult(
                endpoint=endpoint_str,
                method=t.auth.method,
                duration_seconds=auth_duration,
                success=auth_success,
                error=auth_error,
            )

            if not auth_success:
                duration = time.perf_counter() - start
                return RunResult(
                    test_name=t.name.strip('"'),
                    duration_seconds=duration,
                    scenarios=[],
                    auth=auth_result,
                )

        for sc in t.scenarios:
            result = ScenarioResult(name=sc.name)

            try:
                request_count = run_scenario(client, sc, ctx)
                result.requests = request_count
                result.success = True
            except Exception as e:
                result.success = False
                result.error = str(e)

            scenario_results.append(result)

    duration = time.perf_counter() - start

    return RunResult(
        test_name=t.name.strip('"'),
        duration_seconds=duration,
        scenarios=scenario_results,
        auth=auth_result,
    )
