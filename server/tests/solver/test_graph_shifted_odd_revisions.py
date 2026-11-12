"""Real dependency-byte changes must invalidate every T6 recovery boundary."""

import pytest

from shuxueshuo_server.graph_lesson.stage_one.extraction import frozen_files
from shuxueshuo_server.graph_lesson.stage_three import (
    calculations,
    execution_contracts,
    runner,
)
from shuxueshuo_server.graph_lesson.stage_three.contracts import ROOT
from shuxueshuo_server.problem_understanding.workflow_ledger import (
    Budget,
    Ledger,
    WorkflowStop,
)
from tests.solver.test_graph_function_parity_recognition import recognize
from tests.solver.test_graph_shifted_odd import candidate
from tests.solver.test_graph_stage_three_methods import start


def _files(directory):
    return {
        str(p.relative_to(directory)): p.read_bytes()
        for p in directory.rglob("*")
        if p.is_file()
    }


@pytest.mark.serial
@pytest.mark.stage_three_db
def test_real_math_changes_reject_old_workflow_checkpoint_and_manifest_without_partial_write(
    tmp_path,
):
    recognize(candidate(), tmp_path)
    output = tmp_path / "stage-three"
    assert (
        runner.run_sample(tmp_path / "stage-two/stage-two-result.json", output)[
            "goals"
        ][0]["status"]
        == "solved"
    )
    workflow = tmp_path / "workflow"
    with Ledger(workflow, {"files": frozen_files()}, Budget()):
        pass
    state = start()
    collectors = [frozen_files, runner.fingerprint, execution_contracts.revisions]
    before = [read() for read in collectors]
    saved_output, saved_workflow = _files(output), _files(workflow)
    for relative in (
        "shifted_odd_math.py",
        "shifted_odd_identity.py",
        "stage_two/shifted_odd_surface.py",
        "stage_three/abstract_function_domain.py",
    ):
        path = ROOT / "server/shuxueshuo_server/graph_lesson" / relative
        module = path.stem
        original = path.read_bytes()
        try:
            path.write_bytes(original + b"\n# dependency identity regression probe\n")
            for i, read in enumerate(collectors):
                changed = read()
                key = module if i == 2 else str(path.relative_to(ROOT))
                assert changed[key] != before[i][key]
                assert {k for k in changed if changed[k] != before[i][k]} == {key}
            with (
                pytest.raises(WorkflowStop, match="workflow.stale_binding"),
                Ledger(workflow, {"files": frozen_files()}, Budget()),
            ):
                pytest.fail("old workflow accepted changed mathematics")
            calculations._session_contracts.cache_clear()
            with pytest.raises(
                ValueError, match="execution.contract_revisions_changed"
            ):
                calculations.dispatch({"operation": "advance", "state": state})
            with pytest.raises(ValueError, match="checkpoint.revisions_changed"):
                runner.resume_sample(output)
            current_output = _files(output)
            assert {k: current_output[k] for k in saved_output} == saved_output
            # A new read-only admission receipt is audit data, not a rewritten checkpoint.
            assert all(
                k.startswith("preparation/admission-")
                for k in current_output.keys() - saved_output.keys()
            )
            assert _files(workflow) == saved_workflow
        finally:
            path.write_bytes(original)
            calculations._session_contracts.cache_clear()
        assert [read() for read in collectors] == before
    assert runner.resume_sample(output)["goals"][0]["status"] == "solved"
