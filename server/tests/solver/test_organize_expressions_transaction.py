"""q08 prefix through the production Functional transactional interpreter."""

from test_organize_expressions import data

from shuxueshuo_server.solver.expression_rewrite_transaction import (
    execute_rewrite_transaction,
)


def test_production_transaction_q08():
    report = execute_rewrite_transaction(data())
    assert report.call_results[0].status == "verified", report.to_payload()
    assert len(report.committed_versions) == 1
    version = report.committed_versions[0]
    assert version.version_id.ordinal == 1
    assert version.previous_version_id.ordinal == 0
    assert (
        version.version_id.slot_id.logical_key.object_id
        == version.previous_version_id.slot_id.logical_key.object_id
    )
    assert report.call_results[0].state_writes[0].allocation_action == "transition"
    assert (
        report.call_results[0].step_results[0].trace_fragments[0]["teachingEffect"]
        == "combine_fractions_revealing_condition"
    )


def test_production_transaction_invalid_last_row_zero_commits():
    fixture = data()
    fixture["call"]["parameters"]["steps"][-1]["math"] = "a+b"
    report = execute_rewrite_transaction(fixture)
    assert report.call_results[0].status == "failed"
    assert report.committed_versions == ()
    assert report.call_results[0].step_results == ()
    assert report.call_results[0].root_issues


def test_production_condition_authorities_are_individually_bound():
    report = execute_rewrite_transaction(data())
    invocation = report.compiled_calls[0].plans[0].invocations[0]
    assert len(invocation.inputs["conditions"]) == 3
    assert len(invocation.input_read_authorities["conditions"]) == 3
    assert invocation.parameters == data()["call"]["parameters"]
