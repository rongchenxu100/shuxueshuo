"""q08 prefix through the production Functional transactional interpreter."""

from shuxueshuo_server.solver.family.expression_rewrite import (
    ORGANIZE_EXPRESSIONS_BINDING,
    ORGANIZE_EXPRESSIONS_CONTRACT,
)
from shuxueshuo_server.solver.family.models import FamilyMatchRule, SolverFamilySpec
from shuxueshuo_server.solver.runtime.context_inventory import ContextInventoryBuilder
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalCall,
    FunctionalPlan,
    FunctionalScope,
)
from shuxueshuo_server.solver.runtime.functional_plan_reconciliation import (
    FunctionalPlanReconciler,
)
from shuxueshuo_server.solver.runtime.functional_transaction_execution import (
    FunctionalTransactionalInterpreter,
)
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.planner import PlannerInputs
from shuxueshuo_server.solver.runtime.planner_state_context import (
    Condition,
    ContextManifest,
    MathObject,
    PlannerState,
    PlannerStateContext,
    ScopeGraph,
    StateSlot,
)
from shuxueshuo_server.solver.runtime.state_identity import (
    LogicalStateKey,
    MathObjectId,
    StateSlotId,
    StateVersionId,
)
from shuxueshuo_server.solver.runtime.strategy_models import SemanticRef


def execute_rewrite_transaction(fixture, call=None):
    from .expression_rewrite_experiment import RewriteExperiment

    host = RewriteExperiment(fixture)
    from shuxueshuo_server.solver.runtime.models import TypedValue

    for name, symbol in host.context.symbols.items():
        host.context.write_path(
            f"$problem.symbols.{name}",
            TypedValue("Symbol", symbol),
            from_scope_id="problem",
        )
    for name in fixture["conditions"]:
        host.context.write_path(
            f"$problem.conditions.{name}",
            host.context.read_path(
                f"$problem.constraints.{name}", from_scope_id="problem"
            ),
            from_scope_id="problem",
        )
    family = SolverFamilySpec(
        "rewrite_prefix_test",
        FamilyMatchRule(),
        method_ids=("organize_expressions",),
        capability_contracts=(ORGANIZE_EXPRESSIONS_CONTRACT,),
        method_binding_rules=(ORGANIZE_EXPRESSIONS_BINDING,),
    )
    registry = CanonicalHandleRegistry(
        frozenset({"problem"}),
        frozenset({"function:problem:T", "symbol:problem:a", "symbol:problem:b"}),
        frozenset(f"fact:problem:{n}" for n in fixture["conditions"]),
        frozenset(),
        scope_parents={"problem": None},
        fact_types={f"fact:problem:{n}": "Condition" for n in fixture["conditions"]},
        entity_payloads={
            "function:problem:T": {"name": "T", "entity_type": "function"},
            **{
                f"symbol:problem:{n}": {"name": n, "entity_type": "symbol"}
                for n in fixture["symbols"]
            },
        },
    )
    inputs = PlannerInputs(
        fixture["problem_id"],
        family,
        [],
        ContextInventoryBuilder().build(host.context, host.specs),
        host.specs,
        host.context.problem,
    )
    object_id = MathObjectId("function:problem:T", "function", "problem")
    logical = LogicalStateKey(object_id, "expression", "Expression")
    slot_id = StateSlotId(logical, "problem")
    state = PlannerState(
        {},
        {"family_id": family.family_id},
        ScopeGraph(("problem",), {"problem": None}),
        math_objects=(
            MathObject(
                object_id.value,
                "function",
                "problem",
                object_id.value,
                ("function:T",),
                "problem",
                math_object_id=object_id,
            ),
            *(
                MathObject(
                    f"symbol:problem:{n}",
                    "symbol",
                    "problem",
                    f"symbol:problem:{n}",
                    (f"symbol:{n}",),
                    "problem",
                    math_object_id=MathObjectId(
                        f"symbol:problem:{n}", "symbol", "problem"
                    ),
                )
                for n in fixture["symbols"]
            ),
        ),
        conditions=tuple(
            Condition(
                f"fact:problem:{n}",
                "Condition",
                "problem",
                f"fact:problem:{n}",
                value_type="Condition",
            )
            for n in fixture["conditions"]
        ),
        state_slots=(
            StateSlot(
                "target_expression",
                object_id.value,
                "expression",
                "problem",
                "Expression",
                canonical_handle=object_id.value,
                aliases=("function:T",),
                runtime_path="$problem.outputs.target_expression",
                status="given",
                logical_state_key=logical,
                typed_slot_id=slot_id,
                latest_version_id=StateVersionId(slot_id, 0),
            ),
        ),
    )
    parent = PlannerStateContext(
        ContextManifest(
            "q08-prefix",
            "initial",
            "1",
            None,
            (),
            fixture["problem_id"],
            family.family_id,
            "fixture",
            "fixture",
        ),
        state,
    )
    authored = call or fixture["call"]
    if (
        set(authored) != {"step_id", "capability_id", "args", "parameters"}
        or authored["capability_id"] != "organize_expressions"
    ):
        raise ValueError("调用协议不匹配")
    if authored["args"].get("expression") != "target_expression" or set(
        authored["args"]
    ) != {"expression", "conditions"}:
        raise ValueError("表达式绑定不匹配")
    names = authored["args"]["conditions"]
    if (
        not isinstance(names, list)
        or len(set(names)) != len(names)
        or any(n not in fixture["conditions"] for n in names)
    ):
        raise ValueError("条件绑定不存在或重复")
    functional = FunctionalCall(
        authored["step_id"],
        "organize_expressions",
        {
            "expression": (SemanticRef("T", "fact", "Expression"),),
            "conditions": tuple(
                SemanticRef(n, "fact", "Condition")
                for n in authored["args"]["conditions"]
            ),
        },
        {},
        "",
        "",
        parameters=authored["parameters"],
    )
    plan = FunctionalPlan((FunctionalScope("problem", "整理前缀", (functional,)),))
    reconciliation = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=parent,
        family_spec=family,
        method_specs=host.specs,
        handle_registry=registry,
        question_goals=[],
        pinned_canonical_call_ids=(functional.call_id,),
        allow_incomplete_goals=True,
    )
    if reconciliation.issues:
        raise ValueError([i.to_payload() for i in reconciliation.issues])
    report = FunctionalTransactionalInterpreter().execute(
        raw_plan=plan,
        reconciliation=reconciliation,
        runtime_context=host.context,
        parent_context=parent,
        inputs=inputs,
        handle_registry=registry,
    )
    return report
