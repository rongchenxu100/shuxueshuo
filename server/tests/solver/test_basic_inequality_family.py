"""Stage 0.5 declarations must never grant runtime execution authority."""

from dataclasses import replace
import json

import pytest

from shuxueshuo_server.solver.contracts import MethodSpec
from shuxueshuo_server.solver.extraction.problem_domain import problem_domain_schema
from shuxueshuo_server.solver.family import (
    BASIC_INEQUALITY_FAMILY,
    DEFAULT_CAPABILITY_PACK_REGISTRY,
    DEFAULT_FAMILY_REGISTRY,
    FamilyMatchRule,
    FamilyRegistry,
    RecipeExecutionSpec,
    SolverFamilySpec,
    expand_family_spec,
)
from shuxueshuo_server.solver.problem_models import ProblemIR
from shuxueshuo_server.solver.runtime.capability_contracts import (
    contract_is_prompt_executable,
    effective_contract_by_id,
)
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.function_specs import FunctionSpecRegistry
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.macro_specs import MacroSpecRegistry
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.strategy_payload import (
    _basic_inequality_strategy_reference,
)


METHOD_IDS = (
    "organize_expressions",
    "introduce_semantic_substitution",
    "eliminate_by_constraint",
    "reduce_symmetric_sum_product",
    "apply_two_term_amgm",
    "bound_univariate_quadratic",
    "close_equality_and_restore",
    "solve_univariate_inequality",
)
RECIPE_IDS = (
    "basic_inequality_substitute_reduce",
    "basic_inequality_bound_and_restore",
    "basic_inequality_univariate_range",
)
RULE_IDS = (
    "basic_inequality.expression_chain",
    "basic_inequality.bound_application",
    "basic_inequality.equality_restore",
)


def _problem(**changes):
    return replace(
        ProblemIR(
            problem_id="synthetic-family-contract",
            pattern="basic-inequality",
            problem_type="basic_inequality",
            symbols=["a", "b"],
        ),
        **changes,
    )


def test_family_declaration_has_source_guidance_and_reserved_metadata():
    family = BASIC_INEQUALITY_FAMILY
    assert family.family_id == "basic_inequality"
    assert family.match.patterns == ("basic-inequality",)
    assert family.match.problem_types == ("basic_inequality",)
    assert family.common_goal_types == (
        "derive_maximum_value", "derive_minimum_value", "derive_range", "derive_parameter",
    )
    assert family.method_ids == METHOD_IDS
    assert tuple(recipe.recipe_id for recipe in family.step_recipes) == RECIPE_IDS
    assert family.explanation_rule_ids == RULE_IDS
    assert len(set(RECIPE_IDS)) == len(RECIPE_IDS)
    assert all(recipe_id.startswith("basic_inequality_") for recipe_id in RECIPE_IDS)
    assert family.strategy_principles == ()
    assert family.method_binding_rules == ()
    assert family.runtime_preflights == ()
    assert family.source_goal_contracts == ()  # No unimplemented selector promises.
    for recipe in family.step_recipes:
        assert recipe.execution is None
        assert recipe.title and recipe.description and recipe.do_not_use_when
        assert set(recipe.method_ids) <= set(METHOD_IDS)

    guidance = family.authoring_guidance_payload()
    assert guidance["title"] and guidance["description"] and guidance["use_when"]
    assert guidance["do_not_use_when"]
    assert guidance["explanation_rule_ids"] == list(RULE_IDS)
    requirements = family.required_source_requirements
    assert [(r.primitive_kind, r.primitive_types, r.min_count) for r in requirements] == [
        ("entity_type", ("symbol",), 1),
        ("fact_type", ("equation", "symbol_constraint"), 1),
    ]
    assert guidance["required_source_primitives"] == [r.to_payload() for r in requirements]

    expanded = expand_family_spec(family, DEFAULT_CAPABILITY_PACK_REGISTRY)
    assert expanded == family
    payload = family.to_payload()
    assert payload["explanation_rule_ids"] == list(RULE_IDS)
    assert json.loads(json.dumps(payload))["method_ids"] == list(METHOD_IDS)
    payload["explanation_rule_ids"].clear()
    assert family.explanation_rule_ids == RULE_IDS


@pytest.mark.parametrize("rule_ids", [
    ("",), (" ",), ("other.expression_chain",), ("basic_inequality.",),
    ("basic_inequality. expression_chain",), (RULE_IDS[0], RULE_IDS[0]),
])
def test_invalid_explanation_rule_references_fail_at_declaration(rule_ids):
    with pytest.raises(ValueError, match="family explanation rule IDs"):
        replace(BASIC_INEQUALITY_FAMILY, explanation_rule_ids=rule_ids)


def test_explanation_rule_namespace_is_owned_by_each_family():
    quadratic = SolverFamilySpec(
        family_id="quadratic_path_minimum",
        match=FamilyMatchRule(),
        explanation_rule_ids=("quadratic_path_minimum.strategy",),
    )
    assert quadratic.explanation_rule_ids == ("quadratic_path_minimum.strategy",)
    with pytest.raises(ValueError, match=r"quadratic_path_minimum\.\* IDs"):
        replace(
            quadratic,
            explanation_rule_ids=("basic_inequality.expression_chain",),
        )


