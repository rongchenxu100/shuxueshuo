from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from shuxueshuo_server.solver.extraction.problem_domain_smoke import (
    DEFAULT_F2_INPUT,
    _repo_root,
    _resolve_repo_path,
)
from shuxueshuo_server.solver.lesson_authoring_support import build_recorded_snapshot
from shuxueshuo_server.solver.lesson_capability_coverage_review import (
    RECORDED_CASE_IDS,
    build_capability_coverage_review,
    write_capability_coverage_review,
)
from shuxueshuo_server.solver.lesson_capability_synthetic import (
    build_synthetic_capability_scenarios,
)


@pytest.fixture(scope="module")
def c0_review_artifacts():
    root = _repo_root()
    with TemporaryDirectory(prefix="lesson-c0-pages-") as temp_dir:
        snapshots = tuple(
            build_recorded_snapshot(
                problem_id,
                authority_dir=Path(temp_dir) / problem_id,
                f2_root=_resolve_repo_path(root, DEFAULT_F2_INPUT),
            )
            for problem_id in RECORDED_CASE_IDS
        )
    return build_capability_coverage_review(
        snapshots=snapshots,
        synthetic_scenarios=build_synthetic_capability_scenarios(),
    )


def test_all_five_recorded_cases_build_recursive_lesson_and_visual_pages(
    c0_review_artifacts,
) -> None:
    assert set(c0_review_artifacts.recorded) == set(RECORDED_CASE_IDS)
    for case in c0_review_artifacts.recorded.values():
        assert case.lesson_build.lesson.steps
        assert len(case.visual_ir.steps) == len(case.lesson_build.lesson.steps)
        assert all(step.frames for step in case.visual_ir.steps)
        assert case.compiled.geometry_spec
        assert case.compiled.lesson_data


def test_review_writer_compiles_five_recorded_and_three_synthetic_pages(
    c0_review_artifacts,
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "f5-f5c0-public-capability-review"
    write_capability_coverage_review(
        c0_review_artifacts,
        output_dir=output_dir,
    )
    assert (output_dir / "review.html").is_file()
    assert (output_dir / "capability-coverage.json").is_file()
    for problem_id in RECORDED_CASE_IDS:
        assert (output_dir / "cases" / problem_id / "lesson.html").is_file()
    for capability_id in (
        "distance_between_points",
        "equal_length_ray_point",
        "line_intersection_point",
    ):
        target = output_dir / "synthetic" / capability_id
        assert (target / "lesson.html").is_file()
        assert (target / "teaching-source.json").is_file()
        assert (target / "bound-material.json").is_file()
        assert (target / "review.html").is_file()
