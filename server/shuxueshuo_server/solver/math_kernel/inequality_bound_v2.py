"""One local AM-GM application with explicit, replayable predecessor bounds."""

from copy import deepcopy
from dataclasses import replace

from .derivation_math import parse_derivation
from .expression_parser import parse_math_expression, parse_math_relation
from .proof_algebra import (
    ProofFailure,
    commutative_key,
    digest,
    freeze,
    from_node,
    names,
)
from .proof_kernel import (
    _Budget,
    _document,
    _replay,
    _run_request,
    replay_proof,
    verify_relation_sequence,
    verify_witnesses,
)


def math_text(node):
    op = node[0]
    if op == "rat":
        return str(node[1]) if str(node[2]) == "1" else f"({node[1]}/{node[2]})"
    if op == "symbol":
        return node[1]
    if op == "sqrt":
        return f"sqrt({math_text(node[1])})"
    if op == "neg":
        return f"-({math_text(node[1])})"
    signs = {"add": "+", "sub": "-", "mul": "*", "div": "/", "pow": "^"}
    return f"({math_text(node[1])}){signs.get(op, op)}({math_text(node[2])})"


def public(evidence):
    return {
        **{
            k: deepcopy(v)
            for k, v in evidence.items()
            if k not in {"proofs", "derivation"}
        },
        "certificate_bundle": {
            k: deepcopy(evidence[k]) for k in ("proofs", "derivation")
        },
    }


