import json
import subprocess
import sys


FIXTURE = "../internal/solver-fixtures/tj-2026-nankai-yimo-25.json"
ALT_FIXTURE = "../internal/solver-fixtures/tj-2026-nankai-yimo-25-alt-labels.json"
OTHER_REAL_25_FIXTURE = "../internal/solver-fixtures/tj-2026-hexi-yimo-25.json"


def test_solve_problem_cli_outputs_json() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "shuxueshuo_server.solver.solve_problem",
            "--fixture",
            FIXTURE,
        ],
        check=False,
        capture_output=True,
        text=True,
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
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "ok"


def test_solve_problem_cli_returns_unsupported_for_non_default_labels() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "shuxueshuo_server.solver.solve_problem",
            "--fixture",
            ALT_FIXTURE,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    payload = json.loads(completed.stdout)
    assert payload["problem_id"] == "tj-2026-nankai-yimo-25-alt-labels"
    assert payload["status"] == "unsupported"


def test_solve_problem_cli_solves_hexi_weighted_25() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "shuxueshuo_server.solver.solve_problem",
            "--fixture",
            OTHER_REAL_25_FIXTURE,
        ],
        check=False,
        capture_output=True,
        text=True,
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
