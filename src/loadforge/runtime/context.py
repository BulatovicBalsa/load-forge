import os
from pathlib import Path
from typing import Optional

from loadforge.model import Target, VariablesBlock, Environment


def resolve_value_or_ref(vor, ctx: dict[str, str]) -> str:
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


def resolve_variables(variables: Optional[VariablesBlock], env_map: dict[str, str]) -> dict[str, str]:
    if variables is None:
        return {}

    resolved: dict[str, str] = {}
    for entry in variables.vars:
        ctx_so_far = {**env_map, **resolved}
        resolved[entry.name] = resolve_value_or_ref(entry.value, ctx_so_far)

    return resolved


def build_context(env_map: dict[str, str], vars_map: dict[str, str]) -> dict[str, str]:
    overlap = set(env_map.keys()) & set(vars_map.keys())
    if overlap:
        dup = ", ".join(sorted(overlap))
        raise RuntimeError(f"Duplicate names in environment and variables: {dup}")
    return {**env_map, **vars_map}


def resolve_ref(name: str, ctx: dict[str, str]) -> str:
    if name not in ctx:
        raise RuntimeError(f"Reference '#{name}' not found.")
    return ctx[name]


def resolve_target(target: Optional[Target], ctx: dict[str, str]) -> Optional[str]:
    if target is None:
        return None
    if target.value:
        return target.value.strip().strip('"')
    if target.ref:
        return resolve_ref(target.ref.name, ctx)
    return None
