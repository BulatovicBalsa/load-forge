# src/loadforge/cli.py
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

from .parser.parse import parse_file
from .runtime.runner import run_test


def parse_args() -> tuple[Path, Path]:
    if len(sys.argv) < 3:
        print("Usage: loadforge <file.lf> <env path>", file=sys.stderr)
        raise SystemExit(2)
    p = Path(sys.argv[1]).resolve()
    if not p.exists():
        print(f"File not found: {p}", file=sys.stderr)
        raise SystemExit(2)
    env = Path(sys.argv[2]).resolve()
    if not env.exists():
        print(f"Env file not found: {env}", file=sys.stderr)
        raise SystemExit(2)

    return p, env


def main() -> None:
    file, env = parse_args()
    load_dotenv(dotenv_path=env, override=False)
    model = parse_file(file)
    result = run_test(model)
    print(result)


if __name__ == "__main__":
    main()
