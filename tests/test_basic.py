from pathlib import Path

import pytest
from textx import metamodel_from_file

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
from loadforge.main import resolve_env, resolve_target

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

    target_url = resolve_target(model.test.target, env_map, {})
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