def verify(
    target,
    steps,
    *,
    expression=None,
    previous_bound=None,
    depth=0,
    certificates=None,
    budget=None,
):
    from .inequality_evidence import _verify_bound_v1, require, target_context

    if depth > 8:
        raise ProofFailure("proof_limit", "at most eight bound dependencies")
    if expression is not None and previous_bound is not None:
        raise ProofFailure(
            "invalid_input", "expression and previous_bound are mutually exclusive"
        )
    context, _ = target_context(target)
    budget = budget or _Budget(context.limits)
    proof_index = 0

    def certify(parsed, ctx):
        nonlocal proof_index
        request = {"kind": "relation", "candidate": _document(parsed)}
        if certificates is None:
            proof = _run_request(ctx, request, budget=budget).proof
            require(replay_proof(proof, ctx))
        else:
            try:
                proof = certificates["proofs"][proof_index]
            except (KeyError, IndexError, TypeError) as exc:
                raise ProofFailure(
                    "invalid_proof", "missing bound certificate"
                ) from exc
            if proof.get("request") != request:
                raise ProofFailure("invalid_proof", "bound certificate request changed")
            _replay(proof, ctx, budget=budget)
        proof_index += 1
        return proof

    predecessor = None
    source = target["target_math"]
    equalities = []
    dependencies = []
    if previous_bound is not None:
        if not isinstance(previous_bound.get("certificate_bundle"), dict):
            raise ProofFailure(
                "invalid_proof", "missing predecessor certificate bundle"
            )
        if previous_bound.get(
            "schema_version"
        ) != "amgm-bound/v2" or previous_bound.get("target_hash") != digest(target):
            raise ProofFailure(
                "invalid_proof", "bound belongs to another target or version"
            )
        predecessor = verify(
            target,
            previous_bound["steps"],
            expression=previous_bound.get("expression"),
            previous_bound=previous_bound.get("previous_bound"),
            depth=depth + 1,
            certificates=previous_bound.get("certificate_bundle"),
            budget=budget,
        )
        if public(predecessor) != previous_bound:
            raise ProofFailure("invalid_proof", "predecessor bound altered")
        source = predecessor["bound"]
        equalities = list(predecessor["equalities"])
        dependencies = list(predecessor["applications"])
    elif expression is not None:
        source = str(expression)
    direction = "<=" if target["goal_kind"] == "find_maximum" else ">="
    if direction == "<=":
        if previous_bound is not None or expression is not None:
            raise ProofFailure(
                "inequality_template_unmatched",
                "maximum path requires the fixed-sum product template",
            )
        if certificates is None:
            legacy = _verify_bound_v1(target, steps)
        else:
            chain = parse_derivation(steps, context.symbols)
            derivation = certificates["derivation"]
            if derivation["origins"] != [r.origin for r in chain]:
                raise ProofFailure("invalid_proof", "bound origins changed")
            verify_relation_sequence(
                [r.parsed for r in chain],
                context,
                certificates=derivation["proofs"],
                budget=budget,
            )
            supplied = certificates["proofs"]
            if len(supplied) != 3:
                raise ProofFailure(
                    "invalid_proof", "three fixed-sum certificates required"
                )
            for proof in supplied:
                _replay(proof, context, budget=budget)
            if supplied[1]["request"]["candidate"] != _document(chain[-1].parsed):
                raise ProofFailure("invalid_proof", "fixed-sum conclusion changed")
            relation = chain[-1].parsed
            left, right = relation.ast.children
            target_eq = parse_math_relation(
                f"({target['target_math']})=({relation.source[slice(*left.span)]})",
                context.symbols,
            )
            if relation.ast.op != "<=" or supplied[2]["request"][
                "candidate"
            ] != _document(target_eq):
                raise ProofFailure("invalid_proof", "fixed-sum target changed")
            legacy = {
                "target_hash": digest(target),
                "target_math": target["target_math"],
                "steps": deepcopy(steps),
                "proofs": supplied,
                "derivation": derivation,
                "bound": str(
                    parse_math_expression(
                        relation.source[slice(*right.span)], context.symbols
                    ).to_sympy(context.symbols)
                ),
            }

        # v2 derives its public equality from the same certified AM-GM pair
        # during initial verification and replay. Keep v1's source-text evidence
        # unchanged: its stored artifacts still require verbatim comparison.
        pair_nodes = [
            n
            for n in legacy["proofs"][0]["nodes"]
            if n["rule_id"] == "math.two_term_amgm"
        ]
        if len(pair_nodes) != 1:
            raise ProofFailure("invalid_proof", "fixed-sum AM-GM evidence missing")
        pair_u, pair_v = freeze(pair_nodes[0]["conclusion"])[1][1:]
        equality = f"({math_text(pair_u)})=({math_text(pair_v)})"
        application = {
            "terms": [math_text(pair_u), math_text(pair_v)],
            "equality": equality,
        }
        return {
            **legacy,
            "schema_version": "amgm-bound/v2",
            "direction": direction,
            "expression": None,
            "previous_bound": None,
            "source_math": source,
            "equality": equality,
            "equalities": [equality],
            "applications": [application],
        }
    chain = parse_derivation(steps, context.symbols)
    final = chain[-1].parsed
    if final.ast.op not in {">=", "<="}:
        raise ProofFailure(
            "target_bound_mismatch", "minimum needs a lower-bound relation"
        )
    left, right = final.ast.children
    if final.ast.op == "<=":
        left, right = right, left
    bound = final.source[slice(*right.span)]
    premises = dict(context.premises)
    proofs = []
    if predecessor:
        prior = parse_math_relation(
            f"({target['target_math']})>=({source})", context.symbols
        )
        premises["bound:previous"] = prior
    if expression is not None:
        eq = parse_math_relation(
            f"({target['target_math']})=({source})", context.symbols
        )
        proof = certify(eq, context)
        proofs.append(proof)
        premises["expression:verified"] = eq
    working = replace(context, premises=premises)
    # The submitted final lhs may be the original target or the current source.
    from .proof_algebra import Arithmetic

    arithmetic = Arithmetic(budget)
    lhs = from_node(left)
    if all(
        arithmetic.difference(
            ("=", lhs, from_node(parse_math_expression(t, context.symbols).ast))
        )
        for t in (source, target["target_math"])
    ):
        raise ProofFailure(
            "target_bound_mismatch",
            "last relation must bound the current or original target",
        )
    origins = [r.origin for r in chain]
    if certificates is not None and certificates["derivation"]["origins"] != origins:
        raise ProofFailure("invalid_proof", "bound origins changed")
    sequence = verify_relation_sequence(
        [r.parsed for r in chain],
        working,
        certificates=certificates["derivation"]["proofs"]
        if certificates is not None
        else None,
        budget=budget,
    )
    if certificates is None:
        verify_relation_sequence(
            [r.parsed for r in chain], working, certificates=sequence
        )
    pairs = {}
    for proof in sequence:
        for node in proof["nodes"]:
            if node["rule_id"] != "math.two_term_amgm":
                continue
            u, v = freeze(node["conclusion"])[1][1:]
            key = commutative_key(("add", u, v))
            pairs[key] = (u, v)
    if len(pairs) != 1:
        raise ProofFailure(
            "inequality_ambiguous" if pairs else "inequality_template_unmatched",
            "one new positive two-term AM-GM application per call is required",
        )
    u, v = next(iter(pairs.values()))
    equality = f"({math_text(u)})=({math_text(v)})"
    equalities.append(equality)
    dependencies.append({"terms": [math_text(u), math_text(v)], "equality": equality})
    for i, row in enumerate(chain):
        premises[f"bound:row:{i}"] = row.parsed
    final_context = replace(context, premises=premises)
    goal = parse_math_relation(f"({target['target_math']})>=({bound})", context.symbols)
    proof = certify(goal, final_context)
    if certificates is not None and proof_index != len(certificates["proofs"]):
        raise ProofFailure("invalid_proof", "unused bound certificates")
    proofs.append(proof)
    return {
        "schema_version": "amgm-bound/v2",
        "target_hash": digest(target),
        "target_math": target["target_math"],
        "direction": direction,
        "source_math": source,
        "expression": str(expression) if expression is not None else None,
        "previous_bound": deepcopy(previous_bound),
        "steps": deepcopy(steps),
        "bound": bound,
        "equality": equality,
        "equalities": equalities,
        "applications": dependencies,
        "proofs": proofs,
        "derivation": {"origins": [r.origin for r in chain], "proofs": sequence},
    }


