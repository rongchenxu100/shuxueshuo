"""The offline course exporter consumes a real, committed photo-learning run."""

import json

import pytest

from tests.search.function_domain_recording import revalidate_recording
from tests.solver.test_graph_stage_three_function_domain_recorded import execute
from tools.export_graph_walk_course import export_course


def test_export_actual_run_rejects_changed_inputs_hashes_and_unverified_results(tmp_path):
    execute(tmp_path, revalidate_recording())
    directory = tmp_path / "stage-two-1" / "stage-three"
    evidence = export_course(directory, "function-concepts-q15")
    assert evidence["lesson"]["goals"][0]["primary"] == "type-function-domain"
    assert evidence["stream"]["contract"] == "graph-stage-three-snapshot/v2"
    assert all("driver_state" not in row for row in evidence["stream"]["checkpoints"])
    assert len(evidence["stream"]["math_steps"]) == 4
    assert evidence["provenance"]["run_id"] == evidence["stream"]["run_id"]

    for filename, mutate, expected in [
        ("stage-one-input.json", lambda value: value["candidate"].update(original_text="changed"), "input_hash"),
        ("export-manifest.json", lambda value: value["checkpoint"].update(sha256="0" * 64), "export_hash"),
        ("export-manifest.json", lambda value: value["checkpoint"].update(path="../checkpoint.json"), "export_path"),
        ("stage-three-result.json", lambda value: value["goals"][0]["routes"][0].update(status="failed"), "unverified_route"),
    ]:
        path = directory / filename
        original = path.read_text()
        value = json.loads(original)
        mutate(value)
        path.write_text(json.dumps(value))
        try:
            with pytest.raises(ValueError, match="course_export." + expected):
                export_course(directory, "function-concepts-q15")
        finally:
            path.write_text(original)
