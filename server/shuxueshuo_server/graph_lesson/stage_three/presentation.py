"""Freeze readable mathematical fragments at explicit contract boundaries."""

from copy import deepcopy

import sympy as sp

from ...problem_understanding.identity import revision
from .discriminant_display import constant_true_condition
from .execution_contracts import read
from .math_values import latex, math_value
from .presentation_templates import (
    prepare_values,
    render_case_prefix,
    render_highlight,
    render_template,
    render_title,
)
from .presentation_templates import validate_registry as _validate_registry
from .revision_manifest import math_step_hash, revision_ref
from .trajectory import decode_value, encode_value

SEED_CONTRACT = "graph-interaction-seed/v1"
# Per-cell certificates are proof internals; seeds keep the case-level results.
_SEED_OMITTED = frozenset({"cells"})


def validate_registry(registry=None):
    return _validate_registry(read("presentation-registry") if registry is None else registry)


def omit_unchanged_unit(unit, bindings):
    """Hide an opted-in identity transformation, retaining its execution trace.

    Structural equality is deliberate: algebraically equivalent but differently
    written relations still need a visible transformation step.
    """
    specification = read("presentation-registry")["templates"][unit["template"]]
    before, after = bindings.get("before"), bindings.get("after")
    return (specification.get("omit_if_unchanged") is True
            and isinstance(before, (list, tuple)) and bool(before)
            and isinstance(after, (list, tuple)) and len(before) == len(after)
            and all(left == right for left, right in zip(before, after)))


def _seed_values(value):
    if isinstance(value, dict):
        return {key: _seed_values(item) for key, item in value.items() if key not in _SEED_OMITTED}
    if isinstance(value, (list, tuple)):
        return [_seed_values(item) for item in value]
    return value


def record_seed(state, fragment, *, template, values, frame_bindings=None):
    """Freeze already checked exact inputs for the interaction compiler.

    Selection and encoding only: no new mathematics. The route's visible
    constraint context is copied verbatim so witnesses can respect the known
    conditions. A seed that cannot be encoded is recorded as missing so the
    card still counts for repetition.

    Submethod frames pass their live bindings so nested methods (e.g. discriminant
    under domain-parameter) keep domain/quantifier/x/parameter in the seed context
    instead of the parent's sparse top-level inputs.
    """
    seed = {
        "contract": SEED_CONTRACT,
        **{key: state[key] for key in ("run_id", "lesson_version", "target_ref", "route_id")},
        **{key: deepcopy(fragment[key]) for key in (
            "step_id", "math_step_sha256", "ordinal", "display_unit", "method_ref", "case_path")},
        "template": template,
    }
    for key in ("branch_id", "branch_condition", 'option_context'):
        if key in fragment:
            seed[key] = deepcopy(fragment[key])
    try:
        source = frame_bindings if frame_bindings is not None else decode_value(state.get("input_values", {}))
        context = {key: value for key, value in source.items()
                   if isinstance(value, (sp.Basic, str))}
        seed.update(status="ready", values=encode_value(_seed_values(values)), context=encode_value(context),
                    constraint_context=deepcopy(state.get("trajectory", {}).get("constraint_context")))
    except (TypeError, ValueError) as exc:
        seed.update(status="missing", reason="seed_encode_failed", diagnostic=str(exc)[:200])
    state.setdefault("interaction_seeds", []).append(seed)
    return seed


def make_fragment(
    state,
    *,
    unit_id,
    method_ref,
    template,
    before=(),
    after=(),
    source_refs=(),
    used_basis=(),
    explanation=None,
    case_path=(),
    case_condition=None,
    branch_id=None,
    branch_condition=None,
    premise_refs=(),
    highlight=None,
    title=None,
    option_context=None,
):
    settings = read("presentation-registry")["templates"][template]
    ordinal = len(state["fragments"]) + 1
    target_key = revision(state["target_ref"])[:10]
    value = {
        "contract": "graph-math-step/v2",
        "lesson_version": state["lesson_version"],
        "run_id": state["run_id"],
        "target_ref": state["target_ref"],
        "route_id": state["route_id"],
        "step_id": f"{target_key}-{state['route_id']}-{ordinal:03d}-{unit_id}",
        "ordinal": ordinal,
        "method_ref": method_ref,
        "source_refs": list(source_refs),
        "case_path": list(case_path),
        "title": title or settings["title"],
        "before": [math_value(v) for v in before],
        "after": [math_value(v) for v in after],
        "explanation": explanation or settings["explanation"],
        "premise_refs": sorted(set(premise_refs)),
        "used_basis": sorted(set(used_basis)),
        "local_check": "passed",
        "revisions_ref": revision_ref(state),
        "display_unit": unit_id,
    }
    if highlight:
        value["highlight"] = highlight
    if case_condition is not None:
        value["case_condition"] = math_value(case_condition)
    if branch_id is not None:
        value["branch_id"] = branch_id
    if branch_condition is not None:
        value["branch_condition"] = math_value(branch_condition)
    if option_context is not None:
        value['option_context'] = deepcopy(option_context)
    # Conclusion lives elsewhere (e.g. case pictures); the card only carries the derivation.
    if settings.get("derivation") is True:
        value["derivation"] = True
    value["math_step_sha256"] = math_step_hash(value)
    return value


