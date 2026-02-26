# src/loadforge/cli.py
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

from .parser.parse import parse_file
from .runtime.runner import run_test


def parse_args() -> tuple[Path, Path | None]:
    if len(sys.argv) not in (2, 3):
        print("Usage: loadforge <file.lf> [env path]", file=sys.stderr)
        raise SystemExit(2)
    p = Path(sys.argv[1]).resolve()
    if not p.exists():
        print(f"File not found: {p}", file=sys.stderr)
        raise SystemExit(2)

    if len(sys.argv) == 3:
        env = Path(sys.argv[2]).resolve()
        if not env.exists():
            print(f"Env file not found: {env}", file=sys.stderr)
            raise SystemExit(2)
        return p, env

    return p, None


def main() -> None:
    file, env = parse_args()
    model = parse_file(file)
    if env is None:
        has_env_vars = bool(
            model.test and model.test.environment and model.test.environment.envVars
        )
        if has_env_vars:
            raise RuntimeError(
                "Environment variables are declared in the .lf file, but no env file path was provided."
            )
    else:
        load_dotenv(dotenv_path=env, override=False)
    result = run_test(model)
    print(result)


if __name__ == "__main__":
    main()
