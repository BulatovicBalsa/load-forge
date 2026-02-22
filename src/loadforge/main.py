from __future__ import annotations

import os
import sys
import re
from pathlib import Path
from typing import Optional, Any

import httpx
from dotenv import load_dotenv
from textx import metamodel_from_file

from .model import EnvVar, Ref, TestFile, Test, Environment, EnvCall, Target, Load, Duration, VariablesBlock, \
    ExpectStatus, Scenario, VarEntry, Request

_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)}")
HERE = Path(__file__).resolve().parent
GRAMMAR_PATH = HERE / "grammar" / "loadforge.tx"


def load_env_from_cwd() -> None:
    dotenv_path = Path.cwd() / ".env"
    if dotenv_path.exists():
        load_dotenv(dotenv_path=dotenv_path, override=False)


def resolve_env(environment: Optional[Environment]) -> dict[str, str]:
    if environment is None:
        return {}

    resolved: dict[str, str] = {}
    for v in environment.envVars:
        key = v.value.key.strip('"')  # e.g. "BASE_URL" -> BASE_URL
        val = os.getenv(key)
        if val is None:
            raise RuntimeError(
                f"Missing environment variable: {key}\n"
                f"Expected in .env located in: {Path.cwd()}"
            )
        resolved[v.name] = val
    return resolved


def variables_map(variables: Optional[VariablesBlock]) -> dict[str, str]:
    if variables is None:
        return {}
    return {v.name: v.value.strip().strip('"') for v in variables.vars}


def resolve_ref(name: str, env_map: dict[str, str], vars_map: dict[str, str]) -> str:
    if name in vars_map:
        return vars_map[name]
    if name in env_map:
        return env_map[name]
    raise RuntimeError(f"Reference '#{name}' not found (vars/environment).")


def resolve_value(value: Any, env_map: dict[str, str], vars_map: dict[str, str]) -> Any:
    if value is None:
        return None
    if isinstance(value, Ref):
        return resolve_ref(value.name, env_map, vars_map)
    if isinstance(value, str):
        return value.strip().strip('"')
    return value


def resolve_target(target: Optional[Target], env_map: dict[str, str], vars_map: dict[str, str]) -> Optional[str]:
    if target is None:
        return None
    if target.value:
        return resolve_value(target.value, env_map, vars_map)
    if target.ref:
        return resolve_value(target.ref, env_map, vars_map)
    return None


def interpolate(template: str, vars_map: dict[str, str]) -> str:
    s = template.strip().strip('"')

    def repl(m: re.Match) -> str:
        key = m.group(1)
        if key not in vars_map:
            raise RuntimeError(f"Unknown variable in template: ${{{key}}}")
        return vars_map[key]

    return _VAR_PATTERN.sub(repl, s)


def run_scenario(base_url: str, scenario: Scenario, vars_map: dict[str, str]) -> None:
    last_response: Optional[httpx.Response] = None

    with httpx.Client(base_url=base_url) as client:
        for step in scenario.steps:
            if isinstance(step, Request):
                path = interpolate(step.path, vars_map)
                method = step.method
                last_response = client.request(method, path)

            elif isinstance(step, ExpectStatus):
                if last_response is None:
                    raise RuntimeError("expect status used before any request")
                if last_response.status_code != step.code:
                    raise AssertionError(
                        f"Expected status {step.code}, got {last_response.status_code} "
                        f"for scenario {scenario.name}"
                    )


def parse_args() -> Path:
    if len(sys.argv) < 2:
        print("Usage: loadforge <file.lf>", file=sys.stderr)
        raise SystemExit(2)

    dsl_path = Path(sys.argv[1]).resolve()
    if not dsl_path.exists():
        print(f"File not found: {dsl_path}", file=sys.stderr)
        raise SystemExit(2)

    return dsl_path


def build_metamodel():
    return metamodel_from_file(
        str(GRAMMAR_PATH),
        classes=[TestFile, Test,
            Environment, EnvVar, EnvCall,
            Ref, Target,
            VariablesBlock, VarEntry,
            Scenario, Request, ExpectStatus,
            Load, Duration],
    )


def main() -> None:
    load_env_from_cwd()
    dsl_path = parse_args()

    mm = build_metamodel()
    model: TestFile = mm.model_from_file(str(dsl_path))

    env_map = resolve_env(model.test.environment)
    vars_map = variables_map(model.test.variables)
    target_url = resolve_target(model.test.target, env_map, vars_map)

    print(f"Parsed test: {model.test.name}")
    if target_url is not None:
        print(f"Target: {target_url}")

    if model.test.load is not None:
        print(f"Load: {model.test.load}")

    for scenario in model.test.scenarios:
        print(f"Scenario: {scenario.name}")
        for step in scenario.steps:
            if isinstance(step, Request):
                print(f"  Request: {step.method} {interpolate(step.path, vars_map)}")
            elif isinstance(step, ExpectStatus):
                print(f"  Expect status: {step.code}")
            else:
                print(f"  Unknown step type: {type(step)}")

    for scenario in model.test.scenarios:
        print(f"Running scenario: {scenario.name}")
        run_scenario(target_url, scenario, vars_map)


if __name__ == "__main__":
    main()
