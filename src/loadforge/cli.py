import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv

from loadforge.model import TestFile

from .parser.parse import parse_file
from .runtime.runner import run_test


@dataclass(frozen=True)
class CliOptions:
    file: Path
    env: Path | None
    control_stdin: bool
    env_needed: bool
    return_name: bool


def _build_parser() -> argparse.ArgumentParser:
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
    parser.add_argument(
        "--env-needed",
        action="store_true",
        help="Returns true if environment variables are declared in the .lf file, false otherwise.",
    )
    parser.add_argument(
        "--name",
        action="store_true",
        help="Returns the test name declared in the .lf file.",
    )
    return parser


def parse_args(argv: Sequence[str] | None = None) -> CliOptions:
    parser = _build_parser()
    args = parser.parse_args(argv)

    file_path = Path(args.file).resolve()
    if not file_path.exists():
        parser.error(f"File not found: {file_path}")

    env: Path | None = None
    if args.env:
        env = Path(args.env).resolve()
        if not env.exists():
            parser.error(f"Env file not found: {env}")

    return CliOptions(
        file=file_path,
        env=env,
        control_stdin=args.control_stdin,
        env_needed=args.env_needed,
        return_name=args.name,
    )


def force_utf8_stdio() -> None:
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


def is_env_needed(model: TestFile) -> bool:
    return bool(
        model.test and model.test.environment and model.test.environment.envVars
    )


def _print_env_needed(model: TestFile) -> int:
    print("true" if is_env_needed(model) else "false")
    return 0


def _print_test_name(model: TestFile) -> int:
    if model.test and model.test.name:
        print(model.test.name)
    return 0


def _prepare_environment(model: TestFile, env: Path | None) -> None:
    if env is None:
        if is_env_needed(model):
            raise RuntimeError(
                "Environment variables are declared in the .lf file, but no env file path was provided."
            )
        return

    load_dotenv(dotenv_path=env, override=False)


def _run_and_print(model: TestFile, *, control_stdin: bool, env_file_dir: Path) -> int:
    try:
        result = run_test(model, control_stdin=control_stdin, env_file_dir=env_file_dir)
        print(result)
        return 0
    except KeyboardInterrupt:
        print("\033[93mTest interrupted by user.\033[0m")
        return 130


def main(argv: Sequence[str] | None = None) -> int:
    force_utf8_stdio()
    options = parse_args(argv)
    model = parse_file(options.file)

    if options.env_needed:
        return _print_env_needed(model)

    if options.return_name:
        return _print_test_name(model)

    _prepare_environment(model, options.env)
    
    # Determine directory for resolving relative CSV paths
    # Prefer .env file directory, fallback to .lf file directory
    env_file_dir = options.env.parent if options.env else options.file.parent
    
    return _run_and_print(model, control_stdin=options.control_stdin, env_file_dir=env_file_dir)


if __name__ == "__main__":
    raise SystemExit(main())
