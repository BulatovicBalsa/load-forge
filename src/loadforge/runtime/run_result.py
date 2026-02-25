from dataclasses import field, dataclass
from typing import Optional


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