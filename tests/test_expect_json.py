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
    ('expect json $.results isArray',          JsonCheckKind.isArray),
    ('expect json $.results notEmpty',         JsonCheckKind.notEmpty),
    ('expect json $.results isEmpty',          JsonCheckKind.isEmpty),
    ('expect json $.token equals "abc"',       JsonCheckKind.equals),
    ('expect json $.results hasSize 2',        JsonCheckKind.hasSize),
    ('expect json $.deleted_at isNull',        JsonCheckKind.isNull),
    ('expect json $.id notNull',               JsonCheckKind.notNull),
    ('expect json $.user isObject',            JsonCheckKind.isObject),
    ('expect json $.name isString',            JsonCheckKind.isString),
    ('expect json $.count isNumber',           JsonCheckKind.isNumber),
    ('expect json $.active isBool',            JsonCheckKind.isBool),
    ('expect json $.tags contains "python"',   JsonCheckKind.contains),
    ('expect json $.email matches "[^@]+"',    JsonCheckKind.matches),
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


# ── notEmpty ──────────────────────────────────────────────────────────────────

def test_notEmpty_passes_for_non_empty_list():
    assert _passed(_run("expect json $.results notEmpty", {"results": [1]}))


def test_notEmpty_passes_for_non_empty_string():
    assert _passed(_run("expect json $.name notEmpty", {"name": "hello"}))


def test_notEmpty_fails_for_empty_list():
    result = _run("expect json $.results notEmpty", {"results": []})
    assert _failed(result)


def test_notEmpty_fails_for_empty_string():
    result = _run("expect json $.name notEmpty", {"name": ""})
    assert _failed(result)


# ── isEmpty ───────────────────────────────────────────────────────────────────

def test_isEmpty_passes_for_empty_list():
    assert _passed(_run("expect json $.results isEmpty", {"results": []}))


def test_isEmpty_passes_for_empty_string():
    assert _passed(_run("expect json $.name isEmpty", {"name": ""}))


def test_isEmpty_fails_for_non_empty_list():
    result = _run("expect json $.results isEmpty", {"results": [1, 2]})
    assert _failed(result)
    assert any("empty" in e.lower() for e in _errors(result))


def test_isEmpty_fails_for_non_empty_string():
    result = _run("expect json $.name isEmpty", {"name": "hello"})
    assert _failed(result)


def test_isEmpty_fails_for_non_sized_type():
    """isEmpty na broj treba baciti grešku jer int nije list/dict/str.""" #mozemo promijeniti
    result = _run("expect json $.count isEmpty", {"count": 5})
    assert _failed(result)


# ── equals ────────────────────────────────────────────────────────────────────

def test_equals_passes_for_matching_string():
    assert _passed(_run('expect json $.name equals "iPhone 14"', {"name": "iPhone 14"}))


def test_equals_fails_for_different_value():
    result = _run('expect json $.name equals "Galaxy"', {"name": "iPhone 14"})
    assert _failed(result)
    assert any("mismatch" in e.lower() for e in _errors(result))


# ── hasSize ───────────────────────────────────────────────────────────────────

def test_hasSize_passes_for_list():
    assert _passed(_run("expect json $.results hasSize 3", {"results": [1, 2, 3]}))


def test_hasSize_passes_for_string():
    assert _passed(_run("expect json $.name hasSize 5", {"name": "hello"}))


def test_hasSize_fails_when_size_differs():
    result = _run("expect json $.results hasSize 2", {"results": [1, 2, 3]})
    assert _failed(result)
    assert any("size mismatch" in e.lower() for e in _errors(result))


def test_hasSize_fails_for_non_sized_type():
    result = _run("expect json $.count hasSize 1", {"count": 42})
    assert _failed(result)


# ── isNull ────────────────────────────────────────────────────────────────────

def test_isNull_passes_when_field_is_null():
    assert _passed(_run("expect json $.deleted_at isNull", {"deleted_at": None}))


def test_isNull_fails_when_field_has_value():
    result = _run("expect json $.deleted_at isNull", {"deleted_at": "2024-01-01"})
    assert _failed(result)
    assert any("null" in e.lower() for e in _errors(result))


def test_isNull_fails_when_field_missing():
    """Path ne postoji u responsu — treba biti fail."""
    result = _run("expect json $.deleted_at isNull", {"other": "value"})
    assert _failed(result)


# ── notNull ───────────────────────────────────────────────────────────────────

def test_notNull_passes_when_field_has_value():
    assert _passed(_run("expect json $.id notNull", {"id": 42}))


def test_notNull_passes_for_zero():
    """0 nije null, treba proći."""
    assert _passed(_run("expect json $.count notNull", {"count": 0}))


def test_notNull_passes_for_empty_string():
    """Prazan string nije null,  treba proći."""
    assert _passed(_run("expect json $.name notNull", {"name": ""}))


def test_notNull_fails_when_field_is_null():
    result = _run("expect json $.id notNull", {"id": None})
    assert _failed(result)
    assert any("null" in e.lower() for e in _errors(result))


# ── isObject ──────────────────────────────────────────────────────────────────

def test_isObject_passes_for_dict():
    assert _passed(_run("expect json $.user isObject", {"user": {"name": "John"}}))


def test_isObject_fails_for_list():
    result = _run("expect json $.user isObject", {"user": [1, 2]})
    assert _failed(result)
    assert any("object" in e.lower() for e in _errors(result))


def test_isObject_fails_for_string():
    result = _run("expect json $.user isObject", {"user": "John"})
    assert _failed(result)


# ── isString ──────────────────────────────────────────────────────────────────

def test_isString_passes_for_string():
    assert _passed(_run("expect json $.name isString", {"name": "hello"}))


def test_isString_fails_for_number():
    result = _run("expect json $.name isString", {"name": 42})
    assert _failed(result)
    assert any("string" in e.lower() for e in _errors(result))


def test_isString_fails_for_bool():
    result = _run("expect json $.name isString", {"name": True})
    assert _failed(result)


# ── isNumber ──────────────────────────────────────────────────────────────────

def test_isNumber_passes_for_int():
    assert _passed(_run("expect json $.count isNumber", {"count": 42}))


def test_isNumber_passes_for_float():
    assert _passed(_run("expect json $.price isNumber", {"price": 9.99}))


def test_isNumber_fails_for_string():
    result = _run("expect json $.count isNumber", {"count": "42"})
    assert _failed(result)
    assert any("number" in e.lower() for e in _errors(result))


def test_isNumber_fails_for_bool():
    """bool je subclass int u Python, mora biti eksplicitno odbijen."""
    result = _run("expect json $.active isNumber", {"active": True})
    assert _failed(result)
    assert any("number" in e.lower() for e in _errors(result))


# ── isBool ────────────────────────────────────────────────────────────────────

def test_isBool_passes_for_true():
    assert _passed(_run("expect json $.active isBool", {"active": True}))


def test_isBool_passes_for_false():
    assert _passed(_run("expect json $.active isBool", {"active": False}))


def test_isBool_fails_for_int():
    """1 i 0 nisu bool u JSON kontekstu, mora biti odbijen."""
    result = _run("expect json $.active isBool", {"active": 1})
    assert _failed(result)
    assert any("boolean" in e.lower() for e in _errors(result))


def test_isBool_fails_for_string():
    result = _run('expect json $.active isBool', {"active": "true"})
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
