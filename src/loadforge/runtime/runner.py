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

    @property
    def total_requests(self) -> int:
        return sum(s.requests for s in self.scenarios)

    @property
    def failed(self) -> int:
        return sum(1 for s in self.scenarios if not s.success)

    @property
    def passed(self) -> int:
        return sum(1 for s in self.scenarios if s.success)

    def __str__(self) -> str:
        lines = []

        header = (
            f"{Color.BOLD}{Color.CYAN}LoadForge Test Report{Color.RESET}\n"
            f"Test: {Color.BOLD}{self.test_name}{Color.RESET}\n"
            f"Duration: {self.duration_seconds:.3f}s\n"
        )

        lines.append(header)

        for s in self.scenarios:
            status = (
                f"{Color.GREEN}✔ PASS{Color.RESET}"
                if s.success
                else f"{Color.RED}✘ FAIL{Color.RESET}"
            )
            lines.append(
                f"  {status}  {s.name}  "
                f"(requests: {s.requests})"
            )
            if s.error:
                lines.append(f"      {Color.YELLOW}{s.error}{Color.RESET}")

        summary_color = Color.GREEN if self.failed == 0 else Color.RED

        summary = (
            f"\n{Color.BOLD}Summary:{Color.RESET}\n"
            f"  Scenarios: {len(self.scenarios)}\n"
            f"  Passed: {Color.GREEN}{self.passed}{Color.RESET}\n"
            f"  Failed: {Color.RED}{self.failed}{Color.RESET}\n"
            f"  Total requests: {self.total_requests}\n"
        )

        lines.append(summary_color + summary + Color.RESET)

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

    with httpx.Client(base_url=base_url, transport=transport) as client:
        if t.auth is not None:
            token = run_auth_login(client, t.auth, ctx)

            if "authToken" in ctx:
                raise RuntimeError("Reserved name conflict: 'authToken' is already defined in env/variables.")
            ctx["authToken"] = token

            client.headers["Authorization"] = f"Bearer {token}"

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
    )
