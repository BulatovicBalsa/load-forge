import httpx

from loadforge.model import AuthLogin, HttpMethod, Request
from loadforge.parser.parse import parse_str
from loadforge.runtime.runner import run_test


DSL = r'''
test "t" {
  target "http://api.test"

  auth login {
    endpoint "/auth"
    method POST
    body {
      username = "u"
      password = "p"
    }
    format "$.token"
  }

  scenario "s" {
    request GET "/x"
    expect status 200
  }
}
'''


def test_http_methods_are_enums_after_parse():
    model = parse_str(DSL)
    assert model.test is not None
    assert model.test.auth is not None

    auth = model.test.auth
    assert isinstance(auth, AuthLogin)
    assert isinstance(auth.method, HttpMethod)
    assert auth.method == HttpMethod.POST

    req = next(s for s in model.test.scenarios[0].steps if isinstance(s, Request))
    assert isinstance(req.method, HttpMethod)
    assert req.method == HttpMethod.GET


def test_runtime_accepts_enum_http_methods():
    model = parse_str(DSL)

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST" and str(req.url) == "http://api.test/auth":
            return httpx.Response(200, json={"token": "abc"})
        if req.method == "GET" and str(req.url) == "http://api.test/x":
            return httpx.Response(200)
        return httpx.Response(404)

    result = run_test(model, transport=httpx.MockTransport(handler))
    assert result.success is True
