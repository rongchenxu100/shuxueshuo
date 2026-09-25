"""Verified bounds and finite extremum witnesses; no runtime or fixture access."""

from copy import deepcopy
from dataclasses import replace

import sympy as sp

from .derivation_math import parse_derivation
from .expression_parser import (
    MathParseError,
    parse_math_expression,
    parse_math_relation,
)
from .proof_algebra import (
    Arithmetic,
    ProofFailure,
    commutative_key,
    digest,
    from_node,
    names,
)
from .proof_kernel import (
    ProofContext,
    _Budget,
    prove_relation,
    replay_proof,
    verify_relation_sequence,
    verify_witnesses,
)


def require(result):
    if result.status != "proved":
        raise ProofFailure(result.code, result.diagnostic or "proof missing")
    return result.proof


def target_context(target):
    if target.get("type") != "extremum_target" or target.get("goal_kind") not in {
        "find_maximum",
        "find_minimum",
    }:
        raise ProofFailure(
            "unsupported_target", "a maximum-expression target is required"
        )
    names = target["scalar_symbols"]
    conditions = target["source_conditions"]
    if (
        not isinstance(names, list)
        or not 1 <= len(names) <= 4
        or len(set(names)) != len(names)
        or not all(isinstance(name, str) for name in names)
    ):
        raise ProofFailure("invalid_input", "unique declared scalar names required")
    if (
        not isinstance(conditions, list)
        or not 1 <= len(conditions) <= 16
        or len({item["handle"] for item in conditions}) != len(conditions)
    ):
        raise ProofFailure("invalid_input", "unique original conditions required")
    symbols = {name: sp.Symbol(name, real=True) for name in names}
    premises = {
        item["handle"]: replace(
            parse_math_relation(item["math"], symbols), source_path=item["source_path"]
        )
        for item in target["source_conditions"]
    }
    context = ProofContext(symbols, premises, scope_id=target["scope_id"])
    expression = parse_math_expression(target["target_math"], symbols)
    return context, expression


def _check_fixed_sum_bound_shape(upper, origin, context):
    """Reject a mismatched Stage 4A constant before general proof search.

    This is a Method contract diagnostic, never a proof or a counterexample:
    other constraints might justify a different bound via another mechanism.
    Successful candidates still pass every existing domain/proof check.
    """
    goal = from_node(upper.ast)
    if goal[0] != "<=":
        return
    arithmetic = Arithmetic(_Budget(context.limits))
    submitted = arithmetic.literal_rational(goal[2])
    if submitted is None:
        return
    expected = set()
    for parsed in context.premises.values():
        premise = from_node(parsed.ast)
        if premise[0] != "=":
            continue
        total, value = premise[1:]
        if total[0] != "add":
            total, value = value, total
        if total[0] != "add":
            continue
        fixed_sum = arithmetic.literal_rational(value)
        if fixed_sum is None:
            continue
        u, v = total[1:]
        if arithmetic.difference(("=", goal[1], ("mul", u, v))):
            continue
        expected.add(arithmetic.check_q(fixed_sum * fixed_sum / 4))
    if expected and submitted not in expected:
        constants = "、".join(str(value) for value in sorted(expected))
        raise ProofFailure(
            "target_bound_mismatch",
            f"steps[{origin['step']}].math：提交的常数上界 {submitted} 与当前 M11 "
            f"定和 AM-GM 模板 (U+V)^2/4 的常数 {constants} 不一致。"
            "请核对定和代入、除法和平方步骤；若依赖其他条件求界，需使用支持该机制的能力。",
        )


def _verify_bound_v1(target, steps):
    if target.get("goal_kind") != "find_maximum":
        raise ProofFailure(
            "target_bound_mismatch", "v1 is a maximum upper-bound contract"
        )
    context, _expression = target_context(target)
    try:
        derivation = parse_derivation(steps, context.symbols)
    except MathParseError as exc:
        raise ProofFailure(
            exc.code, f"steps[{exc.step}].math：{exc}；使用显式 *、sqrt(...)、>=、<="
        ) from exc
    relations = [item.parsed for item in derivation]
    _check_fixed_sum_bound_shape(relations[-1], derivation[-1].origin, context)
    sequence_proofs = verify_relation_sequence(relations, context)
    upper = relations[-1]
    candidates = []
    for relation in relations:
        if relation.ast.op == ">=" and relation.ast.children[0].op == "add":
            result = prove_relation(relation, context)
            if result.status == "proved" and any(
                n["rule_id"] == "math.two_term_amgm" for n in result.proof["nodes"]
            ):
                candidates.append((relation, result.proof))
    # Stage 4A still certifies the final fixed-sum bound from original sources,
    # independently of the now fully checked intermediate derivation.
    q = require(prove_relation(upper, context))
    if not candidates:
        # Mean-square/product forms may omit the standalone radical line.
        # Recover only the actual certified application, never a guessed pair.
        from .inequality_bound_v2 import math_text
        from .proof_algebra import freeze

        for node in q["nodes"]:
            if node["rule_id"] == "math.two_term_amgm":
                relation = parse_math_relation(
                    math_text(freeze(node["conclusion"])), context.symbols
                )
                candidates.append(
                    (relation, require(prove_relation(relation, context)))
                )
    right = upper.ast.children[1]
    bound_value = parse_math_expression(
        upper.source[right.span[0] : right.span[1]], context.symbols
    ).to_sympy(context.symbols)
    if upper.ast.op != "<=" or bound_value.free_symbols:
        raise ProofFailure(
            "target_bound_mismatch", "a constant upper bound is required"
        )
    target_proof = require(
        prove_relation(
            parse_math_relation(
                f"({target['target_math']})=({upper.source[upper.ast.children[0].span[0] : upper.ast.children[0].span[1]]})",
                context.symbols,
            ),
            context,
        )
    )
    if not any(n["rule_id"] == "math.fixed_sum_product_bound" for n in q["nodes"]):
        raise ProofFailure(
            "inequality_template_unmatched", "fixed-sum product bound required"
        )
    matching = [
        (candidate, proof)
        for candidate, proof in candidates
        if any(
            n["rule_id"] == "math.two_term_amgm"
            and commutative_key(n["conclusion"])
            == commutative_key(from_node(candidate.ast))
            for n in q["nodes"]
        )
    ]
    if not matching:
        raise ProofFailure(
            "inequality_template_unmatched",
            "bound must use the submitted AM-GM application",
        )
    amgm, p = matching[0]
    u, v = amgm.ast.children[0].children
    equality = (
        f"({amgm.source[u.span[0] : u.span[1]]})=({amgm.source[v.span[0] : v.span[1]]})"
    )
    return {
        "schema_version": "amgm-bound/v1",
        "target_hash": digest(target),
        "target_math": target["target_math"],
        "steps": deepcopy(steps),
        "proofs": [p, q, target_proof],
        "derivation": {
            "origins": [item.origin for item in derivation],
            "proofs": sequence_proofs,
        },
        "equality": equality,
        "bound": str(bound_value),
    }


