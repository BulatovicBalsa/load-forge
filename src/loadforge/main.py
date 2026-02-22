from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from textx import metamodel_from_file

from .model import EnvVar, Ref, TestFile, Test, Environment, EnvCall, Target, Load, Duration

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


def resolve_ref(name: str, env_map: dict[str, str]) -> str:
    if name not in env_map:
        raise RuntimeError(f"Reference '#{name}' not found.")
    return env_map[name]


def resolve_value(value, env_map: dict[str, str]):
    """
    Resolves ValueOrRef-like values.
    """
    if value is None:
        return None

    if isinstance(value, Ref):
        return resolve_ref(value.name, env_map)

    if isinstance(value, str):
        return value.strip()

    return value


def resolve_target(target: Optional[Target], env_map: dict[str, str]) -> Optional[str]:
    """
    Resolves `target` to an actual URL string if possible.
    - If target is STRING -> returns it
    - If target is Ref (e.g. baseUrl) -> returns env_map["baseUrl"] if present
    """
    if target is None:
        return None

    if target.value:
        return resolve_value(target.value, env_map)

    if target.ref is not None:
        return resolve_value(target.ref, env_map)

    return None


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
        classes=[TestFile, Test, Environment, EnvVar, EnvCall, Ref, Target, Load, Duration],
    )


def main() -> None:
    load_env_from_cwd()
    dsl_path = parse_args()

    mm = build_metamodel()
    model: TestFile = mm.model_from_file(str(dsl_path))

    env_map = resolve_env(model.test.environment)
    print(env_map)
    target_url = resolve_target(model.test.target, env_map)

    print(f"Parsed test: {model.test.name}")
    if target_url is not None:
        print(f"Target: {target_url}")

    if model.test.load is not None:
        print(f"Load: {model.test.load}")


if __name__ == "__main__":
    main()
