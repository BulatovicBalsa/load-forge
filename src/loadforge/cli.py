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


def parse_args() -> Path:
    if len(sys.argv) < 2:
        print("Usage: loadforge <file.lf>", file=sys.stderr)
        raise SystemExit(2)
    p = Path(sys.argv[1]).resolve()
    if not p.exists():
        print(f"File not found: {p}", file=sys.stderr)
        raise SystemExit(2)
    return p


def main() -> None:
    load_env_from_cwd()
    model = parse_file(parse_args())
    result = run_test(model)
    print(result)


if __name__ == "__main__":
    main()