def verify_equality_derivation(
    context,
    equalities,
    rows,
    *,
    certificates=None,
    budget=None,
    source_path="/parameters/equality_derivation",
):
    """Check submitted equation-solving steps, conditional on AM-GM equality.

    Only explicit selected equations and original domain/sign conditions are
    premises. A witness assignment is never imported as an assumption.
    """
    if not 1 <= len(rows) <= 8:
        raise ProofFailure(
            "proof_limit", "one to eight equality derivation rows required"
        )
    known = dict(context.premises)
    known.update(
        {
            f"attainment:{i}": parse_math_relation(eq, context.symbols)
            for i, eq in enumerate(equalities)
        }
    )
    budget = budget or _Budget(context.limits)
    reports = []
    if certificates is not None and len(certificates) != len(rows):
        raise ProofFailure("invalid_proof", "equality derivation length changed")
    for i, row in enumerate(rows):
        selected = {k: v for k, v in context.premises.items() if v.ast.op != "="}
        for source in row["using"]:
            key = commutative_key(
                from_node(parse_math_relation(source, context.symbols).ast)
            )
            matches = [
                (k, v)
                for k, v in known.items()
                if v.ast.op == "=" and commutative_key(from_node(v.ast)) == key
            ]
            if len(matches) != 1:
                raise ProofFailure(
                    "invalid_input", "using must select one known equality"
                )
            selected[matches[0][0]] = matches[0][1]
        parsed = replace(
            parse_math_relation(row["math"], context.symbols),
            source_path=f"{source_path}/{i}/math",
        )
        if parsed.ast.op != "=":
            raise ProofFailure(
                "invalid_input", "equality derivation requires equations"
            )
        current = replace(context, premises=selected)
        proof = verify_relation_sequence(
            [parsed],
            current,
            budget=budget,
            certificates=[certificates[i]["proof"]]
            if certificates is not None
            else None,
        )[0]
        reports.append(
            {
                "math": row["math"],
                "using": list(row["using"]),
                "source_path": parsed.source_path,
                "proof": proof,
            }
        )
        known[f"equality_derivation:{i}"] = parsed
    return reports


