"""
Assertion helpers for scenario expect steps (status and JSON).
"""
from __future__ import annotations

import re
from typing import Any

import httpx
from jsonpath_ng.ext import parse as jsonpath_parse

from loadforge.model import ExpectJson, ExpectStatus, JsonCheckKind
from loadforge.runtime.context import resolve_value_or_ref


def run_expect_status_step(
    last_response: httpx.Response, step: ExpectStatus
) -> None:
    if last_response.status_code != step.code:
        raise AssertionError(
            f"Expected status {step.code}, got {last_response.status_code}"
        )


def jsonpath_find(data: Any, json_path_literal: str):
    expr = jsonpath_parse(json_path_literal.strip().strip('"'))
    return expr.find(data)


def first_match_value(matches, json_path_literal: str) -> Any:
    if not matches:
        raise AssertionError(
            f"JSONPath did not match anything: {json_path_literal.strip().strip('\"')}"
        )
    return matches[0].value


def run_expect_json_step(
    last_response: httpx.Response, step: ExpectJson, ctx: dict[str, str]
) -> None:
    data = last_response.json()
    matches = jsonpath_find(data, step.path)
    kind = step.check.kind

    match kind:
        case JsonCheckKind.isArray:
            value = first_match_value(matches, step.path)
            if not isinstance(value, list):
                raise AssertionError(
                    f"Expected JSON path to be array, got: {type(value)}"
                )
        case JsonCheckKind.notEmpty:
            value = first_match_value(matches, step.path)
            if not value:
                raise AssertionError(
                    f"Expected JSON path to be not empty, got: {value!r}"
                )
        case JsonCheckKind.isEmpty:
            value = first_match_value(matches, step.path)
            if not isinstance(value, (list, dict, str)):
                raise AssertionError(
                    f"Expected '{step.path}' to be a list/dict/str for isEmpty, "
                    f"got: {type(value).__name__}"
                )
            if len(value) != 0:
                raise AssertionError(
                    f"Expected '{step.path}' to be empty, got {len(value)} elements"
                )
        case JsonCheckKind.equals:
            expected = resolve_value_or_ref(step.check.value, ctx)
            value = first_match_value(matches, step.path)
            if value != expected:
                raise AssertionError(
                    f"JSON value mismatch, expected: {expected!r}, got: {value!r}"
                )
        case JsonCheckKind.hasSize:
            value = first_match_value(matches, step.path)
            if not isinstance(value, (list, dict, str)):
                raise AssertionError(
                    f"Expected JSON path to be sized (list/dict/str), got: {type(value)}"
                )
            actual = len(value)
            if actual != step.check.size:
                raise AssertionError(
                    f"JSON size mismatch, expected: {step.check.size}, got: {actual}"
                )
        case JsonCheckKind.isNull:
            if not matches or matches[0].value is not None:
                actual = matches[0].value if matches else "<no match>"
                raise AssertionError(
                    f"Expected '{step.path}' to be null, got: {actual!r}"
                )
        case JsonCheckKind.notNull:
            if not matches or matches[0].value is None:
                raise AssertionError(
                    f"Expected '{step.path}' to be not null, got null or no match"
                )
        case JsonCheckKind.isObject:
            value = first_match_value(matches, step.path)
            if not isinstance(value, dict):
                raise AssertionError(
                    f"Expected '{step.path}' to be an object, "
                    f"got: {type(value).__name__}"
                )
        case JsonCheckKind.isString:
            value = first_match_value(matches, step.path)
            if not isinstance(value, str):
                raise AssertionError(
                    f"Expected '{step.path}' to be a string, "
                    f"got: {type(value).__name__}"
                )
        case JsonCheckKind.isNumber:
            value = first_match_value(matches, step.path)
            # bool is a subclass of int in Python
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise AssertionError(
                    f"Expected '{step.path}' to be a number, "
                    f"got: {type(value).__name__}"
                )
        case JsonCheckKind.isBool:
            value = first_match_value(matches, step.path)
            if not isinstance(value, bool):
                raise AssertionError(
                    f"Expected '{step.path}' to be a boolean, "
                    f"got: {type(value).__name__}"
                )
        case JsonCheckKind.contains:
            expected = resolve_value_or_ref(step.check.value, ctx)
            value = first_match_value(matches, step.path)
            if isinstance(value, list):
                if expected not in [str(v) for v in value]:
                    raise AssertionError(
                        f"Expected '{step.path}' to contain {expected!r}, "
                        f"got: {value!r}"
                    )
            elif isinstance(value, str):
                if expected not in value:
                    raise AssertionError(
                        f"Expected '{step.path}' to contain {expected!r}, "
                        f"got: {value!r}"
                    )
            else:
                raise AssertionError(
                    f"'contains' requires list or string at '{step.path}', "
                    f"got: {type(value).__name__}"
                )
        case JsonCheckKind.matches:
            pattern = resolve_value_or_ref(step.check.value, ctx)
            value = first_match_value(matches, step.path)
            if not isinstance(value, str):
                raise AssertionError(
                    f"'matches' requires string at '{step.path}', "
                    f"got: {type(value).__name__}"
                )
            if not re.search(pattern, value):
                raise AssertionError(
                    f"Expected '{step.path}' to match pattern {pattern!r}, "
                    f"got: {value!r}"
                )
        case _:
            raise RuntimeError(f"Unsupported JsonCheckKind: {kind!r}")