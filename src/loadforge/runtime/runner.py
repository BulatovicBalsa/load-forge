from dataclasses import dataclass
from typing import Optional

import httpx

from ..model import TestFile
from .context import (
    resolve_env,
    resolve_variables,
    build_context,
    resolve_target,
)
from .executor import run_scenario


@dataclass
class RunResult:
    test_name: str
    scenarios_run: int


def run_test(
    model: TestFile,
    *,
    transport: Optional[httpx.BaseTransport] = None,
) -> RunResult:
    if model.test is None:
        raise RuntimeError("Invalid model: missing test block.")

    t = model.test

    env_map = resolve_env(t.environment)
    vars_map = resolve_variables(t.variables, env_map)
    ctx = build_context(env_map, vars_map)

    base_url = resolve_target(t.target, ctx)
    if not base_url:
        raise RuntimeError("Missing target.")

    with httpx.Client(base_url=base_url, transport=transport) as client:
        for sc in t.scenarios:
            run_scenario(client, sc, ctx)

    return RunResult(test_name=t.name, scenarios_run=len(t.scenarios))
