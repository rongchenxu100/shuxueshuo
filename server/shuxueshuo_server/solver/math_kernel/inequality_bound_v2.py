"""One local AM-GM application with explicit, replayable predecessor bounds."""

from copy import deepcopy
from dataclasses import replace

from .derivation_math import parse_derivation
from .expression_parser import parse_math_expression, parse_math_relation
from .method_proof_session import record_checked_bound
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
            if k not in {"proofs", "derivation", "reciprocal_bound", "local_application", "method_application"}
        },
        "certificate_bundle": {
            k: deepcopy(evidence[k])
            for k in ("proofs", "derivation", "reciprocal_bound", "local_application", "method_application")
            if k in evidence
        },
    }


@record_checked_bound
def verify(
    target,
    steps,
    *,
    expression=None,
    previous_bound=None,
    elimination=None,
    substitution=None,
    reciprocal=False,
    bound_relation_index=-1,
    depth=0,
    certificates=None,
    budget=None,
):
    from .inequality_evidence import _verify_bound_v1, target_context

    if depth > 8:
        raise ProofFailure("proof_limit", "at most eight bound dependencies")
    if sum(v is not None for v in (expression, previous_bound, elimination, substitution)) > 1:
        raise ProofFailure(
            "invalid_input",
            "expression, elimination, substitution and previous_bound are mutually exclusive",
        )
    if reciprocal:
        if expression is not None or previous_bound is not None or substitution is not None:
            raise ProofFailure(
                "invalid_input",
                "reciprocal accepts only a same-target elimination input",
            )
        from .reciprocal_bound import verify_reciprocal

        return verify_reciprocal(
            target, steps, elimination, certificates=certificates, budget=budget
        )
    context, _ = target_context(target)
    from .constraint_elimination import elimination_context, has_elimination

    if elimination is not None or has_elimination(previous_bound):
        context = elimination_context(context)
    from .substitution import (
        find_substitution,
        replay_substitution,
        substitution_context,
    )
    inherited_substitution = substitution or find_substitution({"elimination": elimination}) or find_substitution(previous_bound)
    if inherited_substitution is not None:
        context = substitution_context(context)
    budget = budget or _Budget(context.limits)
    context = replace(context, limits=budget.limits)
    if inherited_substitution is not None and elimination is None:
        context = replay_substitution(target, inherited_substitution, budget=budget)
    if elimination is not None:
        from .constraint_elimination import replay_elimination

        context = replay_elimination(target, elimination, budget=budget)
    proof_index = 0

    def certify(parsed, ctx):
        nonlocal proof_index
        request = {"kind": "relation", "candidate": _document(parsed)}
        if certificates is None:
            proof = _run_request(ctx, request, budget=budget).proof
            # _run_request already independently checked this certificate.
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
        from .bound_chain import consume_bound, replay_bound
        read_bound = consume_bound if certificates is None else replay_bound
        predecessor = read_bound(target, previous_bound, depth=depth + 1, budget=budget)
        if predecessor["direction"] != ">=":
            raise ProofFailure("target_bound_mismatch", "predecessor must be a lower bound")
        ancestor = previous_bound
        while ancestor.get("previous_bound") is not None:
            ancestor = ancestor["previous_bound"]
        if ancestor.get("elimination") is not None:
            from .constraint_elimination import replay_elimination

            context = replay_elimination(target, ancestor["elimination"], budget=budget)
        source = predecessor["bound"]
        equalities = list(predecessor["equalities"])
        dependencies = list(predecessor["applications"])
    elif substitution is not None:
        source = substitution["expression"]
    elif expression is not None:
        source = str(expression)
    elif elimination is not None:
        source = elimination["expression"]
    direction = "<=" if target["goal_kind"] == "find_maximum" else ">="
    if direction == "<=":
        if (
            previous_bound is not None
            or expression is not None
            or elimination is not None
            or substitution is not None
        ):
            raise ProofFailure(
                "inequality_template_unmatched",
                "maximum path requires the fixed-sum product template",
            )
        from .method_proof_session import active_session
        if (certificates is None and active_session() is not None) or (certificates is not None and "method_application" in certificates):
            from .amgm_application import verify_application
            from .inequality_evidence import _check_fixed_sum_bound_shape
            chain = parse_derivation(steps, context.symbols)
            upper = chain[-1].parsed
            _check_fixed_sum_bound_shape(upper, chain[-1].origin, context)
            if upper.ast.op != "<=" or parse_math_expression(upper.source[slice(*upper.ast.children[1].span)], context.symbols).to_sympy(context.symbols).free_symbols:
                raise ProofFailure("target_bound_mismatch", "fixed-sum constant upper bound required")
            bound = upper.source[slice(*upper.ast.children[1].span)]
            app = verify_application(context, target, source, bound, chain, budget=budget,
                                     certificate=certificates["method_application"] if certificates else None)
            sequence = verify_relation_sequence([r.parsed for r in chain], context, budget=budget,
                certificates=certificates["derivation"]["proofs"] if certificates else None)
            target_eq = parse_math_relation(f"({source})=({upper.source[slice(*upper.ast.children[0].span)]})", context.symbols)
            if certificates:
                proofs = certificates["proofs"]
                if len(proofs) != 3 or proofs[0] != app["local_proof"] or proofs[1]["request"]["candidate"] != _document(upper) or proofs[2]["request"]["candidate"] != _document(target_eq):
                    raise ProofFailure("invalid_proof", "fixed-sum evidence changed")
                for proof in proofs:
                    _replay(proof, context, budget=budget)
                if certificates["derivation"]["origins"] != [r.origin for r in chain]:
                    raise ProofFailure("invalid_proof", "bound origins changed")
            else:
                proofs = [app["local_proof"], certify(upper, context), certify(target_eq, context)]
            return {"schema_version": "amgm-bound/v2", "target_hash": digest(target),
                    "target_math": target["target_math"], "steps": deepcopy(steps),
                    "proofs": proofs, "derivation": {"origins": [r.origin for r in chain], "proofs": sequence},
                    "bound": str(parse_math_expression(bound, context.symbols).to_sympy(context.symbols)),
                    "direction": direction, "expression": None, "previous_bound": None,
                    "source_math": source, "equality": app["equality"], "equalities": [app["equality"]],
                    "applications": [{"terms": app["terms"], "equality": app["equality"]}],
                    "method_application": app}
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
    final = chain[bound_relation_index].parsed
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
        # The identity is already certified; do not add a redundant equation
        # to local sign search. Final transport still checks the original target.
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
    method_application = None
    # Missing application field selects the immutable legacy replay protocol.
    from .method_proof_session import active_session
    modern = (certificates is None and active_session() is not None) or (certificates is not None and "method_application" in certificates)
    if modern:
        from .amgm_application import verify_application
        if certificates is None and all(
            any(from_node(row.parsed.ast) == from_node(p.ast) for p in working.premises.values())
            for row in chain
        ):
            raise ProofFailure("inequality_template_unmatched", "old bound alone has no current application")
        method_application = verify_application(
            context, target, source, bound, chain, budget=budget,
            certificate=certificates["method_application"] if certificates else None,
        )
        u, v = (freeze(t) for t in method_application["terms_ast"])
        local_application = method_application["effect"]
        sequence = verify_relation_sequence(
            [r.parsed for r in chain], working, budget=budget,
            certificates=certificates["derivation"]["proofs"] if certificates else None,
        )
    else:
        checked_pairs = set()

        def check_local_contract(proof):
            # Use only a certified pair, never infer proof authority from notation.
            # Reject an independently removed remainder before later rows can
            # consume the whole search budget and obscure the Method boundary.
            from .local_bound_contract import verify_local_application

            for node in proof["nodes"]:
                if node["rule_id"] != "math.two_term_amgm":
                    continue
                u, v = freeze(node["conclusion"])[1][1:]
                key = commutative_key(("add", u, v))
                if key not in checked_pairs:
                    verify_local_application(context, source, bound, u, v, budget=budget)
                    checked_pairs.add(key)

        sequence = verify_relation_sequence(
            [r.parsed for r in chain],
            working,
            certificates=certificates["derivation"]["proofs"]
            if certificates is not None
            else None,
            budget=budget,
            on_verified=check_local_contract if certificates is None else None,
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
        local_application = None
        if certificates is None or "local_application" in certificates:
            from .local_bound_contract import verify_local_application
            local_application = verify_local_application(
                context, source, bound, u, v, budget=budget,
                certificates=certificates.get("local_application") if certificates is not None else None,
            )
    equality = f"({math_text(u)})=({math_text(v)})"
    equalities.append(equality)
    dependencies.append({"terms": [math_text(u), math_text(v)], "equality": equality})
    transport_premises = dict(premises)
    for i, row in enumerate(chain):
        premises[f"bound:row:{i}"] = row.parsed
    from .proof_kernel import fact_key
    if len({fact_key(from_node(p.ast)) for p in premises.values()}) > context.limits.premises:
        # Every row was certified above. Final transport needs the selected
        # complete bound, not every intermediate algebraic spelling. Preserve
        # original scope facts and predecessors; use the same source ID for
        # replay. Previously accepted (within-limit) certificates keep their
        # original context unchanged.
        transport_premises[f"bound:row:{bound_relation_index % len(chain)}"] = final
        premises = transport_premises
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
        **({"method_application": method_application} if method_application is not None else {}),
        **({"local_application": local_application} if local_application is not None else {}),
        "expression": str(expression) if expression is not None else None,
        "previous_bound": deepcopy(previous_bound),
        **({"elimination": deepcopy(elimination)} if elimination is not None else {}),
        **({"substitution": deepcopy(substitution)} if substitution is not None else {}),
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


def verify_equality_references(chain, equalities, context, budget):
    """Resolve natural equality references against replayed bound conditions."""
    import sympy as sp

    from .proof_algebra import Arithmetic

    arithmetic = Arithmetic(budget)
    known = [parse_math_relation(eq, context.symbols) for eq in equalities]
    reports = []
    for row in chain:
        reference = row.origin.get("equality_reference")
        if reference is None:
            continue
        goal = ("sub", *from_node(row.parsed.ast)[1:])
        matched = next((eq for eq in known if arithmetic.proportional(
            goal, ("sub", *from_node(eq.ast)[1:])
        ) not in (None, 0)), None)
        if matched is None:
            raise ProofFailure("equality_reference_unmatched", "取等关系必须对应前序已验证的取等条件")
        cited = parse_math_relation(reference["inequality"], context.symbols)
        # Establish the inequality without assuming attainment.
        proofs = verify_relation_sequence([cited], context, budget=budget)
        verify_relation_sequence([cited], context, certificates=proofs)
        left, right = cited.ast.children
        equality = parse_math_relation(
            f"({cited.source[slice(*left.span)]})=({cited.source[slice(*right.span)]})",
            context.symbols,
        )
        when = replace(context, premises={**context.premises, "attainment:reference": matched})
        left_text, right_text = (cited.source[slice(*side.span)] for side in (left, right))
        def square_text(text):
            value = parse_math_expression(text, context.symbols).to_sympy(context.symbols)
            # A generated candidate, still proved by the kernel; avoid nested
            # powers rejected by the submitted-expression size guard.
            return str(sp.expand(value ** 2))
        attainment_rows = [equality]
        try:
            _, remainder = arithmetic.reduce(
                arithmetic.difference(from_node(equality.ast)),
                [arithmetic.equation_divisor(from_node(matched.ast))],
            )
            direct_identity = not remainder
        except ProofFailure as exc:
            if exc.code not in {"proof_limit", "proof_missing"}:
                raise
            direct_identity = False
        if not direct_identity:
            squared = parse_math_relation(
                f"{square_text(left_text)}={square_text(right_text)}", context.symbols
            )
            # Only introduce a squared helper when direct reduction does not
            # establish equality. The probe is not proof authority: both paths
            # are independently checked, including square_equal's sign guards.
            attainment_rows.insert(0, squared)
        attained = verify_relation_sequence(attainment_rows, when, budget=budget)
        verify_relation_sequence(attainment_rows, when, certificates=attained)
        reports.append({"origin": row.origin, "condition": matched.source,
                        "inequality_proof": proofs, "attainment_proof": attained})
    return reports


def close(
    target, bound, branches, *, equality_derivation=None, branch_derivations=None
):
    from .inequality_evidence import require, target_context

    context, _ = target_context(target)
    from .constraint_elimination import elimination_context, has_elimination

    if has_elimination(bound):
        context = elimination_context(context)
    from .substitution import (
        find_substitution,
        replay_substitution,
        substitution_context,
    )
    substitution = find_substitution(bound)
    if substitution is not None:
        context = substitution_context(context)
    replay_budget = _Budget(context.limits)
    witness_budget = _Budget(context.limits)
    if not isinstance(bound.get("certificate_bundle"), dict):
        raise ProofFailure("invalid_proof", "missing bound certificate bundle")
    from .bound_chain import consume_bound
    rebuilt = consume_bound(target, bound, budget=replay_budget)
    ancestor = bound
    while ancestor.get("previous_bound") is not None:
        ancestor = ancestor["previous_bound"]
    if ancestor.get("elimination") is not None:
        from .constraint_elimination import replay_elimination

        context = replay_elimination(
            target, ancestor["elimination"], budget=replay_budget
        )
        # Witnesses check the original target directly. The expanded target
        # equivalence is already replayed above and is not a witness premise.
        context = replace(
            context,
            premises={
                k: p
                for k, p in context.premises.items()
                if p.source_path != "/parameters/expression"
            },
        )
    if substitution is not None:
        context = replay_substitution(target, substitution, budget=replay_budget)
        context = replace(context, premises={k:p for k,p in context.premises.items() if p.source_path != "/parameters/expression"})
    # Restoration checks original facts and conservative definitions. All
    # transformed rows have already been replayed above; repeating them in the
    # witness bundle adds no authority and can exceed the finite bundle size.
    witness_context = replace(context, premises={k:p for k,p in context.premises.items()
        if not k.startswith("substitution:verified:")}) if substitution is not None else context
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
        chain = parse_derivation(steps, context.symbols, closure_target=target)
        equality_references = verify_equality_references(
            chain, rebuilt["equalities"], context, witness_budget
        )
        assignments, aliases = {}, []
        for row in chain:
            # Summary statements add obligations, never manufacture witnesses.
            if row.origin.get("statement_reference") or row.origin.get("equality_reference"):
                continue
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
        if substitution is not None:
            if not set(target["scalar_symbols"]) <= assignments.keys():
                raise ProofFailure("witness_assignment_invalid", "submit every original variable explicitly")
            original_values = {context.symbols[k]: assignments[k].to_sympy(context.symbols) for k in target["scalar_symbols"]}
            for name, definition in substitution["definitions"].items():
                if name not in assignments:
                    computed = parse_math_expression(definition, context.symbols).to_sympy(context.symbols).subs(original_values)
                    assignments[name] = parse_math_expression(str(computed), context.symbols)
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
        # Keep the proof kernel's bounded certificate size. Natural comparison
        # chains can produce more assertions; verify every batch under the same
        # total construction/replay budgets and the exact same witness/context.
        proof_batches = []
        for offset in range(0, len(required), 16):
            proof = require(verify_witnesses(
                [assignments], required[offset:offset + 16], witness_context,
                _budget=witness_budget,
            ))
            _replay(proof, witness_context, budget=replay_budget)
            proof_batches.append(proof)
        proof = proof_batches[0]
        if len(proof_batches) > 1:
            for entry in coverage:
                entry["proof_batch"], entry["batch_requirement"] = divmod(entry["proof_requirement"], 16)
        reports.append(
            {
                "assignments": {k: v.source for k, v in sorted(assignments.items())},
                "steps": deepcopy(steps),
                "origins": [r.origin for r in chain],
                **({"equality_references": equality_references} if equality_references else {}),
                "proof": proof,
                **({"proof_batches": proof_batches} if len(proof_batches) > 1 else {}),
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
        **({"witness_proof_batches": first["proof_batches"]} if "proof_batches" in first else {}),
        "assignments": first["assignments"],
        "steps": first["steps"],
        "derivation_origins": first["origins"],
        "branches": reports,
        "claim_scope": "submitted_witness",
        "exhaustive": False,
        "equality_derivation": derivation,
    }
