import json
from pathlib import Path

import pytest

from shuxueshuo_server.solver.explanation.expression_rewrite import (
    build_rewrite_presentation,
)
from shuxueshuo_server.solver.math_kernel import SympyKernel
from shuxueshuo_server.solver.math_kernel.expression_rewrite import (
    RewriteError,
    parse_expression,
    parse_relation,
)
from shuxueshuo_server.solver.runtime.functional_diagnostics import StatelessMethodError
from shuxueshuo_server.solver.runtime.methods.organize_expressions import (
    OrganizeExpressionsMethod,
)

FIXTURE = Path(__file__).parent / "fixtures/expression_rewrite/q08.json"


def data():
    return json.loads(FIXTURE.read_text())


def run(d):
    kernel = SympyKernel()
    symbols = kernel.symbols(d["symbols"])
    return OrganizeExpressionsMethod().run(
        {
            "expression": parse_expression(d["expression"], symbols).value,
            "conditions": [
                parse_relation(v, symbols) for v in d["conditions"].values()
            ],
            "__parameters__": d["call"]["parameters"],
        },
        kernel,
    )


def test_q08_verified_operations_and_display():
    result = run(data())
    assert list(result.outputs) == ["organized_expression"]
    trace = result.trace_fragments[0]
    assert [t["operation"] for t in trace["transitions"]] == [
        "combine_fractions",
        "substitute_condition",
    ]
    assert trace["teachingEffect"] == "combine_fractions_revealing_condition"
    assert len(trace["transitions"][0]["unchanged"]) == 1
    student = build_rewrite_presentation(trace)
    assert len(student["visual"]["beats"]) == 4
    assert "定积" not in json.dumps(student, ensure_ascii=False)
    assert all(c.ok for c in result.checks)


@pytest.mark.parametrize(
    "kind",
    [
        "wrong_result",
        "missing_using",
        "forged_condition",
        "wrong_start",
        "missing_domain",
        "undefined_intermediate",
    ],
)
def test_invalid_chain_rejected(kind):
    d = data()
    steps = d["call"]["parameters"]["steps"]
    if kind == "wrong_result":
        steps[-1]["math"] = "(a+b)/3+8/(a+b)"
    if kind == "missing_using":
        steps[-1].pop("using")
    if kind == "forged_condition":
        steps[-1]["using"] = ["a*b=2"]
    if kind == "wrong_start":
        steps[0]["math"] = "a+b"
    if kind == "missing_domain":
        d["conditions"] = {"product_condition": "a*b=1"}
    if kind == "undefined_intermediate":
        steps[1]["math"] = "1/(a-a)"
    with pytest.raises(StatelessMethodError):
        run(d)


@pytest.mark.parametrize(
    "source",
    [
        "__import__('os').system('true')",
        "a.__class__",
        "sqrt(a)",
        "c+a",
        "a**100000",
        "a[0]",
    ],
)
def test_restricted_parser(source):
    with pytest.raises(RewriteError):
        parse_expression(source, SympyKernel().symbols(["a", "b"]))


def test_structure_not_discarded():
    p = parse_expression("3*a+(a+b)", SympyKernel().symbols(["a", "b"]))
    assert p.tree["children"][1]["op"] == "add"
    assert str(p.value) == "4*a + b"


def test_rename_and_coefficients():
    d = data()
    d["symbols"] = ["u", "v"]
    d["expression"] = "5/(u+v)+1/(3*v)+1/(3*u)"
    d["conditions"] = {"p": "u>0", "q": "v>0", "fixed": "u*v=2"}
    d["call"]["parameters"]["steps"] = [
        {"math": d["expression"]},
        {"math": "5/(u+v)+(u+v)/(3*u*v)"},
        {"math": "5/(u+v)+(u+v)/6", "using": ["u*v=2"]},
    ]
    assert [t["operation"] for t in run(d).trace_fragments[0]["transitions"]] == [
        "combine_fractions",
        "substitute_condition",
    ]


def test_equivalent_is_not_automatically_common_denominator():
    d = data()
    d["expression"] = "a*(b+1)"
    d["call"]["parameters"]["steps"] = [{"math": "a*(b+1)"}, {"math": "a*b+a"}]
    assert (
        run(d).trace_fragments[0]["transitions"][0]["operation"] == "equivalent_rewrite"
    )


def test_registered_executor_and_single_final_version():
    from shuxueshuo_server.solver.expression_rewrite_experiment import RewriteExperiment

    host = RewriteExperiment(data())
    output = host.function.returns[0]
    assert output.identity_policy == "preserve_input_object"
    assert output.identity_arg == "expression"
    assert output.write_mode == "transition"
    record = host.execute(data()["call"])
    versions = host.index.versions_for(host.logical)
    assert len(versions) == 2  # one given + one committed, not one per row
    assert (
        versions[0].version_id.slot_id.logical_key.object_id
        == versions[1].version_id.slot_id.logical_key.object_id
    )
    assert record["goalSolved"] is False
    assert (
        record["trace"]["conditionCards"][2]["source"]
        == "$problem.constraints.product_condition"
    )