def render_unit(state, frame, step, unit, bindings, source_refs, used_basis, premise_refs=()):
    """Return the card and the exact values its interaction seed may use."""
    registry = read("presentation-registry")
    case_path = frame.get("case_path", [])
    specification = registry["templates"][unit["template"]]
    values = prepare_values(specification, bindings, has_case=bool(case_path))
    before, after, explanation = render_template(specification, bindings, has_case=bool(case_path))
    highlight = render_highlight(specification, bindings, has_case=bool(case_path))
    case = decode_value(frame["bindings"]).get("case") if case_path else None
    if case and isinstance(case.get("condition"), sp.Basic) and specification.get("case_prefix", True):
        explanation = render_case_prefix(registry, case["condition"]) + explanation
    if case:
        values["case"] = case
    branch = bindings.get("branch")
    if branch:
        # Opening scope is presentation metadata, not an execution case path.
        # Keep the exact branch domain for checked interaction answers.
        values["case"] = {"condition": branch["condition"], "domain": branch["domain"], "kind": "opening"}
    # A multi-step source scope adds evidence without changing the card's own
    # method step. The legacy single-step scope explicitly re-anchors it.
    method_step = unit.get("source_scope", {}).get("step", step["id"])
    option_context = deepcopy(frame.get('option_context'))
    if option_context:
        # Domain (+ correspondence when same-domain) stay evidence; a separate
        # verdict card always closes the option workspace.
        option_context['phase'] = (
            'verdict' if unit['template'] == 'equality_verdict' else 'evidence')
    fragment = make_fragment(
        state, unit_id=unit["id"], method_ref=frame["method"] + "#" + method_step,
        template=unit["template"], before=before, after=after, source_refs=source_refs,
        used_basis=used_basis, explanation=explanation, case_path=case_path, premise_refs=premise_refs,
        case_condition=case.get("condition") if case else None,
        branch_id=branch["id"] if branch else None,
        branch_condition=(branch["condition"] if branch and not
                          constant_true_condition(branch["condition"]) else None),
        highlight=highlight,
        title=render_title(specification, bindings, has_case=bool(case_path)),
        option_context=option_context,
    )
    return fragment, values


def _parameter(state):
    """The route's parameter symbol for the closing cards, or None when the method has none."""
    parameter = decode_value(state.get("input_values", {})).get("parameter")
    return parameter if isinstance(parameter, sp.Symbol) else None


