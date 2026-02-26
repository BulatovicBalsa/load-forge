from __future__ import annotations

import pytest
import httpx
from textx.exceptions import TextXSyntaxError

from loadforge.parser.parse import parse_str
from loadforge.runtime.runner import run_test
from loadforge.model import ExpectJson


def _dsl_with_path(path: str) -> str:
    """Build minimal DSL with a single expect json step using given path."""
    return rf'''
    test "t" {{
      target "http://api.test"
      scenario "s" {{
        request GET "/x"
        expect status 200
        expect json {path} isArray
      }}
    }}
    '''


def _ok_transport(json_body: dict):
    """Mock transport that always returns 200 with given JSON body."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=json_body)

    return httpx.MockTransport(handler)


@pytest.mark.parametrize("path", [
    '$.results',
    '$.results[0].name',
    '$.data.items',
    '$.token',
    '$.access_token',
    '$.results[*]',
    '$.count',
    '$.data[0]',
    '$.user.profile.name',
])
def test_valid_json_path_is_accepted(path):
    model = parse_str(_dsl_with_path(path))
    scenario = model.test.scenarios[0]
    expect_steps = [s for s in scenario.steps if isinstance(s, ExpectJson)]
    assert len(expect_steps) == 1
    assert expect_steps[0].path.startswith("$")


@pytest.mark.parametrize("path", [
    'results',  # nema $ prefiks
    '"hello"',  # slobodan string
    'access_token',  # nema $ prefiks
    'data.items',  # nema $ prefiks
])
def test_invalid_json_path_is_rejected_by_parser(path):
    with pytest.raises(TextXSyntaxError):
        parse_str(_dsl_with_path(path))


def test_bare_dollar_is_rejected():
    with pytest.raises(TextXSyntaxError):
        parse_str(_dsl_with_path('"$"'))


def test_json_path_stored_correctly_on_model():
    """Parsed path must match exactly what was written."""
    model = parse_str(_dsl_with_path('$.results[0].name'))
    steps = model.test.scenarios[0].steps
    expect_step = next(s for s in steps if isinstance(s, ExpectJson))
    assert expect_step.path == "$.results[0].name"


def test_valid_path_evaluates_array_successfully():
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
    result = run_test(model, transport=_ok_transport({"results": [1, 2, 3]}))
    assert result.failed == 0
    assert result.scenarios[0].success is True


def test_valid_nested_path_equals_value():
    model = parse_str(r'''
    test "t" {
      target "http://api.test"
      scenario "s" {
        request GET "/x"
        expect status 200
        expect json $.results[0].name equals "iPhone 14"
      }
    }
    ''')
    result = run_test(
        model,
        transport=_ok_transport({"results": [{"name": "iPhone 14"}]})
    )
    assert result.failed == 0


def test_valid_path_but_wrong_value_fails():
    model = parse_str(r'''
    test "t" {
      target "http://api.test"
      scenario "s" {
        request GET "/x"
        expect status 200
        expect json $.results[0].name equals "Galaxy S24"
      }
    }
    ''')
    result = run_test(
        model,
        transport=_ok_transport({"results": [{"name": "iPhone 14"}]})
    )
    assert result.failed == 1
    assert result.scenarios[0].success is False
    error = result.scenarios[0].error or ""
    assert "mismatch" in error.lower()


def test_path_not_found_in_response_fails():
    model = parse_str(r'''
    test "t" {
      target "http://api.test"
      scenario "s" {
        request GET "/x"
        expect status 200
        expect json $.nonexistent isArray
      }
    }
    ''')
    result = run_test(
        model,
        transport=_ok_transport({"results": [1, 2, 3]})
    )
    assert result.failed == 1
    assert result.scenarios[0].success is False
