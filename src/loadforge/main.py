from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv
from textx import metamodel_from_file

from .model import EnvVar, Ref, TestFile, Test, Environment, EnvCall, Target, Load, Duration, VariablesBlock, \
    ExpectStatus, Scenario, VarEntry, Request, ValueOrRef

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


def resolve_ref(name: str, ctx: dict[str, str]) -> str:
    if name not in ctx:
        raise RuntimeError(f"Reference '#{name}' not found.")
    return ctx[name]


def resolve_value_or_ref(vor, ctx: dict[str, str]) -> str:
    """
    Resolves ValueOrRef to a string.
    - If vor.value (STRING) is present -> returns it without quotes
    - If vor.ref is present -> resolves from ctx
    """
    if vor is None:
        raise RuntimeError("Missing value.")

    # STRING branch
    if getattr(vor, "value", ""):
        return vor.value.strip().strip('"')

    # REF branch
    ref = getattr(vor, "ref", None)
    if ref is not None:
        return resolve_ref(ref.name, ctx)

    raise RuntimeError("Invalid ValueOrRef: neither value nor ref set.")


def resolve_variables(variables: Optional[VariablesBlock], env_map: dict[str, str]) -> dict[str, str]:
    if variables is None:
        return {}

    resolved: dict[str, str] = {}
    for entry in variables.vars:
        ctx_so_far = {**env_map, **resolved}
        resolved[entry.name] = resolve_value_or_ref(entry.value, ctx_so_far)

    return resolved


def resolve_target(target: Optional[Target], ctx: dict[str, str]) -> Optional[str]:
    if target is None:
        return None
    if target.value:
        return target.value.strip().strip('"')
    if target.ref:
        return resolve_ref(target.ref.name, ctx)
    return None


def interpolate(template: str, ctx: dict[str, str]) -> str:
    s = template.strip().strip('"')

    def repl(m: re.Match) -> str:
        key = m.group(1)
        if key not in ctx:
            raise RuntimeError(f"Unknown variable in template: ${{{key}}}")
        return ctx[key]

    return _VAR_PATTERN.sub(repl, s)


def run_scenario(client: httpx.Client, scenario: Scenario, ctx: dict[str, str]) -> None:
    last_response: Optional[httpx.Response] = None

    for step in scenario.steps:
        if isinstance(step, Request):
            path = interpolate(step.path, ctx)
            last_response = client.request(step.method, path)

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


def build_context(env_map: dict[str, str], vars_map: dict[str, str]) -> dict[str, str]:
    overlap = set(env_map.keys()) & set(vars_map.keys())
    if overlap:
        dup = ", ".join(sorted(overlap))
        raise RuntimeError(f"Duplicate names in environment and variables: {dup}")
    return {**env_map, **vars_map}


def build_metamodel():
    return metamodel_from_file(
        str(GRAMMAR_PATH),
        classes=[TestFile, Test,
            Environment, EnvVar, EnvCall,
            Ref, Target,
            VariablesBlock, VarEntry, ValueOrRef,
            Scenario, Request, ExpectStatus,
            Load, Duration],
    )


def main() -> None:
    load_env_from_cwd()
    dsl_path = parse_args()

    mm = build_metamodel()
    model: TestFile = mm.model_from_file(str(dsl_path))

    env_map = resolve_env(model.test.environment)
    vars_map = resolve_variables(model.test.variables, env_map)
    ctx = build_context(env_map, vars_map)

    target_url = resolve_target(model.test.target, ctx)

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

    with httpx.Client(base_url=target_url) as client:
        for sc in model.test.scenarios:
            run_scenario(client, sc, ctx)
            print(f"Scenario OK: {sc.name}")


if __name__ == "__main__":
    main()
