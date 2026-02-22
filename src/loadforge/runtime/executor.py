from typing import Optional

import httpx

from loadforge.model import ExpectStatus, Scenario, Request
from loadforge.runtime.interpolate import interpolate


def run_scenario(client: httpx.Client, scenario: Scenario, ctx: dict[str, str]) -> None:
    last_response: Optional[httpx.Response] = None

    for step in scenario.steps:
        if isinstance(step, Request):
            path = interpolate(step.path, ctx)
            last_response = client.request(step.method, path)

        elif isinstance(step, ExpectStatus):
            if last_response is None:
                raise RuntimeError("expect status used before any request")
            if last_response.status_code != step.code:
                raise AssertionError(
                    f"Expected status {step.code}, got {last_response.status_code} "
                    f"for scenario {scenario.name}"
                )
