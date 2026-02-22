from __future__ import annotations

from pathlib import Path
import httpx
import pytest
from textx import metamodel_from_file

from loadforge.model import (
    EnvCall, EnvVar, Environment, Ref, Target, Load, Duration,
    VariablesBlock, VarEntry, Scenario, Request, ExpectStatus,
    Test, TestFile,
)
from loadforge.runtime.context import resolve_target, build_context, resolve_env, resolve_variables

DSL = r'''
test "Hello DSL" {
  environment {
    baseUrl = env("BASE_URL")
  }

  target #baseUrl

  variables {
    q = "phone"
  }

  scenario "search" {
    request GET "/catalog/search?q=${q}"
    expect status 200
  }
}
'''


def build_mm():
    grammar_path = Path(__file__).resolve().parents[1] / "src" / "loadforge" / "grammar" / "loadforge.tx"
    return metamodel_from_file(
        str(grammar_path),
        classes=[
            TestFile, Test,
            Environment, EnvVar, EnvCall,
            Ref, Target,
            VariablesBlock, VarEntry,
            Scenario, Request, ExpectStatus,
            Load, Duration,
        ],
    )


def test_scenario_executes_and_expects_status(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BASE_URL", "https://api.example.com")

    mm = build_mm()
    model: TestFile = mm.model_from_str(DSL)
    assert model.test is not None

    env_map = resolve_env(model.test.environment)
    vars_map = resolve_variables(model.test.variables, env_map)
    ctx = build_context(env_map, vars_map)
    base = resolve_target(model.test.target, ctx)
    assert base == "https://api.example.com"

    # Mock HTTP
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/catalog/search"
        assert request.url.query.decode() == "q=phone"
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)

    with httpx.Client(base_url=base, transport=transport) as client:
        last = None
        for step in model.test.scenarios[0].steps:
            if isinstance(step, Request):
                path = step.path.strip().strip('"').replace("${q}", vars_map["q"])
                last = client.request(step.method, path)
            elif isinstance(step, ExpectStatus):
                assert last is not None
                assert last.status_code == step.code
