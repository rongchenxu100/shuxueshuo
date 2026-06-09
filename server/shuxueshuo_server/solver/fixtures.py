"""Fixture loading for hand-authored ProblemIR inputs."""

from __future__ import annotations

import json
from pathlib import Path

from shuxueshuo_server.solver.problem_models import ProblemIR
from shuxueshuo_server.solver.runtime.projection import (
    is_canonical_problem_input,
    problem_from_canonical_input,
)


def load_problem_ir(path: str | Path) -> ProblemIR:
    fixture_path = _resolve_fixture_path(Path(path))
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    data = fixture.get("input", fixture)
    if is_canonical_problem_input(data):
        return problem_from_canonical_input(data)
    return ProblemIR(
        problem_id=data["problem_id"],
        pattern=data["pattern"],
        problem_type=data["problem_type"],
        symbols=list(data.get("symbols", [])),
        symbol_roles=dict(data.get("symbol_roles", {})),
        original_text=dict(data.get("original_text", {})),
        constraints=dict(data.get("constraints", {})),
        data=dict(data.get("data", {})),
        solver_config=dict(data.get("solver_config", {})),
        expected_answers={},
    )


def load_expected_answers(path: str | Path) -> dict:
    fixture_path = _resolve_fixture_path(Path(path))
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    if "expected" in fixture:
        return dict(fixture["expected"])
    if "expected_answers" in fixture:
        return dict(fixture["expected_answers"])
    if "input" not in fixture:
        return dict(fixture)
    return {}


def _resolve_fixture_path(path: Path) -> Path:
    if path.exists():
        return path

    repo_root = Path(__file__).resolve().parents[3]
    parts = path.parts
    if "internal" in parts:
        internal_index = parts.index("internal")
        candidate = repo_root.joinpath(*parts[internal_index:])
        if candidate.exists():
            return candidate

    candidate = repo_root / "internal" / "solver-fixtures" / path.name
    if candidate.exists():
        return candidate

    return path
