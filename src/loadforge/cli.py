import argparse
import sys
import os
from pathlib import Path

from dotenv import load_dotenv

from .parser.parse import parse_file
from .runtime.runner import run_test


def parse_args() -> tuple[Path, Path | None, bool]:
    parser = argparse.ArgumentParser(
        prog="loadforge",
        description="Run a LoadForge test file.",
    )
    parser.add_argument("file", help="Path to .lf file")
    parser.add_argument("env", nargs="?", help="Optional path to .env file")
    parser.add_argument(
        "--control-stdin",
        action="store_true",
        help="Enable STOP control command via stdin pipe.",
    )

    args = parser.parse_args()

    p = Path(args.file).resolve()
    if not p.exists():
        parser.error(f"File not found: {p}")

    env: Path | None = None
    if args.env:
        env = Path(args.env).resolve()
        if not env.exists():
            parser.error(f"Env file not found: {env}")

    return p, env, args.control_stdin

def force_utf8_stdio():
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")

    # noinspection PyBroadException
    try:
        # Python 3.7+
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def main() -> None:
    force_utf8_stdio()
    file, env, control_stdin = parse_args()
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

    try:
        result = run_test(model, control_stdin=control_stdin)
        print(result)
    except KeyboardInterrupt:
        print("\033[93mTest interrupted by user.\033[0m")


if __name__ == "__main__":
    main()