def test_atomic_invalid_second_transition_does_not_mutate_state():
    from shuxueshuo_server.solver.expression_rewrite_experiment import RewriteExperiment

    host = RewriteExperiment(data())
    original = host.context
    call = data()["call"]
    call["parameters"]["steps"][-1]["math"] = "a+b"
    with pytest.raises(StatelessMethodError):
        host.execute(call)
    assert host.context is original
    assert len(host.index.versions_for(host.logical)) == 1
    assert "rewrite_1" not in host.context.scopes


def test_parameters_replay_hash_and_serialization():
    from shuxueshuo_server.solver.runtime.functional_plan_models import (
        FunctionalCall,
        FunctionalCallReconciliation,
    )
    from shuxueshuo_server.solver.runtime.functional_state_allocation import (
        functional_computation_key,
    )
    from shuxueshuo_server.solver.runtime.state_identity import ComputationKey

    parameters = data()["call"]["parameters"]
    call = FunctionalCall(
        call_id="rewrite_1",
        capability_id="organize_expressions",
        args={},
        return_bindings={},
        strategy="",
        reason="",
        parameters=parameters,
    )
    assert call.to_payload()["parameters"] == parameters
    reconciliation = FunctionalCallReconciliation(
        call.call_id, "problem", call.capability_id, {}, (), parameters=parameters
    )
    assert reconciliation.to_payload()["parameters"] == parameters
    computed = functional_computation_key(
        call,
        resolved_args={},
        scope_id="problem",
        identity_factory=None,
        identity_index=None,
    )
    from dataclasses import replace

    changed = replace(call, parameters={"steps": [{"math": "a"}, {"math": "a+0"}]})
    assert computed != functional_computation_key(
        changed,
        resolved_args={},
        scope_id="problem",
        identity_factory=None,
        identity_index=None,
    )
    key = ComputationKey("organize_expressions", parameters_hash="first")
    assert ComputationKey.from_payload(key.to_payload()) == key
    assert key != ComputationKey("organize_expressions", parameters_hash="changed")
    assert "parameters_hash" not in ComputationKey("old_method").to_payload()


def test_old_methods_reject_undeclared_parameters():
    from jsonschema import ValidationError

    from shuxueshuo_server.solver.runtime.method_parameters import validate_parameters

    assert validate_parameters(None, {}) == {}
    with pytest.raises(ValidationError):
        validate_parameters(None, {"steps": []})


@pytest.mark.parametrize(
    "steps",
    [
        [],
        [{"math": "a"}],
        [{"math": "a"}] * 13,
        [{"math": "a", "reason": "test"}, {"math": "a"}],
    ],
)
def test_parameter_schema_rejection(steps):
    d = data()
    d["call"]["parameters"]["steps"] = steps
    with pytest.raises(StatelessMethodError):
        run(d)


def test_condition_list_capability_projection():
    from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
        _lower_runtime_container,
    )

    types, cardinality, aggregation = _lower_runtime_container("ConditionList", "one")
    assert types == ("Condition", "Constraint", "Equation")
    assert cardinality == "many" and aggregation == "condition_list"


def test_compressed_route_verified_but_no_invented_operation():
    d = data()
    d["call"]["parameters"]["steps"].pop(1)
    trace = run(d).trace_fragments[0]
    assert trace["teachingEffect"] == "equivalent_rewrite"
    assert trace["transitions"][0]["operation"] == "equivalent_rewrite"


def test_generated_highlight_and_local_node_references_resolve():
    trace = run(data()).trace_fragments[0]

    def ids(tree):
        return {tree["id"]}.union(*(ids(c) for c in tree.get("children", [])))

    for transition in trace["transitions"]:
        for mark in transition["highlights"]:
            assert mark["nodeId"] in ids(transition[mark["side"]]["tree"])
        for side, local in (("before", "localBefore"), ("after", "localAfter")):
            assert set(transition[local]["nodeIds"]) <= ids(transition[side]["tree"])


def test_scoped_parameters_roundtrip():
    # The wire-level step schema, independently of problem binding resolution.
    from jsonschema import Draft202012Validator

    from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
        scoped_functional_plan_schema,
    )

    schema = scoped_functional_plan_schema()
    Draft202012Validator({"$ref": "#/$defs/step", "$defs": schema["$defs"]}).validate(
        data()["call"]
    )