def close(
    target, bound, branches, *, equality_derivation=None, branch_derivations=None
):
    from .inequality_evidence import require, target_context

    context, _ = target_context(target)
    replay_budget = _Budget(context.limits)
    witness_budget = _Budget(context.limits)
    if not isinstance(bound.get("certificate_bundle"), dict):
        raise ProofFailure("invalid_proof", "missing bound certificate bundle")
    rebuilt = verify(
        target,
        bound["steps"],
        expression=bound.get("expression"),
        previous_bound=bound.get("previous_bound"),
        certificates=bound.get("certificate_bundle"),
        budget=replay_budget,
    )
    if public(rebuilt) != bound:
        raise ProofFailure("invalid_proof", "bound or dependency evidence altered")
    value = parse_math_expression(bound["bound"], context.symbols)
    if names(from_node(value.ast)):
        raise ProofFailure(
            "target_bound_mismatch", "extremum closure requires a constant bound"
        )
    if not 1 <= len(branches) <= 8:
        raise ProofFailure("proof_limit", "one to eight explicit branches required")
    reports = []
    if branch_derivations is not None and len(branch_derivations) != len(branches):
        raise ProofFailure("invalid_input", "branch derivation count mismatch")
    for branch_index, steps in enumerate(branches):
        chain = parse_derivation(steps, context.symbols)
        assignments, aliases = {}, []
        for row in chain:
            if row.parsed.ast.op != "=":
                continue
            a, b = row.parsed.ast.children
            for name, val in ((a, b), (b, a)):
                if name.op != "symbol":
                    continue
                if val.op == "symbol":
                    aliases.append((name.text, val.text))
                else:
                    parsed = parse_math_expression(
                        row.parsed.source[slice(*val.span)], context.symbols
                    )
                    if not names(from_node(parsed.ast)):
                        assignments.setdefault(name.text, parsed)
        for _ in context.symbols:
            for a, b in aliases:
                if a not in assignments and b in assignments:
                    assignments[a] = assignments[b]
        if set(assignments) != set(context.symbols):
            raise ProofFailure(
                "witness_assignment_invalid",
                "explicit constant assignment for every original variable required",
            )
        required = [
            parse_math_relation(t, context.symbols)
            for t in [
                *bound["equalities"],
                f"({target['target_math']})=({bound['bound']})",
            ]
        ] + [r.parsed for r in chain]
        if branch_derivations is not None:
            when = replace(
                parse_math_relation(
                    branch_derivations[branch_index]["when"], context.symbols
                ),
                source_path=f"/parameters/branches/{branch_index}/when",
            )
            if when.ast.op not in {">=", "<="}:
                raise ProofFailure(
                    "invalid_input", "branch case must be a non-strict sign comparison"
                )
            # An assumed case must hold for the independently checked witness.
            required.append(when)
        # A submitted row can repeat the target/equality checks that closure
        # already requires. Share that exact assertion's proof, while retaining
        # coverage for every source document; never drop a distinct requirement.
        unique, by_ast, coverage = [], {}, []
        for requirement in required:
            key = from_node(requirement.ast)
            if key not in by_ast:
                by_ast[key] = len(unique)
                unique.append(requirement)
            coverage.append(
                {
                    "proof_requirement": by_ast[key],
                    "source": _document(requirement),
                }
            )
        required = unique
        if len(required) > 16:
            raise ProofFailure(
                "proof_limit",
                f"见证共 {len(required)} 个关系，超过 16；请删去重复常量计算并缩短关系链，"
                "保留具体赋值与取等条件。内核自动验证原条件及目标值。",
            )
        proof = require(
            verify_witnesses([assignments], required, context, _budget=witness_budget)
        )
        _replay(proof, context, budget=replay_budget)
        reports.append(
            {
                "assignments": {k: v.source for k, v in sorted(assignments.items())},
                "steps": deepcopy(steps),
                "origins": [r.origin for r in chain],
                "proof": proof,
                "requirement_coverage": coverage,
            }
        )
    first = reports[0]
    derivation = None
    derivation_budget, derivation_replay_budget = (
        _Budget(context.limits),
        _Budget(context.limits),
    )
    if equality_derivation is not None:
        if len(reports) != 1 and branch_derivations is None:
            raise ProofFailure(
                "invalid_input",
                "shared equation derivation requires a derivation for every branch",
            )
        derivation = verify_equality_derivation(
            context, bound["equalities"], equality_derivation, budget=derivation_budget
        )
        verify_equality_derivation(
            context,
            bound["equalities"],
            equality_derivation,
            certificates=derivation,
            budget=derivation_replay_budget,
        )
    if branch_derivations is not None and not derivation:
        raise ProofFailure(
            "invalid_input", "branch derivations require the shared equation derivation"
        )

    def check_assignments(rows, assignments):
        derived = {
            from_node(parse_math_relation(row["math"], context.symbols).ast)
            for row in rows
        }
        for name, val in assignments.items():
            if (
                from_node(parse_math_relation(f"{name}=({val})", context.symbols).ast)
                not in derived
            ):
                raise ProofFailure(
                    "proof_missing",
                    "equation derivation must derive every submitted assignment",
                )

    if derivation and branch_derivations is None:
        check_assignments(derivation, first["assignments"])
    if branch_derivations is not None:
        shared = {
            **context.premises,
            **{
                f"shared_solution:{i}": parse_math_relation(
                    row["math"], context.symbols
                )
                for i, row in enumerate(derivation)
            },
        }
        for i, (report, description) in enumerate(
            zip(reports, branch_derivations, strict=True)
        ):
            case = replace(
                parse_math_relation(description["when"], context.symbols),
                source_path=f"/parameters/branches/{i}/when",
            )
            case_context = replace(context, premises={**shared, "solution_case": case})
            path = f"/parameters/branches/{i}/equality_derivation"
            proof_rows = verify_equality_derivation(
                case_context,
                bound["equalities"],
                description["equality_derivation"],
                budget=derivation_budget,
                source_path=path,
            )
            verify_equality_derivation(
                case_context,
                bound["equalities"],
                description["equality_derivation"],
                certificates=proof_rows,
                budget=derivation_replay_budget,
                source_path=path,
            )
            check_assignments(proof_rows, report["assignments"])
            report.update(when=description["when"], equality_derivation=proof_rows)
    return value.to_sympy(context.symbols), {
        "kind": "verified_extremum",
        "bound": rebuilt,
        "witness_proof": first["proof"],
        "assignments": first["assignments"],
        "steps": first["steps"],
        "derivation_origins": first["origins"],
        "branches": reports,
        "claim_scope": "submitted_witness",
        "exhaustive": False,
        "equality_derivation": derivation,
    }