def _public_bound_v1(evidence):
    """The typed mathematical Fact; certificates stay in the audit trace."""
    return {
        key: deepcopy(evidence[key])
        for key in ("schema_version", "target_math", "steps", "equality", "bound")
    }


def replay_derivation(steps, evidence, context):
    relations = parse_derivation(steps, context.symbols)
    if set(evidence) != {"origins", "proofs"} or evidence["origins"] != [
        item.origin for item in relations
    ]:
        raise ProofFailure("invalid_proof", "derivation source map changed")
    verify_relation_sequence(
        [item.parsed for item in relations], context, certificates=evidence["proofs"]
    )


def _close_bound_v1(target, bound, steps):
    context, _expression = target_context(target)
    rebuilt = _verify_bound_v1(target, bound["steps"])
    if _public_bound_v1(rebuilt) != bound:
        raise ProofFailure("invalid_proof", "bound evidence altered")
    for proof in rebuilt["proofs"]:
        require(replay_proof(proof, context))
    replay_derivation(bound["steps"], rebuilt["derivation"], context)
    derivation = parse_derivation(steps, context.symbols)
    assignments = {}
    aliases = []
    for item in derivation:
        parsed = item.parsed
        if parsed.ast.op != "=":
            continue
        left, right = parsed.ast.children
        for variable, value in ((left, right), (right, left)):
            if variable.op != "symbol":
                continue
            name = variable.text
            if value.op == "symbol":
                aliases.append((name, value.text))
            elif not names(from_node(value)):
                candidate = parse_math_expression(
                    parsed.source[slice(*value.span)], context.symbols
                )
                # Keep the first submitted value; repeated assignments remain
                # requirements and must agree under exact witness verification.
                # Do not construct SymPy constants ahead of the kernel budgets.
                assignments.setdefault(name, candidate)
    # A chain such as x=y=1 explicitly supplies the same constant to x and y.
    # This bounded alias propagation is not equation solving. All claims are
    # subsequently checked under the complete simultaneous witness.
    for _ in context.symbols:
        for left, right in aliases:
            if left not in assignments and right in assignments:
                assignments[left] = assignments[right]
    if set(assignments) != set(context.symbols):
        raise ProofFailure(
            "witness_assignment_invalid",
            "推导中须给出每个原变量的具体取值，可用 x=y=常数；不搜索缺失取值",
        )
    requirements = [
        parse_math_relation(s, context.symbols)
        for s in (
            bound["equality"],
            f"({target['target_math']})=({bound['bound']})",
        )
    ]
    requirements.extend(item.parsed for item in derivation)
    witness = verify_witnesses([assignments], requirements, context)
    proof = require(witness)
    require(replay_proof(proof, context))
    value = parse_math_expression(bound["bound"], context.symbols).to_sympy(
        context.symbols
    )
    return value, {
        "kind": "verified_extremum",
        "bound": rebuilt,
        "witness_proof": proof,
        "steps": deepcopy(steps),
        "derivation_origins": [item.origin for item in derivation],
        "assignments": {
            name: value.source for name, value in sorted(assignments.items())
        },
        "claim_scope": "submitted_witness",
        "exhaustive": False,
    }


def verify_bound(target, steps, *, expression=None, previous_bound=None):
    from .inequality_bound_v2 import verify

    return verify(target, steps, expression=expression, previous_bound=previous_bound)


def public_bound(evidence):
    if evidence["schema_version"] == "amgm-bound/v1":
        return _public_bound_v1(evidence)
    from .inequality_bound_v2 import public

    return public(evidence)


def close_bound(target, bound, steps=None, *, branches=None, equality_derivation=None):
    if bound["schema_version"] == "amgm-bound/v1":
        if branches is not None or equality_derivation is not None:
            raise ProofFailure("invalid_input", "v1 requires single-branch steps")
        return _close_bound_v1(target, bound, steps)
    from .inequality_bound_v2 import close

    return close(
        target,
        bound,
        [steps] if branches is None else [b["steps"] for b in branches],
        equality_derivation=equality_derivation,
        branch_derivations=(
            [
                {"when": b["when"], "equality_derivation": b["equality_derivation"]}
                for b in branches
            ]
            if branches is not None
            and any("when" in b or "equality_derivation" in b for b in branches)
            else None
        ),
    )
