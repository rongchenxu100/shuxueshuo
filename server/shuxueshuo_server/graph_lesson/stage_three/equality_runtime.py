"""Scoped M8 operations and typed completion, shared by photo and topic routes."""

from copy import deepcopy

from ..function_equality import (
    compare_pair,
    domain_context,
    structural_inspect,
    verify_pair,
)
from .capabilities import CapabilityGap, LocalCheckFailed
from .trajectory import decode_value, encode_value


def admitted(context):
    goal = context.get("comparison_goal") or {}
    options = goal.get("options") or []
    return (context.get("goal", {}).get("kind") == "compare_functions"
            and goal.get("structure_supported") is True and bool(options)
            and all(structural_inspect(option[side])["structure_supported"]
                    for option in options for side in ("left", "right")))


def _result(outputs, operation):
    return {"outputs": outputs, "operations": [operation],
            "checks": [{"kind": operation, "passed": True}]}


def prepare_function_comparisons(context):
    if not admitted(context):
        raise CapabilityGap("function_equality.input_class_unavailable")
    goal = deepcopy(context["comparison_goal"])
    return _result({"options": goal["options"], "comparison_goal": goal}, "function_comparison_scope")


# Families whose natural domain is all reals for the admitted M8 input class.
_TRIVIAL_DOMAIN_FAMILIES = frozenset({
    "polynomial", "absolute_affine", "square_root_square",
})


def prepare_function_pair(option, comparison_goal):
    contexts = {}
    trivial = []
    for side in ("left", "right"):
        descriptor = option[side]
        context = domain_context(descriptor, natural=True)
        context["target_ref"] = comparison_goal["target_ref"]
        family = structural_inspect(descriptor)["family"]
        side_trivial = family in _TRIVIAL_DOMAIN_FAMILIES
        trivial.append(side_trivial)
        context["domain_trivial"] = side_trivial
        # M8 teaching surface defaults to fold/light: always run M1 for the
        # certificate, never project its step-by-step student cards.
        context["suppress_domain_display"] = True
        contexts[side + "_context"] = context
    density = "fold" if all(trivial) else "light"
    return _result({**contexts, "option": deepcopy(option),
                    "needs_borrow": False, "domain_density": density},
                   "function_comparison_scope")


def compare_function_pair(option, left_domain, right_domain):
    comparison = compare_pair(option["left"], option["right"])
    if comparison["relation"] == "unresolved":
        raise CapabilityGap(comparison["reason"])
    if (comparison["left"]["natural_domain"] != left_domain
            or comparison["right"]["natural_domain"] != right_domain):
        raise LocalCheckFailed("function_equality.child_domain_mismatch")
    verification = verify_pair(option["left"], option["right"], comparison)
    if verification["status"] != "verified":
        raise LocalCheckFailed("function_equality.pair_verification_failed")
    same = comparison["left"]["domain"] == comparison["right"]["domain"]
    # Domains / correspondence evidence stay separate; only same-domain
    # correspondence doubles as the item-closing verdict.
    result = _result({"comparison": comparison, "same_domain": same, "merge_verdict": False},
                     "function_identity_comparison")
    rules = {cell[side]['rule'] for cell in comparison['proof'].get('cells', [])
             for side in ('left_rule', 'right_rule')}
    result['operations'].extend(sorted(rules & {'absolute_value_on_sign_cell', 'square_of_real_square_root'}))
    return result


def collect_function_comparisons(comparison_goal, comparisons):
    options = comparison_goal["options"]
    if len(comparisons) != len(options):
        raise LocalCheckFailed("function_equality.incomplete_options")
    rows = []
    for option, row in zip(options, comparisons, strict=True):
        if row["option_id"] != option["option_id"]:
            raise LocalCheckFailed("function_equality.option_binding_mismatch")
        rows.append({"option_id": option["option_id"], "label": option["label"],
                     "result": decode_value(encode_value(row["outputs"]["comparison"]))})
    result = {"kind": "compare_functions", "target_ref": comparison_goal["target_ref"],
              "mode": comparison_goal["mode"], "selection_mode": comparison_goal["selection_mode"],
              "select_relation": comparison_goal["select_relation"], "options": rows}
    result["correct_labels"] = [row["label"] for row in rows
                                if row["result"]["relation"] == result["select_relation"]]
    return _result({"comparison_result": result}, "function_comparison_collection")


def verify_result(context, result):
    goal = context["comparison_goal"]
    expected_keys = {"kind", "target_ref", "mode", "selection_mode", "select_relation", "options", "correct_labels"}
    if (set(result) != expected_keys or result["kind"] != "compare_functions"
            or any(result[key] != goal[key] for key in ("target_ref", "mode", "selection_mode", "select_relation"))
            or len(result["options"]) != len(goal["options"])):
        return {"status": "math_failed", "diagnostics": [{"code": "function_equality.result_binding_mismatch"}]}
    evidence = []
    for option, row in zip(goal["options"], result["options"], strict=True):
        if set(row) != {"option_id", "label", "result"} or any(row[key] != option[key] for key in ("option_id", "label")):
            return {"status": "math_failed", "diagnostics": [{"code": "function_equality.option_binding_mismatch"}]}
        verified = verify_pair(option["left"], option["right"], row["result"])
        if verified["status"] != "verified":
            return verified
        evidence.append({"option_id": option["option_id"], **verified})
    expected = [row["label"] for row in result["options"] if row["result"]["relation"] == goal["select_relation"]]
    if result["correct_labels"] != expected:
        return {"status": "math_failed", "diagnostics": [{"code": "function_equality.label_polarity_mismatch"}]}
    return {"status": "verified", "diagnostics": [], "options": evidence}


def answer_for(result):
    return {"kind": "compare_functions", "status": "complete", "mode": result["mode"],
            "selection_mode": result["selection_mode"], "select_relation": result["select_relation"],
            "correct_labels": list(result["correct_labels"]), "option_verdicts": [
                {"option_id": row["option_id"], "label": row["label"],
                 "verdict": row["result"]["relation"], "reason": row["result"]["reason"]}
                for row in result["options"]]}


def original_choice(context, answer):
    goal = context["comparison_goal"]
    if goal["selection_mode"] == "none":
        return None
    return {"status": "matched", "kind": "multiple_choice" if goal["selection_mode"] == "multiple" else "single_choice",
            "selection_mode": goal["selection_mode"], "target_ref": goal["target_ref"],
            "select_relation": goal["select_relation"],
            "options": [{key: option[key] for key in ("option_id", "label", "text")} for option in goal["options"]],
            "correct_labels": list(answer["correct_labels"]), "option_verdicts": deepcopy(answer["option_verdicts"])}


def verify_frozen(candidate, target_ref, context, encoded_result):
    from .context import build_context

    current = build_context(candidate, target_ref)
    if current != context:
        raise LocalCheckFailed("function_equality.original_context_mismatch")
    return verify_result(current, decode_value(encoded_result))


def finish(state, previous):
    result = decode_value(state["comparison_result_exact"])
    answer = answer_for(result)
    consistency = "consistent"
    for route in previous:
        if route["status"] == "verified" and route.get("answer") != answer:
            consistency = "conflict"
    return {"state": deepcopy(state), "answer": answer,
            "comparison_result_exact": encode_value(result), "consistency": consistency}
