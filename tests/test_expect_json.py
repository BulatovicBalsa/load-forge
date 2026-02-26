import httpx
import pytest

from loadforge.parser.parse import parse_str
from loadforge.model import ExpectJson, JsonCheckKind
from loadforge.runtime.runner import run_test


@pytest.mark.parametrize(
    "check_snippet, expected_kind",
    [
        ('expect json "$.results" isArray', JsonCheckKind.isArray),
        ('expect json "$.results" notEmpty', JsonCheckKind.notEmpty),
        ('expect json "$.token" equals "abc"', JsonCheckKind.equals),
        ('expect json "$.results" hasSize 2', JsonCheckKind.hasSize),
    ],
)
def test_each_json_check_kind_is_converted(check_snippet, expected_kind):
    dsl = rf'''
    test "t" {{
      target "https://example.com"
      scenario "s" {{
        request GET "/x"
        expect status 200
        {check_snippet}
      }}
    }}
    '''
    model = parse_str(dsl)

    step = next(s for s in model.test.scenarios[0].steps if isinstance(s, ExpectJson))
    assert isinstance(step.check.kind, JsonCheckKind)
    assert step.check.kind == expected_kind


def test_expect_json_isarray_passes_with_array():
    dsl = r'''
    test "t" {
      target "http://api.test"

      scenario "s" {
        request GET "/x"
        expect status 200
        expect json "$.results" isArray
      }
    }
    '''

    model = parse_str(dsl)

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET" and str(req.url) == "http://api.test/x":
            return httpx.Response(200, json={"results": [1, 2, 3]})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)

    result = run_test(model, transport=transport)
    assert result.failed == 0
    assert result.total_requests == 1


def test_expect_json_has_size_fails_when_size_differs():
    dsl = r'''
    test "t" {
      target "http://api.test"

      scenario "s" {
        request GET "/x"
        expect status 200
        expect json "$.results" hasSize 2
      }
    }
    '''

    model = parse_str(dsl)

    def handler(_) -> httpx.Response:
        return httpx.Response(200, json={"results": [1, 2, 3]})

    transport = httpx.MockTransport(handler)

    result = run_test(model, transport=transport)
    assert result.failed == 1
    assert result.total_requests == 1