def test_all_pack_contracts_are_explicit_catalog_only_including_existing_m01():
    family = BASIC_INEQUALITY_FAMILY
    pack = DEFAULT_CAPABILITY_PACK_REGISTRY.require("basic_inequality_core")
    assert family.mechanism_packs == (pack.pack_id,)
    assert pack.method_ids == METHOD_IDS
    assert pack.method_binding_rules == ()
    methods = MethodSpecRegistry.load_from_code()
    methods.require("organize_expressions")
    contracts = effective_contract_by_id(family, methods)
    assert tuple(contracts) == (*METHOD_IDS, *RECIPE_IDS)
    for capability_id, contract in contracts.items():
        assert contract.kind == ("method" if capability_id in METHOD_IDS else "recipe")
        assert contract.source == "explicit"
        assert contract.execution_status == "catalog_only"
        assert contract.exposes_to_llm is False
        assert contract.is_complete is False
        assert not contract_is_prompt_executable(contract)
        assert not (contract.slot_reads or contract.slot_writes)
        assert not (contract.condition_reads or contract.condition_writes)
    # The shared M01 implementation remains executable for its original pack.
    rewrite = DEFAULT_CAPABILITY_PACK_REGISTRY.require("rational_expression_rewrite")
    assert contract_is_prompt_executable(rewrite.contracts[0])


@pytest.mark.parametrize("all_methods_exist", [False, True])
def test_catalog_only_gate_does_not_depend_on_missing_implementations(all_methods_exist):
    methods = MethodSpecRegistry.load_from_code()
    if all_methods_exist:
        methods = MethodSpecRegistry({
            **methods.specs,
            **{
                method_id: MethodSpec(
                    method_id=method_id, title=method_id,
                    solves=("derive_minimum_value",), inputs={}, outputs={"value": "Expression"},
                )
                for method_id in METHOD_IDS if method_id not in methods.specs
            },
        })
    family = BASIC_INEQUALITY_FAMILY
    functions = FunctionSpecRegistry.from_family_spec(family, methods)
    assert functions.specs == {}
    assert functions.to_prompt_payload()["items"] == []
    assert MacroSpecRegistry.from_family_spec(family, methods).specs == {}
    with pytest.raises(ValueError, match="functional catalog is empty"):
        FunctionalCapabilityCatalog.from_family_spec(family, methods)

    # Even a future execution declaration must not override catalog-only status.
    with_execution = replace(family, step_recipes=tuple(
        replace(recipe, execution=RecipeExecutionSpec(
            recipe_id=recipe.recipe_id, method_sequence=recipe.method_ids,
            execution_mode="direct",
        ))
        for recipe in family.step_recipes
    ))
    assert MacroSpecRegistry.from_family_spec(with_execution, methods).specs == {}
    with pytest.raises(ValueError, match="functional catalog is empty"):
        FunctionalCapabilityCatalog.from_family_spec(with_execution, methods)


def test_structural_matching_is_independent_of_problem_identity_and_labels():
    registry = FamilyRegistry((*DEFAULT_FAMILY_REGISTRY.families, BASIC_INEQUALITY_FAMILY))
    for problem in (
        _problem(), _problem(problem_id="a-new-problem"),
        _problem(data={"family_id": "untrusted-other-label"}),
    ):
        assert registry.match(problem) is BASIC_INEQUALITY_FAMILY


@pytest.mark.parametrize("changes", [
    {"pattern": "unknown"}, {"problem_type": "unknown"},
    {"pattern": "", "problem_type": ""},
])
def test_family_label_cannot_authorize_a_structural_mismatch(changes):
    registry = FamilyRegistry((BASIC_INEQUALITY_FAMILY,))
    assert registry.match(_problem(data={"family_id": "basic_inequality"}, **changes)) is None


def test_ambiguous_family_match_fails_closed():
    registry = FamilyRegistry((
        BASIC_INEQUALITY_FAMILY,
        replace(
            BASIC_INEQUALITY_FAMILY,
            family_id="duplicate",
            explanation_rule_ids=(),
        ),
    ))
    with pytest.raises(ValueError, match="ambiguous solver family match"):
        registry.match(_problem())


def test_production_registry_and_schema_remain_closed():
    assert "basic_inequality" not in {f.family_id for f in DEFAULT_FAMILY_REGISTRY.families}
    assert DEFAULT_FAMILY_REGISTRY.match(_problem()) is None
    assert SolverRuntimeConfig().build_family_registry() is DEFAULT_FAMILY_REGISTRY
    assert "basic_inequality" not in problem_domain_schema()["properties"]["family_id"]["enum"]


def test_planning_reference_is_not_a_capability_or_a_family_execution_field():
    reference = _basic_inequality_strategy_reference()
    assert reference is not None
    assert reference["strategy_overview"]
    assert len(reference["methods"]) == 6
    assert "strategy_principles" not in reference
    catalog_ids = set(METHOD_IDS) | set(RECIPE_IDS)
    for method in reference["methods"]:
        assert method["name"] not in catalog_ids
        assert "capability_id" not in method and "method_id" not in method
    payload = BASIC_INEQUALITY_FAMILY.to_payload()
    assert "strategy_overview" not in payload and "planning_methods" not in payload
