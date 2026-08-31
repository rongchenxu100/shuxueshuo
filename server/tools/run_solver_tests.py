from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
from typing import Sequence

try:
    from tools.solver_test_profiles import (
        DEFAULT_WORKERS,
        PROFILE_MARKERS,
        tests_for_changed_paths,
    )
except ModuleNotFoundError:  # Direct ``python tools/run_solver_tests.py``.
    from solver_test_profiles import (  # type: ignore[no-redef]
        DEFAULT_WORKERS,
        PROFILE_MARKERS,
        tests_for_changed_paths,
    )


SERVER_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SERVER_ROOT.parent
LIVE_ENV_PREFIXES = ("RUN_LLM_", "RUN_DEEPSEEK_", "RUN_DOUBAO_")
LIVE_ENV_NAMES = {
    "ARK_API_KEY",
    "DEEPSEEK_API_KEY",
    "DOUBAO_API_KEY",
    "OPENAI_API_KEY",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run tiered offline Solver tests without provider access.",
    )
    parser.add_argument(
        "profile",
        choices=("affected", "fast", "contract", "full"),
    )
    parser.add_argument(
        "--base",
        help="Include committed changes from BASE...HEAD for affected mode.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Parallel workers for fast/contract/full; 0 disables xdist.",
    )
    parser.add_argument("--list", action="store_true", dest="list_only")
    parser.add_argument(
        "--durations",
        type=int,
        default=None,
        metavar="N",
        help="Report the N slowest tests.",
    )
    return parser


def _git_lines(*args: str) -> tuple[str, ...]:
    result = subprocess.run(
        ("git", *args),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(line for line in result.stdout.splitlines() if line)


def changed_paths(base: str | None) -> tuple[str, ...]:
    paths: set[str] = set()
    if base:
        paths.update(_git_lines("diff", "--name-only", f"{base}...HEAD"))
    paths.update(_git_lines("diff", "--name-only", "HEAD"))
    paths.update(_git_lines("ls-files", "--others", "--exclude-standard"))
    return tuple(sorted(paths))


def sanitized_environment() -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in LIVE_ENV_NAMES
        and not key.startswith(LIVE_ENV_PREFIXES)
    }
    environment["RUN_LLM_INTEGRATION"] = "0"
    return environment


def pytest_commands(
    profile: str,
    *,
    selected_tests: Sequence[str] = (),
    workers: int | None = None,
    durations: int | None = None,
    passthrough: Sequence[str] = (),
) -> tuple[tuple[str, ...], ...]:
    base = [sys.executable, "-m", "pytest"]
    if profile == "affected":
        if not selected_tests:
            return ()
        command = [
            *base,
            *selected_tests,
            "-q",
            "-m",
            "not solver_full and not live_llm",
        ]
        if durations:
            command.extend(("--durations", str(durations)))
        command.extend(passthrough)
        return (tuple(command),)

    marker = PROFILE_MARKERS[profile]
    worker_count = DEFAULT_WORKERS if workers is None else workers
    parallel_marker = f"({marker}) and not serial"
    serial_marker = f"({marker}) and serial"
    duration_count = durations or (10 if profile == "fast" else 30)
    parallel = [
        *base,
        "tests/solver",
        "-q",
        "-m",
        parallel_marker,
        "--durations",
        str(duration_count),
    ]
    if worker_count > 0:
        parallel.extend(("-n", str(worker_count), "--dist", "worksteal"))
    parallel.extend(passthrough)
    serial = [
        *base,
        "tests/solver",
        "-q",
        "-m",
        serial_marker,
        "-n",
        "0",
        "--durations",
        str(duration_count),
        *passthrough,
    ]
    return tuple(map(tuple, (parallel, serial)))


def _display(command: Sequence[str]) -> str:
    return " ".join(command)


def _run(command: Sequence[str], *, environment: dict[str, str]) -> int:
    print(f"\n$ {_display(command)}", flush=True)
    result = subprocess.run(
        command,
        cwd=SERVER_ROOT,
        env=environment,
        check=False,
    )
    # A split serial invocation commonly collects nothing.
    return 0 if result.returncode == 5 else result.returncode


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    passthrough: tuple[str, ...] = ()
    if "--" in raw_argv:
        separator = raw_argv.index("--")
        passthrough = tuple(raw_argv[separator + 1 :])
        raw_argv = raw_argv[:separator]
    args = _parser().parse_args(raw_argv)

    selected_tests: tuple[str, ...] = ()
    if args.profile == "affected":
        paths = changed_paths(args.base)
        selected_tests, unmapped = tests_for_changed_paths(paths)
        if unmapped:
            print(
                "Unmapped Solver source paths:\n  " + "\n  ".join(unmapped),
                file=sys.stderr,
            )
            return 2
        if not selected_tests:
            print("No Solver-affecting changes detected.")
            return 0
        print("Changed paths:")
        for path in paths:
            print(f"  {path}")
        print("Selected tests:")
        for path in selected_tests:
            print(f"  {path}")

    commands = pytest_commands(
        args.profile,
        selected_tests=selected_tests,
        workers=args.workers,
        durations=args.durations,
        passthrough=passthrough,
    )
    if args.list_only:
        for command in commands:
            print(_display(command))
        return 0

    environment = sanitized_environment()
    for command in commands:
        return_code = _run(command, environment=environment)
        if return_code:
            return return_code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
