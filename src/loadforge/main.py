from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from textx import metamodel_from_file

HERE = Path(__file__).resolve().parent
GRAMMAR_PATH = HERE / "grammar" / "loadforge.tx"


def resolve_env(env_vars) -> dict[str, str]:
    resolved: dict[str, str] = {}

    for v in env_vars:
        key = v.value.key.strip('"')
        val = os.getenv(key)

        if val is None:
            raise RuntimeError(
                f"Missing environment variable: {key}\n"
                f"Expected in .env located in: {Path.cwd()}"
            )

        resolved[v.name] = val

    return resolved


def main() -> None:
    # Load .env from current working directory
    dotenv_path = Path.cwd() / ".env"
    if dotenv_path.exists():
        load_dotenv(dotenv_path=dotenv_path, override=False)

    # CLI argument
    if len(sys.argv) < 2:
        print("Usage: loadforge <file.lf>", file=sys.stderr)
        raise SystemExit(2)

    dsl_path = Path(sys.argv[1]).resolve()
    if not dsl_path.exists():
        print(f"File not found: {dsl_path}", file=sys.stderr)
        raise SystemExit(2)

    # Parse DSL
    mm = metamodel_from_file(str(GRAMMAR_PATH))
    model = mm.model_from_file(str(dsl_path))

    # Resolve env vars from DSL
    env = resolve_env(model.test.envVars) if getattr(model.test, "envVars", None) else {}

    # Minimal output (temporary)
    print(f"Parsed test: {model.test.name}")

    if env:
        print("Resolved environment:")
        for k, v in env.items():
            print(f"  {k} = {v}")


if __name__ == "__main__":
    main()
