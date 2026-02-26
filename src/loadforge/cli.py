# src/loadforge/cli.py
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

from .parser.parse import parse_file
from .runtime.runner import run_test


def load_env_from_cwd() -> None:
    p = Path.cwd() / ".env"
    if p.exists():
        load_dotenv(dotenv_path=p, override=False)


def parse_args() -> tuple[Path, Path | None]:
    if len(sys.argv) < 2:
        print("Usage: loadforge <file.lf>", file=sys.stderr)
        raise SystemExit(2)
    p = Path(sys.argv[1]).resolve()
    if not p.exists():
        print(f"File not found: {p}", file=sys.stderr)
        raise SystemExit(2)
    env = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else None
    if env and not env.exists():
        print(f"Env file not found: {env}", file=sys.stderr)
        raise SystemExit(2)

    return p, env


def main() -> None:
    file, env = parse_args()
    if env:
        load_dotenv(dotenv_path=env, override=False)
    else:
        load_env_from_cwd()
    model = parse_file(file)
    result = run_test(model)
    print(result)


if __name__ == "__main__":
    main()