def test_changed_parameters_cannot_reuse_pinned_reconciliation():
    from shuxueshuo_server.solver.runtime.functional_plan_models import (
        FunctionalCall,
        FunctionalCallReconciliation,
    )
    from shuxueshuo_server.solver.runtime.functional_plan_reconciliation import (
        _pinned_call_reconciliation_issue,
    )

    parameters = data()["call"]["parameters"]
    call = FunctionalCall(
        "rewrite_1", "organize_expressions", {}, {}, "", "", parameters=parameters
    )
    pinned = FunctionalCallReconciliation(
        "rewrite_1", "problem", "organize_expressions", {}, (), parameters=parameters
    )
    assert (
        _pinned_call_reconciliation_issue(call, scope_id="problem", pinned=pinned)
        is None
    )
    from dataclasses import replace

    assert (
        _pinned_call_reconciliation_issue(
            replace(call, parameters={}), scope_id="problem", pinned=pinned
        )
        is not None
    )


def test_snapshot_lesson_and_visual_generated_from_verified_trace(tmp_path):
    from unittest.mock import patch

    from shuxueshuo_server.solver.expression_rewrite_experiment import (
        RewriteExperiment,
        generate_preview,
    )

    record = RewriteExperiment(data()).execute(data()["call"])
    with patch(
        "shuxueshuo_server.solver.expression_rewrite_experiment.subprocess.run"
    ) as compile_page:
        generate_preview(record, data(), tmp_path, "site/previews/test.html")
    snapshot = json.loads((tmp_path / "explanation-snapshot.json").read_text())
    lesson = json.loads((tmp_path / "lesson-ir.json").read_text())
    visual = json.loads((tmp_path / "visual-spec.json").read_text())
    assert snapshot["answers"] == {}
    assert "$problem" not in json.dumps(snapshot)
    assert lesson["steps"][0]["trace_refs"] == [
        snapshot["teaching_trace"][0]["trace_id"]
    ]
    assert len(visual["beats"]) == 4
    compile_page.assert_called_once()


def test_direct_compiler_keeps_candidate_parameters_outside_fact_inputs():
    from types import SimpleNamespace as NS
    from unittest.mock import Mock

    from shuxueshuo_server.solver.runtime.functional_direct_compiler import (
        FunctionalCompileRequest,
        FunctionalDirectCompiler,
    )
    from shuxueshuo_server.solver.runtime.functional_plan_models import (
        FunctionalCallReconciliation,
    )
    from shuxueshuo_server.solver.runtime.models import (
        MethodInvocation,
        StepGoal,
        StepPlan,
    )
    from shuxueshuo_server.solver.runtime.recipe_compiler import ExactCompiledStep

    parameters = data()["call"]["parameters"]
    invocation = MethodInvocation(
        "rewrite_1",
        "organize_expressions",
        "rewrite_1",
        inputs={"expression": "$problem.outputs.target_expression"},
        outputs={},
    )
    plan = StepPlan(
        "rewrite_1",
        StepGoal(
            "organize",
            "organize_expressions",
            "$step.rewrite_1.outputs.result",
            "rewrite_1",
        ),
        "rewrite_1",
        [invocation],
    )
    compiler = Mock()
    compiler.compile.return_value = ExactCompiledStep(plan)
    prepared = NS(
        call_id="rewrite_1",
        reconciliation=FunctionalCallReconciliation(
            "rewrite_1",
            "problem",
            "organize_expressions",
            {},
            (),
            parameters=parameters,
        ),
        macro_method_inputs=(),
        macro_role_overrides={},
    )
    request = FunctionalCompileRequest(
        prepared,
        NS(
            capability_id="organize_expressions",
            goal_type="organize_expressions",
            source=NS(method_id="organize_expressions"),
        ),
        "rewrite_1",
        (),
        (),
        (),
        (),
        (),
        (),
    )
    compiled = FunctionalDirectCompiler(capability_compiler=compiler).compile(
        request,
        None,
        inputs=NS(family_spec=None, method_specs=None, question_goals=()),
        handle_registry=None,
    )
    assert compiled.plan.invocations[0].parameters == parameters
    assert "steps" not in compiled.plan.invocations[0].inputs
    assert compiled.plan.invocations[0].parameters is not parameters


@pytest.mark.parametrize("source", ["(9^12)^12", "(a+b)^12", "a^(2+1)"])
def test_expression_expansion_budget(source):
    with pytest.raises(RewriteError):
        parse_expression(source, SympyKernel().symbols(["a", "b"]))


def test_irrelevant_using_does_not_invent_substitution():
    d = data()
    d["expression"] = "a+b"
    d["call"]["parameters"]["steps"] = [
        {"math": "a+b"},
        {"math": "b+a", "using": ["a*b=1"]},
    ]
    assert (
        run(d).trace_fragments[0]["transitions"][0]["operation"] == "equivalent_rewrite"
    )
