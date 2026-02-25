from __future__ import annotations

from typing import Any, Optional

import httpx
from jsonpath_ng.ext import parse as jsonpath_parse

from loadforge.model import ExpectStatus, Scenario, Request, ExpectJson, JsonCheckKind
from loadforge.runtime.context import resolve_value_or_ref
from loadforge.runtime.interpolate import interpolate


def _require_last_response(last_response: Optional[httpx.Response], step_name: str) -> httpx.Response:
    if last_response is None:
        raise RuntimeError(f"{step_name} used before any request")
    return last_response


def _run_request_step(client: httpx.Client, step: Request, ctx: dict[str, str]) -> httpx.Response:
    path = interpolate(step.path, ctx)
    return client.request(step.method, path)


def _run_expect_status_step(last_response: httpx.Response, step: ExpectStatus) -> None:
    if last_response.status_code != step.code:
        raise AssertionError(f"Expected status {step.code}, got {last_response.status_code}")


def _jsonpath_find(data: Any, json_path_literal: str):
    """
    Returns list of jsonpath-ng Match objects.
    """
    expr = jsonpath_parse(json_path_literal.strip().strip('"'))
    return expr.find(data)


def _first_match_value(matches, json_path_literal: str) -> Any:
    """
    Returns the first matched value, or raises if there are no matches.
    """
    if not matches:
        raise AssertionError(f"JSONPath did not match anything: {json_path_literal.strip().strip('\"')}")
    return matches[0].value


def _run_expect_json_step(last_response: httpx.Response, step: ExpectJson, ctx: dict[str, str]) -> None:
    data = last_response.json()
    matches = _jsonpath_find(data, step.path)

    kind = step.check.kind

    match kind:
        case JsonCheckKind.isArray:
            value = _first_match_value(matches, step.path)
            if not isinstance(value, list):
                raise AssertionError(f"Expected JSON path to be array, got: {type(value)}")

        case JsonCheckKind.notEmpty:
            value = _first_match_value(matches, step.path)
            if not value:
                raise AssertionError(f"Expected JSON path to be not empty, got: {value!r}")

        case JsonCheckKind.equals:
            expected = resolve_value_or_ref(step.check.value, ctx)
            value = _first_match_value(matches, step.path)
            if value != expected:
                raise AssertionError(f"JSON value mismatch, expected: {expected!r}, got: {value!r}")

        case JsonCheckKind.hasSize:
            value = _first_match_value(matches, step.path)
            if not isinstance(value, (list, dict, str)):
                raise AssertionError(f"Expected JSON path to be sized (list/dict/str), got: {type(value)}")
            actual = len(value)
            if actual != step.check.size:
                raise AssertionError(f"JSON size mismatch, expected: {step.check.size}, got: {actual}")

        case _:
            raise RuntimeError(f"Unsupported JsonCheckKind: {kind!r}")


def run_scenario(client: httpx.Client, scenario: Scenario, ctx: dict[str, str]) -> int:
    last_response: Optional[httpx.Response] = None
    request_count = 0

    for step in scenario.steps:
        if isinstance(step, Request):
            last_response = _run_request_step(client, step, ctx)
            request_count += 1
            continue

        if isinstance(step, ExpectStatus):
            resp = _require_last_response(last_response, "expect status")
            _run_expect_status_step(resp, step)
            continue

        if isinstance(step, ExpectJson):
            resp = _require_last_response(last_response, "expect json")
            _run_expect_json_step(resp, step, ctx)
            continue

        raise RuntimeError(f"Unsupported step type: {type(step).__name__}")

    return request_count