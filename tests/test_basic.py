from pathlib import Path

import pytest
from textx import metamodel_from_file

from loadforge.main import resolve_env, resolve_target, resolve_variables, build_context
from loadforge.model import (
    EnvCall,
    EnvVar,
    Environment,
    Ref,
    Target,
    Load,
    Duration,
    Test,
    TestFile,
)

Test.__test__ = False
TestFile.__test__ = False

def build_mm() :
    grammar_path = Path(__file__).resolve().parents[1] / "src" / "loadforge" / "grammar" / "loadforge.tx"
    return metamodel_from_file(
        str(grammar_path),
        classes=[TestFile, Test, Environment, EnvVar, EnvCall, Ref, Target, Load, Duration],
    )


DSL = r'''
test "Hello DSL" {
  environment {
    baseUrl = env("BASE_URL")
  }

  target #baseUrl

  load {
    users 10
    rampUp 10s
    duration 1m
  }
}
'''


def test_target_ref_resolves(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BASE_URL", "https://api.example.com")

    mm = build_mm()
    model: TestFile = mm.model_from_str(DSL)

    assert model.test is not None
    env_map = resolve_env(model.test.environment)

    assert env_map["baseUrl"] == "https://api.example.com"

    target_url = resolve_target(model.test.target, env_map)
    assert target_url == "https://api.example.com"


def test_missing_env_var_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("BASE_URL", raising=False)

    mm = build_mm()
    model: TestFile = mm.model_from_str(DSL)

    assert model.test is not None
    with pytest.raises(RuntimeError) as e:
        resolve_env(model.test.environment)

    assert "Missing environment variable: BASE_URL" in str(e.value)


def test_duration_total_seconds(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BASE_URL", "x")

    mm = build_mm()
    model: TestFile = mm.model_from_str(DSL)

    assert model.test is not None
    assert model.test.load is not None

    assert model.test.load.ramp_up.total_seconds() == 10
    assert model.test.load.duration.total_seconds() == 60


def test_duplicate_env_and_variable_name_raises(monkeypatch):
    monkeypatch.setenv("BASE_URL", "https://api.example.com")
    monkeypatch.setenv("Q", "env-q")

    dsl = r'''
    test "t" {
      environment { q = env("Q") }
      target #q
      variables { q = "phone" }
      scenario "s" { request GET "/x" expect status 200 }
    }
    '''

    mm = build_mm()
    model: TestFile = mm.model_from_str(dsl)

    env_map = resolve_env(model.test.environment)
    vars_map = resolve_variables(model.test.variables, env_map)

    with pytest.raises(RuntimeError) as e:
        build_context(env_map, vars_map)

    assert "Duplicate names" in str(e.value)


def test_variable_can_reference_env(monkeypatch):
    monkeypatch.setenv("DEFAULT_Q", "phone")

    dsl = r'''
    test "t" {
      environment { defaultQ = env("DEFAULT_Q") }
      target "https://api.example.com"
      variables { q = #defaultQ }
      scenario "s" { request GET "/search?q=${q}" expect status 200 }
    }
    '''

    mm = build_mm()
    model: TestFile = mm.model_from_str(dsl)

    env_map = resolve_env(model.test.environment)
    vars_map = resolve_variables(model.test.variables, env_map)
    ctx = build_context(env_map, vars_map)

    assert ctx["q"] == "phone"


@pytest.mark.xfail(reason="Ordering is not flexible yet: target cannot appear after variables.")
def test_flexible_ordering_should_allow_target_after_variables():
    dsl = r'''
    test "t" {
      environment { q = env("Q") }
      variables { q = "phone" }
      target #q
      scenario "s" { request GET "/x" expect status 200 }
    }
    '''
    mm = build_mm()
    mm.model_from_str(dsl)
