from __future__ import annotations

import inspect
from pathlib import Path

from shuxueshuo_server.solver.runtime import (
    functional_plan_reconciliation,
    recipe_compiler,
)
from shuxueshuo_server.solver.runtime.functional_state_allocation import (
    project_sibling_symbol_dependencies,
)


def test_functional_reconciliation_does_not_restore_static_state_authority() -> None:
    source = inspect.getsource(functional_plan_reconciliation)

    assert "refine_functional_object_states" not in source


def test_functional_compiler_excludes_legacy_free_parameter_selector() -> None:
    source = inspect.getsource(
        recipe_compiler._RecipePlanCompiler._projected_expansion_selectors
    )

    assert 'selector != "free_quadratic_parameter_if_read"' in source


def test_sibling_dependency_projection_marks_free_symbols_as_provisional() -> None:
    source = inspect.getsource(project_sibling_symbol_dependencies)

    assert "provisional allocation estimate" in source
    assert "Runtime Context, checkpoint" in source


def test_migrated_parameter_methods_do_not_reintroduce_local_solvers() -> None:
    methods_dir = (
        Path(__file__).parents[2]
        / "shuxueshuo_server"
        / "solver"
        / "runtime"
        / "methods"
    )
    method_files = (
        "parameter_from_curve_point_on_quadratic.py",
        "parameter_from_expression_value.py",
        "parameter_from_minimum_value.py",
        "parameter_from_segment_length.py",
    )

    for filename in method_files:
        source = (methods_dir / filename).read_text(encoding="utf-8")
        assert "solve_values(" not in source, filename
        assert "pick_by_lower_bound(" not in source, filename
