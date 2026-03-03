from __future__ import annotations

import httpx
import pytest

from loadforge.parser.parse import parse_str
from loadforge.model import ExpectJson, JsonCheckKind
from loadforge.runtime.runner import run_test


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_transport(json_body: dict, status: int = 200):
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=json_body)

    return httpx.MockTransport(handler)


def _dsl(check: str) -> str:
    return rf'''
    test "t" {{
      target "http://api.test"
      scenario "s" {{
        request GET "/x"
        expect status 200
        {check}
      }}
    }}
    '''


def _run(check: str, body: dict):
    return run_test(parse_str(_dsl(check)), transport=_make_transport(body))


def _passed(result):
    return result.summary.failed_requests == 0


def _failed(result):
    return result.summary.failed_requests > 0


def _errors(result):
    sc = next(s for s in result.summary.scenarios if s.name == "s")
    return sc.errors


# ── parametrize: grammar parses all kinds ────────────────────────────────────

@pytest.mark.parametrize("check_snippet, expected_kind", [
    ('expect json $.results isArray', JsonCheckKind.isArray),
    ('expect json $.results notEmpty', JsonCheckKind.notEmpty),
    ('expect json $.results isEmpty', JsonCheckKind.isEmpty),
    ('expect json $.token equals "abc"', JsonCheckKind.equals),
    ('expect json $.results hasSize 2', JsonCheckKind.hasSize),
    ('expect json $.deleted_at isNull', JsonCheckKind.isNull),
    ('expect json $.id notNull', JsonCheckKind.notNull),
    ('expect json $.user isObject', JsonCheckKind.isObject),
    ('expect json $.name isString', JsonCheckKind.isString),
    ('expect json $.count isNumber', JsonCheckKind.isNumber),
    ('expect json $.active isBool', JsonCheckKind.isBool),
    ('expect json $.tags contains "python"', JsonCheckKind.contains),
    ('expect json $.email matches "[^@]+"', JsonCheckKind.matches),
])
def test_each_json_check_kind_is_parsed(check_snippet, expected_kind):
    model = parse_str(_dsl(check_snippet))
    step = next(
        s for s in model.test.scenarios[0].steps
        if isinstance(s, ExpectJson)
    )
    assert isinstance(step.check.kind, JsonCheckKind)
    assert step.check.kind == expected_kind


# ── isArray ───────────────────────────────────────────────────────────────────

def test_isArray_passes_for_list():
    assert _passed(_run("expect json $.results isArray", {"results": [1, 2, 3]}))


def test_isArray_fails_for_object():
    result = _run("expect json $.results isArray", {"results": {"a": 1}})
    assert _failed(result)
    assert any("array" in e.lower() for e in _errors(result))


def test_isArray_fails_for_string():
    result = _run("expect json $.results isArray", {"results": "hello"})
    assert _failed(result)


def test_expect_json_isarray_passes_with_array():
    model = parse_str(r'''
    test "t" {
      target "http://api.test"
      scenario "s" {
        request GET "/x"
        expect status 200
        expect json $.results isArray
      }
    }
    ''')

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET" and str(req.url) == "http://api.test/x":
            return httpx.Response(200, json={"results": [1, 2, 3]})
        return httpx.Response(404)

    result = run_test(model, transport=httpx.MockTransport(handler))
    assert result.summary.failed_requests == 0
    assert result.summary.total_requests == 1


def test_expect_json_has_size_fails_when_size_differs():
    model = parse_str(r'''
    test "t" {
      target "http://api.test"
      scenario "s" {
        request GET "/x"
        expect status 200
        expect json $.results hasSize 2
      }
    }
    ''')

    result = run_test(
        model,
        transport=_make_transport({"results": [1, 2, 3]})
    )
    assert result.summary.failed_requests == 1
    assert result.summary.total_requests == 1
