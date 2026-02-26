import httpx

from loadforge.parser.parse import parse_str
from loadforge.runtime.runner import run_test


DSL_NO_LOAD = r'''
test "t" {
  target "http://api.test"

  scenario "s1" {
    request GET "/a"
    expect status 200
  }
}
'''

DSL_TWO_SCENARIOS = r'''
test "t" {
  target "http://api.test"

  scenario "first" {
    request GET "/a"
    expect status 200
  }

  scenario "second" {
    request GET "/b"
    expect status 200
  }
}
'''

DSL_LOAD = r'''
test "t" {
  target "http://api.test"

  scenario "s" {
    request GET "/x"
    expect status 200
  }

  load {
    users 3
    rampUp 0s
    duration 1s
  }
}
'''

DSL_LOAD_RAMPUP = r'''
test "t" {
  target "http://api.test"

  scenario "s" {
    request GET "/x"
    expect status 200
  }

  load {
    users 3
    rampUp 1s
    duration 2s
  }
}
'''

DSL_EXPECT_STATUS_FAIL = r'''
test "t" {
  target "http://api.test"

  scenario "s" {
    request GET "/x"
    expect status 200
  }
}
'''

DSL_EXPECT_JSON_FAIL = r'''
test "t" {
  target "http://api.test"

  scenario "s" {
    request GET "/x"
    expect status 200
    expect json "$.items" isArray
  }
}
'''

DSL_AUTH_WITH_LOAD = r'''
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
    format "$.token"
  }

  scenario "s" {
    request GET "/data"
    expect status 200
  }

  load {
    users 2
    rampUp 0s
    duration 1s
  }
}
'''

DSL_AUTH_FAIL = r'''
test "t" {
  environment {
    baseUrl = env("BASE_URL")
  }

  target #baseUrl

  auth login {
    endpoint "/auth"
    method POST
    body {
      user = "x"
    }
    format "$.token"
  }

  scenario "s" {
    request GET "/x"
    expect status 200
  }
}
'''

DSL_VARIABLES = r'''
test "t" {
  target "http://api.test"

  variables {
    q = "phone"
  }

  scenario "search" {
    request GET "/search?q=${q}"
    expect status 200
  }
}
'''


def _ok_handler(req: httpx.Request) -> httpx.Response:
    return httpx.Response(200)


def test_single_pass_without_load_block():
    model = parse_str(DSL_NO_LOAD)
    transport = httpx.MockTransport(_ok_handler)

    result = run_test(model, transport=transport)

    assert result.failed == 0
    assert result.total_requests == 1
    assert result.users == 1
    assert result.target_duration_seconds == 0.0


def test_single_pass_runs_all_scenarios():
    model = parse_str(DSL_TWO_SCENARIOS)
    transport = httpx.MockTransport(_ok_handler)

    result = run_test(model, transport=transport)

    assert result.failed == 0
    assert result.total_requests == 2

    by_name = {sc.name: sc for sc in result.summary.scenarios}
    assert "first" in by_name
    assert "second" in by_name
    assert by_name["first"].total_requests == 1
    assert by_name["second"].total_requests == 1


def test_load_block_runs_multiple_requests():
    model = parse_str(DSL_LOAD)
    transport = httpx.MockTransport(_ok_handler)

    result = run_test(model, transport=transport)

    assert result.failed == 0
    assert result.users == 3
    assert result.total_requests > 3
    assert result.summary.requests_per_sec > 0


def test_load_block_with_ramp_up():
    model = parse_str(DSL_LOAD_RAMPUP)
    transport = httpx.MockTransport(_ok_handler)

    result = run_test(model, transport=transport)

    assert result.failed == 0
    assert result.users == 3
    assert result.ramp_up_seconds == 1.0
    assert result.total_requests > 3
    assert result.summary.duration_seconds >= 1.5


def test_expect_status_failure_counts_as_error():
    model = parse_str(DSL_EXPECT_STATUS_FAIL)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)

    result = run_test(model, transport=transport)

    assert result.failed == 1
    assert result.total_requests == 1
    assert result.summary.error_rate == 100.0


def test_expect_json_failure_counts_as_error():
    model = parse_str(DSL_EXPECT_JSON_FAIL)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": "not-an-array"})

    transport = httpx.MockTransport(handler)

    result = run_test(model, transport=transport)

    assert result.failed == 1
    assert result.total_requests == 1


def test_auth_runs_before_load(monkeypatch):
    monkeypatch.setenv("BASE_URL", "https://api.test")
    monkeypatch.setenv("AUTH_ENDPOINT", "https://auth.test/login")
    monkeypatch.setenv("USERNAME", "u")
    monkeypatch.setenv("PASSWORD", "p")

    model = parse_str(DSL_AUTH_WITH_LOAD)
    captured_headers = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST" and str(req.url) == "https://auth.test/login":
            return httpx.Response(200, json={"token": "secret123"})
        if req.method == "GET":
            captured_headers.append(req.headers.get("Authorization"))
            return httpx.Response(200)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)

    result = run_test(model, transport=transport)

    assert result.auth_success is True
    assert result.failed == 0
    assert result.total_requests > 0
    assert all(h == "Bearer secret123" for h in captured_headers)


def test_auth_failure_aborts_load(monkeypatch):
    monkeypatch.setenv("BASE_URL", "https://api.test")

    model = parse_str(DSL_AUTH_FAIL)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    transport = httpx.MockTransport(handler)

    result = run_test(model, transport=transport)

    assert result.auth_success is False
    assert result.auth_error is not None
    assert result.total_requests == 0


def test_variable_interpolation_in_load():
    model = parse_str(DSL_VARIABLES)
    captured_paths = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured_paths.append(req.url.path + "?" + (req.url.query.decode() if req.url.query else ""))
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)

    result = run_test(model, transport=transport)

    assert result.failed == 0
    assert "/search?q=phone" in captured_paths[0]


def test_load_multiple_scenarios_all_execute():
    dsl = r'''
    test "t" {
      target "http://api.test"

      scenario "a" {
        request GET "/a"
        expect status 200
      }

      scenario "b" {
        request GET "/b"
        expect status 200
      }

      load {
        users 2
        rampUp 0s
        duration 1s
      }
    }
    '''
    model = parse_str(dsl)
    transport = httpx.MockTransport(_ok_handler)

    result = run_test(model, transport=transport)

    assert result.failed == 0
    by_name = {sc.name: sc for sc in result.summary.scenarios}
    assert "a" in by_name
    assert "b" in by_name
    assert by_name["a"].total_requests > 0
    assert by_name["b"].total_requests > 0


def test_partial_scenario_failure_records_correctly():
    dsl = r'''
    test "t" {
      target "http://api.test"

      scenario "ok" {
        request GET "/ok"
        expect status 200
      }

      scenario "bad" {
        request GET "/bad"
        expect status 200
      }
    }
    '''
    model = parse_str(dsl)

    def handler(req: httpx.Request) -> httpx.Response:
        if "/ok" in str(req.url):
            return httpx.Response(200)
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)

    result = run_test(model, transport=transport)

    assert result.total_requests == 2
    by_name = {sc.name: sc for sc in result.summary.scenarios}
    assert by_name["ok"].failed_requests == 0
    assert by_name["bad"].failed_requests == 1


def test_result_str_contains_test_name():
    model = parse_str(DSL_NO_LOAD)
    transport = httpx.MockTransport(_ok_handler)

    result = run_test(model, transport=transport)
    output = str(result)

    assert "t" in output
    assert "PASS" in output