def append_boundary(state, evidence, *, feasible_set=None):
    """Add a separate fragment only after the caller's independent boundary checks."""
    updated = deepcopy(state)
    checks = evidence.get(
        "points", evidence.get("checks", evidence.get("boundaries", []))
    )
    if evidence.get("status") not in ("verified", "passed", "ok"):
        raise ValueError("presentation.boundary_unverified")
    operation = {
        "capability": "endpoint_check",
        "public_ref": None,
        "outputs": deepcopy(evidence),
        "operations": ["endpoint_check"],
        "used_basis": ["function-range-extrema#attainability"],
        "postconditions": [{"kind": "independent_boundary", "passed": True}],
    }
    records = updated.setdefault(
        "finalization", deepcopy(updated["trajectory"]["finalization"])
    )
    index = len(records)
    records.append(operation)
    updated["trajectory"]["finalization"] = deepcopy(records)
    goal_kind = updated["trajectory"].get("constraint_context", {}).get("goal", {}).get("kind")
    if 'range_goal' in updated['trajectory'].get('constraint_context', {}):
        # The image card already displays endpoint attainment. Keep independent
        # evidence here without adding a duplicate parameter-boundary lesson.
        return updated
    if goal_kind == "find_domain":
        operation["used_basis"] = ["function-concept#elements", "interval-notation#finite"]
        records[index] = deepcopy(operation)
        updated["trajectory"]["finalization"] = deepcopy(records)
        from .domain_presentation import append_verified_intersection
        return append_verified_intersection(updated, feasible_set, evidence, index)
    if goal_kind == "match_domain":
        # Parameter-range closure keeps endpoint evidence in finalization only;
        # nested discriminant cards already cover the interactive teaching path.
        operation["used_basis"] = ["function-concept#elements", "quantifiers#universal"]
        records[index] = deepcopy(operation)
        updated["trajectory"]["finalization"] = deepcopy(records)
        return updated
    boundary_variable = _parameter(updated)
    if goal_kind == "find_abstract_domain":
        description = updated["trajectory"]["constraint_context"]["abstract_domain_goal"]
        boundary_variable = sp.Symbol(description["variable"], real=True)
        operation["used_basis"] = ["function-concept#composite-domain", "interval-notation#finite"]
        records[index] = deepcopy(operation)
        updated["trajectory"]["finalization"] = deepcopy(records)
    if goal_kind == "find_abstract_domain_parameter":
        description = updated["trajectory"]["constraint_context"]["abstract_domain_parameter_goal"]
        boundary_variable = sp.Symbol(description["parameter"], real=True)
        operation["used_basis"] = ["function-concept#composite-domain", "quantifiers#existential"]
        records[index] = deepcopy(operation)
        updated["trajectory"]["finalization"] = deepcopy(records)
    specification = read("presentation-registry")["templates"]["boundary"]
    bindings = {"before": [], "after": [], "checks": checks, "parameter": boundary_variable,
                "feasible": feasible_set}
    _, _, description = render_template(specification, bindings)
    fragment = make_fragment(
        updated,
        unit_id="boundary",
        method_ref=updated["method"]
        + "#"
        + read("presentation-registry")["boundary_steps"][updated["method"]],
        template="boundary",
        after=([feasible_set] if feasible_set is not None else []),
        source_refs=[f"/finalization/{index}"],
        used_basis=operation["used_basis"],
        explanation=description,
        highlight=render_highlight(specification, bindings),
    )
    updated["fragments"].append(fragment)
    updated["trajectory"]["math_steps"].append(
        {
            "step_id": fragment["step_id"],
            "math_step_sha256": fragment["math_step_sha256"],
            "source_refs": fragment["source_refs"],
            "file": f"math-steps/{updated['route_id']}/{fragment['step_id']}.json",
        }
    )
    points = {sp.sstr(point): point for point in getattr(
        feasible_set.boundary if isinstance(feasible_set, sp.Set) else sp.S.EmptySet, "args", ())}
    seed_values = {
        "feasible_set": feasible_set,
        "checks": [{"point": points.get(row.get("point", {}).get("expression")),
                    "included": row.get("included"), "holds": row.get("holds")} for row in checks],
    }
    if goal_kind in ("find_abstract_domain", "find_abstract_domain_parameter"):
        seed_values["boundary_variable"] = boundary_variable
    record_seed(updated, fragment, template="boundary", values=seed_values)
    return updated


def _goal_math(value, *, set_value=False):
    """Decode an already certified value; do not solve for its bound here."""
    if not isinstance(value, dict) or "exact" not in value:
        raise ValueError("presentation.goal_exact_value_required")
    decoded = decode_value(value["exact"])
    if not isinstance(decoded, sp.Set if set_value else sp.Expr):
        raise TypeError("presentation.goal_math_type")
    if value.get("expression") != sp.sstr(decoded) or value.get("latex") != latex(decoded):
        raise ValueError("presentation.goal_display_mismatch")
    return decoded


