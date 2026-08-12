import json
import os
import subprocess
import sys

from _problem_planning_support import accepted_bundle_fixture


FIXTURE = "../internal/solver-fixtures/tj-2026-nankai-yimo-25.json"
ALT_FIXTURE = "../internal/solver-fixtures/tj-2026-nankai-yimo-25-alt-labels.json"
OTHER_REAL_25_FIXTURE = "../internal/solver-fixtures/tj-2026-hexi-yimo-25.json"
ENV_KEYS = [
    "SOLVER_PLANNER_MODE",
    "SOLVER_LLM_PROVIDER",
    "SOLVER_LLM_MODEL",
    "SOLVER_LLM_MAX_ATTEMPTS",
    "SOLVER_LLM_DEBUG_DIR",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "DOUBAO_API_KEY",
    "DOUBAO_BASE_URL",
    "DOUBAO_MODEL",
]


def _cli_env(**overrides: str) -> dict[str, str]:
    """清理本机私有 LLM 配置，保证 CLI 测试可重复。"""
    env = os.environ.copy()
    for key in ENV_KEYS:
        env.pop(key, None)
    env["SOLVER_PLANNER_MODE"] = "strategy"
    env["SOLVER_LLM_PROVIDER"] = "recorded"
    env.update(overrides)
    return env


def test_solve_problem_cli_outputs_json() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "shuxueshuo_server.solver.solve_problem",
            "--fixture",
            FIXTURE,
            "--planner",
            "deterministic",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=_cli_env(),
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["problem_id"] == "tj-2026-nankai-yimo-25"
    assert payload["solver_family"] == "QuadraticPathMinimumSolver"
    assert "distance_between_points" in payload["methods_used"]
    assert payload["answers"]["ii_2"]["G"] == ["4", "-13/3"]
    assert all(check["status"] == "passed" for check in payload["checks"])


def test_solve_problem_cli_resolves_repo_fixture_paths() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "shuxueshuo_server.solver.solve_problem",
            "--fixture",
            "../../internal/solver-fixtures/tj-2026-nankai-yimo-25.json",
            "--planner",
            "deterministic",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=_cli_env(),
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "ok"


def test_solve_problem_cli_rejects_strategy_problem_ir_fixture() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "shuxueshuo_server.solver.solve_problem",
            "--fixture",
            ALT_FIXTURE,
            "--planner",
            "strategy",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=_cli_env(),
    )

    assert completed.returncode != 0
    assert completed.returncode == 2
    assert "planner.problem_bundle_required" in completed.stderr
    assert completed.stdout == ""


def test_solve_problem_cli_solves_hexi_weighted_25() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "shuxueshuo_server.solver.solve_problem",
            "--fixture",
            OTHER_REAL_25_FIXTURE,
            "--planner",
            "deterministic",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=_cli_env(),
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["problem_id"] == "tj-2026-hexi-yimo-25"
    assert payload["status"] == "ok"
    assert payload["solver_family"] == "QuadraticWeightedPathMinimumSolver"
    assert payload["answers"]["iii"]["b"] == "2"
    assert payload["answers"] == {
        "i": {"P": ["1", "2"]},
        "ii": {"D": ["sqrt(2)", "1"]},
        "iii": {"b": "2"},
    }
    assert "weighted_axis_path_triangle_transform" in payload["methods_used"]
    assert "linked_broken_path_geometric_minimum" in payload["methods_used"]


def test_solve_problem_cli_strategy_recorded_explicit(tmp_path) -> None:
    root, parent, accepted, store, *_ = accepted_bundle_fixture(tmp_path)
    root_path = tmp_path / "root-context.json"
    parent_path = tmp_path / "f2-context.json"
    accepted_path = tmp_path / "accepted-context.json"
    _write_json(root_path, root.to_payload())
    _write_json(parent_path, parent.to_payload())
    _write_json(accepted_path, accepted.to_payload())
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "shuxueshuo_server.solver.solve_problem",
            "--accepted-context",
            str(accepted_path),
            "--ancestor-context",
            str(root_path),
            "--ancestor-context",
            str(parent_path),
            "--artifact-root",
            str(store.root),
            "--planner",
            "strategy",
            "--llm-provider",
            "recorded",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=_cli_env(),
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "ok"
    assert payload["answers"]["ii_2"]["G"] == ["4", "-13/3"]


def test_solve_problem_cli_strategy_deepseek_requires_key(tmp_path) -> None:
    root, parent, accepted, store, *_ = accepted_bundle_fixture(tmp_path)
    root_path = tmp_path / "root-context.json"
    parent_path = tmp_path / "f2-context.json"
    accepted_path = tmp_path / "accepted-context.json"
    _write_json(root_path, root.to_payload())
    _write_json(parent_path, parent.to_payload())
    _write_json(accepted_path, accepted.to_payload())
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "shuxueshuo_server.solver.solve_problem",
            "--accepted-context",
            str(accepted_path),
            "--ancestor-context",
            str(root_path),
            "--ancestor-context",
            str(parent_path),
            "--artifact-root",
            str(store.root),
            "--planner",
            "strategy",
            "--llm-provider",
            "deepseek",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=_cli_env(DEEPSEEK_API_KEY=""),
    )

    assert completed.returncode == 2
    assert "DEEPSEEK_API_KEY" in completed.stderr
    assert completed.stdout == ""


def _write_json(path, payload) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
