import httpx

from loadforge.parser.parse import parse_str
from loadforge.runtime.runner import run_test

DSL = r'''
test "t" {
  environment {
    baseUrl = env("BASE_URL")
    authEndpoint = env("AUTH_ENDPOINT")
    username = env("USERNAME")
    password = env("PASSWORD")
  }

  target #baseUrl

  auth login {
    endpoint #authEndpoint
    method POST
    body {
      username = #username
      password = #password
    }
    format "$.access_token"
  }

  scenario "s" {
    request GET "/x"
    expect status 200
  }
}
'''

def test_auth_login_sets_bearer_header(monkeypatch):
    monkeypatch.setenv("BASE_URL", "https://api.example.com")
    monkeypatch.setenv("AUTH_ENDPOINT", "https://auth.example.com/login")
    monkeypatch.setenv("USERNAME", "u")
    monkeypatch.setenv("PASSWORD", "p")

    model = parse_str(DSL)

    def handler(req: httpx.Request) -> httpx.Response:
        # 1) login call
        if req.method == "POST" and str(req.url) == "https://auth.example.com/login":
            return httpx.Response(200, json={"access_token": "TOKEN123"})

        # 2) scenario call (base_url + /x)
        if req.method == "GET" and str(req.url) == "https://api.example.com/x":
            assert req.headers.get("Authorization") == "Bearer TOKEN123"
            return httpx.Response(200)

        return httpx.Response(404)

    transport = httpx.MockTransport(handler)

    result = run_test(model, transport=transport)
    assert result.failed == 0
    assert result.total_requests == 2