def append_goal_finalization(state, answer, evidence):
    """Append a checked goal conclusion without recomputing extrema.

    Range closure retains its existing record and adds no card. Extremum closure
    requires the independent boundary card first and uses only the supplied exact
    bound, membership evidence and typed answer.
    """
    updated = deepcopy(state)
    records = updated.setdefault("finalization", deepcopy(updated["trajectory"]["finalization"]))
    kind = answer.get("kind")
    if kind in ("find_range", "find_domain", "match_domain", "find_abstract_domain", "find_abstract_domain_parameter"):
        if answer.get("status") != "set":
            raise ValueError("presentation.goal_answer_invalid")
        records.append({"capability": "finalize_goal", "answer": deepcopy(answer)})
        updated["trajectory"]["finalization"] = deepcopy(records)
        return updated
    if kind not in ("find_minimum", "find_maximum"):
        raise ValueError("presentation.goal_kind_unsupported")
    status = answer.get("status")
    minimum = kind == "find_minimum"
    direction = "lower" if minimum else "upper"
    unbounded = "unbounded_below" if minimum else "unbounded_above"
    checks = evidence.get("checks") if isinstance(evidence, dict) else None
    if (
        not checks or not all(check.get("passed") is True for check in checks)
        or evidence.get("kind") != "goal_closure" or evidence.get("goal_kind") != kind
        or evidence.get("status") != status or evidence.get("direction") != direction
        or status not in ("attained", "not_attained", unbounded, "empty_feasible_set")
    ):
        raise ValueError("presentation.goal_evidence_unverified")
    fragments = updated["fragments"]
    if (not fragments or fragments[-1]["display_unit"] != "boundary"
            or updated.get("verification", {}).get("status") != "verified"):
        raise ValueError("presentation.goal_independent_boundary_required")
    boundary_sources = {f"/finalization/{index}" for index, record in enumerate(records)
                        if record.get("capability") == "endpoint_check"
                        and record.get("postconditions")
                        and all(check.get("passed") is True for check in record["postconditions"])}
    if not boundary_sources.intersection(fragments[-1]["source_refs"]):
        raise ValueError("presentation.goal_independent_boundary_required")
    feasible = _goal_math(evidence.get("feasible_set"), set_value=True)
    if evidence["feasible_set"]["exact"] != updated.get("feasible_set_exact"):
        raise ValueError("presentation.goal_feasible_set_mismatch")
    if any(record.get("capability") == "finalize_goal" for record in records):
        raise ValueError("presentation.goal_already_finalized")
    after, displayed, bound = [], None, None
    if status == "empty_feasible_set":
        valid = (evidence.get("empty") is True and feasible is sp.S.EmptySet
                 and all(evidence.get(key) is None for key in ("bounded", "bound", "member", "attained"))
                 and "value" not in answer and "bound" not in answer)
    elif status == unbounded:
        bound = _goal_math(evidence.get("bound"))
        valid = (evidence.get("empty") is False and evidence.get("bounded") is False
                 and evidence.get("member") is False and evidence.get("attained") is False
                 and bound is (-sp.oo if minimum else sp.oo)
                 and "value" not in answer and "bound" not in answer)
    else:
        attained = status == "attained"
        displayed = answer.get("value" if attained else "bound")
        bound = _goal_math(displayed)
        valid = (evidence.get("empty") is False and evidence.get("bounded") is True
                 and evidence.get("member") is attained and evidence.get("attained") is attained
                 and displayed == evidence.get("bound") and not bound.free_symbols
                 and bound.is_real is True and bound.is_finite is True)
        after.append(bound)
    if not valid:
        raise ValueError("presentation.goal_answer_evidence_mismatch")
    template = "goal_minimum" if minimum else "goal_maximum"
    specification = read("presentation-registry")["templates"][template]
    bindings = {"before": [feasible], "after": after, "status": status, "bound": bound,
                "parameter": _parameter(updated), "feasible": feasible}
    _, _, explanation = render_template(specification, bindings)
    used_basis = ["function-range-extrema#attainability"]
    operation = {
        "capability": "finalize_goal", "public_ref": None,
        "answer": deepcopy(answer), "outputs": {"answer": deepcopy(answer), "evidence": deepcopy(evidence)},
        "operations": ["goal_finalization"], "used_basis": used_basis,
        "postconditions": [*deepcopy(checks), {"kind": "goal_answer_evidence_match", "passed": True}],
    }
    index = len(records)
    records.append(operation)
    updated["trajectory"]["finalization"] = deepcopy(records)
    fragment = make_fragment(
        updated, unit_id="goal_finalization",
        method_ref=updated["method"] + "#" + read("presentation-registry")["boundary_steps"][updated["method"]],
        template="goal_minimum" if minimum else "goal_maximum", before=[feasible], after=after,
        source_refs=[f"/finalization/{index}"], used_basis=used_basis, explanation=explanation,
        highlight=render_highlight(specification, bindings),
    )
    fragment["before"][0]["exact"] = deepcopy(evidence["feasible_set"]["exact"])
    if displayed is not None:
        fragment["after"][0]["exact"] = deepcopy(displayed["exact"])
    fragment["math_step_sha256"] = math_step_hash(fragment)
    fragments.append(fragment)
    updated["trajectory"]["math_steps"].append({
        "step_id": fragment["step_id"], "math_step_sha256": fragment["math_step_sha256"],
        "source_refs": fragment["source_refs"],
        "file": f"math-steps/{updated['route_id']}/{fragment['step_id']}.json",
    })
    record_seed(updated, fragment, template=template, values={
        "goal_kind": kind, "status": status, "bound": bound, "feasible_set": feasible,
        "attained": status == "attained",
    })
    return updated
