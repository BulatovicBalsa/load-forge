import httpx
from jsonpath_ng.ext import parse as jsonpath_parse

from loadforge.model import ExpectStatus, Scenario, Request, ExpectJson
from loadforge.runtime.context import resolve_value_or_ref
from loadforge.runtime.interpolate import interpolate


def run_scenario(client: httpx.Client, scenario: Scenario, ctx: dict[str, str]) -> int:
    last_response = None
    request_count = 0

    for step in scenario.steps:
        if isinstance(step, Request):
            path = interpolate(step.path, ctx)
            last_response = client.request(step.method, path)
            request_count += 1

        elif isinstance(step, ExpectStatus):
            if last_response is None:
                raise RuntimeError("expect status used before any request")
            if last_response.status_code != step.code:
                raise AssertionError(
                    f"Expected status {step.code}, got {last_response.status_code}"
                )

        elif isinstance(step, ExpectJson):
            if last_response is None:
                raise RuntimeError("expect json used before any request")

            data = last_response.json()
            expr = jsonpath_parse(step.path.strip('"'))
            matches = expr.find(data)

            if step.check.kind == "isArray":
                if not matches or not isinstance(matches[0].value, list):
                    raise AssertionError(f"Expected JSON path to be array, got: {type(matches[0].value)}")

            elif step.check.kind == "notEmpty":
                if not matches or not matches[0].value:
                    raise AssertionError(f"Expected JSON path to be not empty, got: {type(matches[0].value)}")

            elif step.check.kind == "equals":
                expected = resolve_value_or_ref(step.check.value, ctx)
                if not matches or matches[0].value != expected:
                    raise AssertionError(f"JSON value mismatch, expected: {expected}, got: {matches[0].value}")

            elif step.check.kind == "hasSize":
                if not matches or len(matches[0].value) != step.check.size:
                    raise AssertionError(f"JSON size mismatch, expected: {step.check.size}, got: {len(matches[0].value)}")

    return request_count
