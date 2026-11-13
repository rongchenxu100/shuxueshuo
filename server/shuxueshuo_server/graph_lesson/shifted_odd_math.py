"""FP-T6 source-bound offset odd applications. No question ids or model answers."""

from copy import deepcopy

import sympy as sp

from . import function_cells, symmetry_linear
from .function_parity import reflect_set
from .parity_extension_math import ARGUMENT, _replace
from .parity_parameter_math import _budget
from .shifted_odd_identity import (
    X,
    compatibility,
    exact_budget,
    fixed_set,
    identity,
    scalar,
    verify_compatibility,
    verify_identity,
)
from .symmetry_relation_math import _substitute
from .symmetry_value_math import _function_calls

VERSION = "function-symmetry/shifted-odd-v1"


def name(ref):
    return ref.rsplit(":", 1)[-1]


def extrema_request(goal, goal_ast, target_ref, entries):
    """Adapt the existing range answer request without changing model/source data.

    Named extrema belong to this goal and the same function/input restriction.
    Only their sum enters T6; other range requests retain their ordinary route.
    """
    if goal.get("kind") not in ("find_range", "find_extrema_expression"):
        return None
    # The T6 extrema certificate needs an explicit input scope. A global
    # range/extremum task keeps its existing range methods and original choices.
    if "input_domain" not in goal_ast and not any(
        r["ast"][0] == "=" and r["ast"][1][:2] == ["call", "Dom"]
        and r["ast"][2] != ["real"] for r in entries
    ):
        return None
    from ..problem_understanding.answer_requests import request_for_goal
    from ..problem_understanding.notation_parser import parse

    request = request_for_goal(goal)
    if not request or request["kind"] != "expression":
        return None
    bindings = request["bindings"]
    if len(bindings) != 2 or {r["quantity"] for r in bindings} != {"minimum", "maximum"}:
        return None
    target = parse(request["expression"])
    names = [["name", r["symbol"]] for r in bindings]
    if target not in (["+", *names], ["+", *reversed(names)]):
        return None
    function = goal_ast["target"]
    if function[0] != "ref" or function[2] != "function":
        return None
    derived = deepcopy(entries)
    if "input_domain" in goal_ast:
        derived.append({
            "source_ref": target_ref + "/input_domain",
            "expression": "Dom(" + name(function[1]) + ")=" + goal["input_domain"],
            "ast": ["=", ["call", "Dom", function], deepcopy(goal_ast["input_domain"])],
            "input_restriction": True,
        })
    for i, binding in enumerate(bindings):
        symbol = binding["symbol"]
        ref = ["ref", target_ref + "/answer:" + symbol, "scalar"]
        target = _replace(target, ["name", symbol], ref)
        operation = {"maximum": "max", "minimum": "min"}[binding["quantity"]]
        derived.append({
            "source_ref": target_ref + (f"/answer_request/bindings/{i}" if "answer_request" in goal else f"/extrema/{i}"),
            "expression": symbol + "=" + operation + "(" + name(function[1]) + "(x))",
            "ast": ["=", ref, ["extremum", operation, [],
                    ["function_call", function, ["ref", target_ref + "/answer:x", "scalar"]]]],
        })
    return ({"kind": "find_value", "expression": request["expression"]},
            {"kind": "find_value", "target": target}, derived)


def owned(goal, goal_ast, entries):
    if goal.get("kind") not in ("find_value", "finite_sum"):
        return False
    definitions = [r["ast"] for r in entries if r["ast"][0] == "function_definition"]
    parity_facts = [r["ast"] for r in entries if r["ast"][0] == "function_parity"]
    odd = {a[1][1] for a in parity_facts if a[2] == "odd"}
    local = [r["ast"] for r in entries if r["ast"][0] == "quantifier"]
    if any(
        a[4][0] == "="
        and a[4][1][0] == "function_call"
        and len({c[1][1] for c in _function_calls(a)}) == 2
        and any(c[1][1] in odd for c in _function_calls(a))
        for a in local
    ):
        return True
    if any(
        _function_calls(d[2])
        and (d[1][1] in odd or any(c[1][1] in odd for c in _function_calls(d[2])))
        for d in definitions
    ):
        return True
    explicit = [d for d in definitions if not _function_calls(d[2])]
    if (
        not explicit
        or parity_facts
        or any(r["ast"][0] == "function_graph_symmetry" for r in entries)
    ):
        return False
    extrema = any("extremum" in str(r["ast"]) for r in entries)
    try:
        expanded = targets({"source": goal, "goal_ast": goal_ast})
        calls = [c for row in expanded for c in _function_calls(row["ast"])]
        # Nested calls need forward evaluation before their inputs can be
        # compared. A scalar parsing failure is not evidence of an odd shift.
        if any(_function_calls(c[2]) for c in calls):
            return False
        inputs = [(c[1][1], scalar(c[2])) for c in calls]
        paired = any((ref, -q) in inputs for ref, q in inputs)
        known = [
            c
            for row in entries
            if row["ast"][0] == "="
            for c in _function_calls(row["ast"])
        ]
        symbolic = any(
            q.free_symbols and any(c[1][1] == ref for c in known) for ref, q in inputs
        )
        if not (extrema or paired or symbolic):
            return False
        if len(explicit) == 1:
            formula = explicit[0]
            domains = [
                row["ast"][2]
                for row in entries
                if row["ast"][0] == "="
                and row["ast"][1][:2] == ["call", "Dom"]
                and row["ast"][1][2] == formula[1]
            ]
            identity(
                formula[2], domains[0] if len(domains) == 1 else None, formula[1][1], ""
            )
        return True
    except (ValueError, TypeError, KeyError, IndexError, NotImplementedError) as exc:
        # A proved counterexample leaves ordinary explicit evaluation available.
        return str(exc) not in {
            "shifted_odd.not_constant_sum",
            "shifted_odd.fixed_identity_unproved",
            "shifted_odd.domain_not_symmetric",
        }


def describe(goal, goal_ast, target_ref, entries, *, candidate=None):
    adapted = extrema_request(goal, goal_ast, target_ref, entries)
    execution_goal, execution_ast, entries = adapted or (goal, goal_ast, entries)
    if not owned(execution_goal, execution_ast, entries):
        return None
    d = {
        "source": deepcopy(goal),
        "target_ref": target_ref,
        "goal_ast": deepcopy(execution_ast),
        "requested_expression": execution_goal.get("expression"),
        "structure_version": VERSION,
        "structure_supported": False,
        "reason": "",
        "source_refs": list(dict.fromkeys([target_ref, *[
            target_ref if r["source_ref"].startswith(target_ref + "/") else r["source_ref"]
            for r in entries
        ]])),
        "given_entries": [
            {k: deepcopy(r[k]) for k in ("source_ref", "expression", "ast", "input_restriction") if k in r}
            for r in entries
        ],
    }
    try:
        parse_sources(d)
        if candidate is not None:
            from .stage_two.fragments import _scope_ranges
            from .stage_two.shifted_odd_surface import source_spans

            if (
                source_spans(
                    candidate, target_ref, _scope_ranges(candidate, target_ref), d
                )
                is None
            ):
                raise ValueError("shifted_odd.source_not_bound")
        d["structure_supported"] = True
    except (ValueError, TypeError, KeyError, IndexError, NotImplementedError) as exc:
        d["reason"] = str(exc)
    return d


def parse_sources(d):
    defs, domains, odd, values, extrema = [], {}, [], [], {}
    declarations = []
    restrictions = {}
    scope_ast = None
    for r in d["given_entries"]:
        a = r["ast"]
        _budget(a)
        if a[0] == "function_definition":
            defs.append(r)
        elif a[0] == "quantifier":
            if (
                a[1] != "∀"
                or a[4][0] != "="
                or a[4][1][0] != "function_call"
                or a[4][1][2] != ["bound", a[2]]
                or scope_ast is not None
            ):
                raise ValueError("shifted_odd.local_affine_required")
            normalized = [
                "function_definition",
                a[4][1][1],
                _replace(a[4][2], ["bound", a[2]], ARGUMENT),
            ]
            if not _function_calls(normalized[2]):
                raise ValueError("shifted_odd.local_affine_required")
            defs.append({**r, "ast": normalized, "original_ast": a})
            scope_ast = a[3]
        elif a[0] == "=" and a[1][:2] == ["call", "Dom"]:
            ref = a[1][2][1]
            if r.get("input_restriction"):
                fixed_set(a[2])
                restrictions[ref] = a[2]
                continue
            if ref in domains and domains[ref] != a[2]:
                raise ValueError("shifted_odd.conflicting_domains")
            fixed_set(a[2])
            domains[ref] = a[2]
        elif a[0] == "function_parity" and a[2] == "odd":
            odd.append(a[1][1])
        elif a[0] == "=" and a[1][0] == "ref" and a[2][0] == "extremum":
            if a[1][1] in extrema and extrema[a[1][1]] != a[2]:
                raise ValueError("shifted_odd.conflicting_extrema")
            extrema[a[1][1]] = a[2]
        elif a[0] == "=" and _function_calls(a):
            values.append(r)
        elif a[0] == "default_domain" and a[1][0] == "ref" and a[1][2] == "scalar" and a[2] == "real":
            declarations.append(r)
        else:
            raise ValueError("shifted_odd.additional_condition_unsupported")
    for ref, scope in restrictions.items():
        domains[ref] = ["∩", domains[ref], scope] if ref in domains else scope
    if len(defs) != 1 or len(values) > 32:
        raise ValueError("shifted_odd.definition_or_condition_budget")
    original = defs[0]
    a = original["ast"]
    def scalar_refs(ast):
        if ast[0] == "ref" and ast[2] == "scalar":
            return {ast[1]}
        return set().union(*(scalar_refs(t) for t in ast[1:] if isinstance(t, list)))
    if any(r["ast"][1][1] not in scalar_refs(a[2]) for r in declarations):
        raise ValueError("shifted_odd.unrelated_scalar_declaration")
    explicit = not _function_calls(a[2])
    refs = {a[1][1], *[c[1][1] for c in _function_calls(a[2])]}
    if set(domains) - refs or set(odd) - refs:
        raise ValueError("shifted_odd.other_function")
    if explicit:
        if odd:
            raise ValueError("shifted_odd.additional_parity_unsupported")
        from .shifted_odd_identity import admitted_expression

        admitted_expression(a[2])
    elif len(refs) != 2 or len(odd) != 1 or extrema:
        raise ValueError("shifted_odd.affine_odd_source_required")
    if not explicit:
        # Same-input affine definition, with original zero coefficients retained.
        for c in _function_calls(a[2]):
            if c[2] != ARGUMENT:
                raise ValueError("shifted_odd.input_transform_unsupported")
        equation = ["-", ["function_call", a[1], ARGUMENT], a[2]]
        terms, constant = combine(equation, argument=X, symbolic_coefficients=True)
        coeffs = [*terms.values(), constant]
        if any(q != X for _, q in terms) or any(X in v.free_symbols for v in coeffs):
            raise ValueError("shifted_odd.affine_required")
        params = set().union(*(v.free_symbols for v in coeffs))
        if len(params) > 1 or any(
            params and sp.Poly(v, *params).total_degree() > 1 for v in coeffs
        ):
            raise ValueError("shifted_odd.affine_parameter_budget")
    if scope_ast is not None:
        if scope_ast[:2] == ["call", "Dom"]:
            scope_ast = domains.get(scope_ast[2][1])
            if scope_ast is None:
                raise ValueError("shifted_odd.local_domain_unproved")
        if fixed_set(scope_ast) == sp.S.EmptySet:
            raise ValueError("shifted_odd.local_domain_empty")
    return {
        "definition": original,
        "relation_scope_ast": scope_ast,
        "domains": domains,
        "odd": odd,
        "values": values,
        "declarations": declarations,
        "extrema": extrema,
        "explicit": explicit,
        "refs": sorted(refs),
    }


def combine(ast, argument=X, symbolic_coefficients=False):
    """Read the original tree, retaining zero-coefficient calls for domain checks elsewhere."""
    if not _function_calls(ast):
        return {}, scalar(ast, argument)
    if ast[0] == "function_call":
        return {(ast[1][1], scalar(ast[2], argument)): sp.S.One}, sp.S.Zero
    if ast[0] == "neg":
        t, c = combine(ast[1], argument, symbolic_coefficients)
        return {k: -v for k, v in t.items()}, -c
    if ast[0] in ("+", "-"):
        t, c = combine(ast[1], argument, symbolic_coefficients)
        u, e = combine(ast[2], argument, symbolic_coefficients)
        sign = 1 if ast[0] == "+" else -1
        for k, v in u.items():
            t[k] = exact_budget(t.get(k, 0) + sign * v)
        return t, exact_budget(c + sign * e)
    if ast[0] in ("*", "/"):
        left, right = ast[1:]
        if ast[0] == "*" and not _function_calls(left):
            left, right = right, left
        if _function_calls(right):
            raise ValueError("shifted_odd.nonlinear_value_relation")
        factor = scalar(right, argument)
        if not symbolic_coefficients and factor.free_symbols:
            raise ValueError("shifted_odd.symbolic_weight")
        if ast[0] == "/":
            if factor == 0 or factor.free_symbols:
                raise ValueError("shifted_odd.divisor_unsupported")
            factor = 1 / factor
        t, c = combine(left, argument, symbolic_coefficients)
        return {k: exact_budget(factor * v) for k, v in t.items()}, exact_budget(
            factor * c
        )
    raise ValueError("shifted_odd.linear_target_required")


def targets(d):
    goal = d["goal_ast"]
    blocks = (
        goal["terms"] if goal["kind"] == "finite_sum" else [{"target": goal["target"]}]
    )
    out = []
    for i, b in enumerate(blocks):
        indices = range(b["lower"], b["upper"] + 1) if "index" in b else [None]
        if len(indices) + len(out) > 4096 or (
            "index" in b
            and (
                b["lower"] > b["upper"] or max(abs(b["lower"]), abs(b["upper"])) > 10000
            )
        ):
            raise ValueError("shifted_odd.sum_budget")
        for j in indices:
            ast = (
                _substitute(b["target"], b["index"], sp.Integer(j))
                if j is not None
                else b["target"]
            )
            _budget(ast)
            out.append({"block": i, "index": j, "ast": ast})
    if (
        goal["kind"] != "finite_sum"
        and sum(len(_function_calls(r["ast"])) for r in out) > 32
    ):
        raise ValueError("shifted_odd.call_budget")
    return out


def system(d, *, evidence=None, symbolic_parameter=False):
    sources = parse_sources(d)
    definition = sources["definition"]
    ast, refs = definition["ast"], sources["refs"]
    originals = targets(d)
    calls = [c for r in originals for c in _function_calls(r["ast"])]
    calls += [c for r in sources["values"] for c in _function_calls(r["ast"])]
    if any(c[1][1] not in refs for c in calls):
        raise ValueError("shifted_odd.other_function")
    maps, constraints, ident, existence = [], [], None, None
    if sources["explicit"]:
        ref = ast[1][1]
        if evidence is None:
            ident = identity(
                ast[2], sources["domains"].get(ref), ref, definition["source_ref"]
            )
        else:
            ident = evidence["identity"]
            if not verify_identity(
                ast[2],
                sources["domains"].get(ref),
                ref,
                definition["source_ref"],
                ident,
            ):
                raise ValueError("shifted_odd.identity_certificate_invalid")
        domain, K = ident["domain"], ident["K"]
        if sources["extrema"]:
            if K.free_symbols:
                raise ValueError("shifted_odd.target_parameter_not_eliminated")
            if (
                ident["expression"] is None
                or sources["values"]
                or not isinstance(domain, sp.Interval)
                or domain.left_open
                or domain.right_open
                or not (domain.start.is_finite and domain.end.is_finite)
            ):
                raise ValueError("shifted_odd.attained_extrema_required")
            bound = sources["extrema"]
            if len(bound) != 2 or {a[1] for a in bound.values()} != {"min", "max"}:
                raise ValueError("shifted_odd.same_extrema_pair_required")
            for e in bound.values():
                c = e[3]
                if (
                    e[2]
                    or c[0] != "function_call"
                    or c[1][1] != ref
                    or c[2][0] != "ref"
                    or c[2][2] != "scalar"
                ):
                    raise ValueError("shifted_odd.extrema_function_required")
            expected = ["+", *[["ref", k, "scalar"] for k in bound]]
            goal = d["goal_ast"].get("target")
            if goal not in (expected, ["+", expected[2], expected[1]]):
                raise ValueError("shifted_odd.extrema_sum_required")
            return {
                "version": VERSION,
                "description": deepcopy(d),
                "identity": ident,
                "existence": None,
                "domain": domain,
                "K": K,
                "maps": [],
                "groups": originals,
                "bases": [],
                "rows": [],
                "rhs": [],
                "target": [],
                "constant": K,
                "extrema": deepcopy(bound),
            }
        symbols = (
            set().union(*(scalar(c[2]).free_symbols for c in calls)) if calls else set()
        )
        if len(symbols) > 1:
            raise ValueError("shifted_odd.symbolic_input_budget")
        symbol = next(iter(symbols), None)
        equations = []
        for r in sources["values"]:
            a = r["ast"]
            if a[1][0] != "function_call" or _function_calls(a[2]):
                raise ValueError("shifted_odd.explicit_value_equation_required")
            q, v = scalar(a[1][2]), scalar(a[2])
            if v.free_symbols:
                raise ValueError("shifted_odd.symbolic_known_value_unsupported")
            if q.free_symbols:
                equations.append([q, v])
            else:
                if domain.contains(q) is not sp.true:
                    raise ValueError("shifted_odd.conditions_inconsistent")
                residual = sp.cancel(
                    (
                        ident["expression"].subs(X, q)
                        if ident["expression"] is not None
                        else function_cells.evaluate(ast[2], q)[1]
                    )
                    - v
                )
                if residual.free_symbols:
                    # The condition may constrain a coefficient; it is not a contradiction.
                    raise ValueError("shifted_odd.coefficient_conditions_unsupported")
                if residual != 0:
                    raise ValueError("shifted_odd.conditions_inconsistent")
        if symbol is not None:
            if ident["expression"] is None or ident["parameters"] or not equations:
                raise ValueError("shifted_odd.symbolic_input_witness_required")
            if evidence is None:
                existence = compatibility(
                    ident["expression"], domain, equations, symbol
                )
            else:
                existence = evidence["existence"]
                if not verify_compatibility(
                    ident["expression"], domain, equations, symbol, existence
                ):
                    raise ValueError("shifted_odd.common_root_certificate_invalid")

        def read(ref, q):
            if q.free_symbols:
                # Domain legality for every common root, not just a convenient witness.
                if q not in [v for p, _ in equations for v in (p, -p)]:
                    raise ValueError("shifted_odd.symbolic_pair_required")
                for p, v in equations:
                    if q == p:
                        return {}, v
                    if q == -p:
                        return {}, K - v
            if domain.contains(q) is not sp.true:
                raise ValueError("shifted_odd.input_outside_domain")
            v = (
                sp.cancel(ident["expression"].subs(X, q))
                if ident["expression"] is not None
                else sp.simplify(function_cells.evaluate(ast[2], q)[1])
            )
            return {}, v
    else:
        odd = sources["odd"][0]
        f = next(r for r in refs if r != odd)
        equation = ["-", ["function_call", ast[1], ARGUMENT], ast[2]]
        coeffs, C = combine(equation, symbolic_coefficients=True)
        A, B = coeffs.get((f, X), sp.S.Zero), coeffs.get((odd, X), sp.S.Zero)
        if not symbolic_parameter and any(v.free_symbols for v in (A, B, C)):
            if sources["relation_scope_ast"] is not None:
                raise ValueError("shifted_odd.local_parameter_unsupported")
            return parameter_system(
                d, sources, originals, A, B, C, f, odd, evidence=evidence
            )
        sets = {ref: fixed_set(s) for ref, s in sources["domains"].items()}
        local = sources["relation_scope_ast"] is not None
        if not local and sets:
            if any(s != next(iter(sets.values())) for s in sets.values()):
                raise ValueError("shifted_odd.same_domain_required")
            sets = {ref: next(iter(sets.values())) for ref in refs}
        domain = sets.get(f)
        odd_domain = sets.get(odd)
        if any(s == sp.S.EmptySet for s in sets.values()) or (
            odd_domain is not None and odd_domain != reflect_set(odd_domain)
        ):
            raise ValueError("shifted_odd.domain_not_symmetric")
        scope = fixed_set(sources["relation_scope_ast"]) if local else domain
        if local and any(scope.is_subset(s) is not True for s in sets.values()):
            raise ValueError("shifted_odd.relation_outside_domain")
        pair_scope = scope & reflect_set(scope) if scope is not None else None
        if A == 0 and C != 0 and (B == 0 or not local or pair_scope != sp.S.EmptySet):
            raise ValueError("shifted_odd.conditions_inconsistent")
        K = -2 * C / A if A != 0 else None
        known = {
            (c[1][1], scalar(c[2]))
            for r in sources["values"]
            for c in _function_calls(r["ast"])
        }

        def related(q):
            return not local or scope.contains(q) is sp.true

        def read(ref, q):
            if q.free_symbols or q.is_real is not True:
                raise ValueError("shifted_odd.numeric_input_required")
            D = sets.get(ref)
            if D is not None:
                if D.contains(q) is not sp.true:
                    raise ValueError("shifted_odd.input_outside_domain")
            elif not (
                (ref, q) in known
                or (not local and any(p in (q, -q) for _, p in known))
                or (local and related(q))
                or (ref == odd and (odd, -q) in known)
            ):
                raise ValueError("shifted_odd.input_membership_unproved")
            if ref == f and (A == 0 or not related(q)):
                return {(f, q): sp.S.One}, sp.S.Zero
            factor, offset = (sp.S.One, sp.S.Zero) if ref == odd else (-B / A, -C / A)
            if A == 0 and B != 0 and (related(q) or related(-q)):
                return {}, -C / B if related(q) else C / B
            if q == 0:
                return {}, offset
            return {(odd, abs(q)): factor * sp.sign(q)}, offset

    # Validate every printed call, including cancelled or zero-weight calls.
    for c in calls:
        q = scalar(c[2])
        t, v = read(c[1][1], q)
        maps.append(
            {
                "function": c[1][1],
                "input": q,
                "terms": [[r, p, k] for (r, p), k in t.items()],
                "constant": v,
            }
        )

    def reduce(a):
        terms, c = combine(a)
        out = {}
        for (ref, q), k in terms.items():
            t, v = read(ref, q)
            c = exact_budget(c + k * v)
            for key, w in t.items():
                out[key] = exact_budget(out.get(key, 0) + k * w)
        return {
            k: sp.cancel(v) for k, v in out.items() if sp.cancel(v) != 0
        }, sp.cancel(c)

    for row in sources["values"]:
        a = row["ast"]
        t, c = reduce(["-", a[1], a[2]])
        constraints.append((t, -c))
    groups = [reduce(r["ast"]) for r in originals]
    total = {}
    for row, _ in groups:
        for key, v in row.items():
            total[key] = exact_budget(sp.cancel(total.get(key, 0) + v))
    total = {k: v for k, v in total.items() if v != 0}
    keys = sorted({k for row, _ in constraints for k in row} | set(total), key=str)
    if len(keys) > 32:
        raise ValueError("shifted_odd.unknown_budget")
    vector = lambda row: [sp.cancel(row.get(k, 0)) for k in keys]
    rows = [vector(r) for r, _ in constraints]
    rhs = [b for _, b in constraints]
    target = vector(total)
    constant = sp.S.Zero
    for _, b in groups:
        constant = exact_budget(sp.cancel(constant + b))
    if not symbolic_parameter and any(
        v.free_symbols for v in [*rhs, *target, constant]
    ):
        raise ValueError("shifted_odd.target_parameter_not_eliminated")
    return {
        "version": VERSION,
        "description": deepcopy(d),
        "identity": ident,
        "existence": existence,
        "domain": domain,
        "relation_scope": scope if not sources["explicit"] else None,
        "K": K,
        "maps": maps,
        "groups": originals,
        "bases": [list(k) for k in keys],
        "rows": rows,
        "rhs": rhs,
        "target": target,
        "constant": constant,
        "extrema": None,
    }


def parameter_system(d, sources, originals, A, B, C, f, odd, *, evidence=None):
    """Partition both affine coefficients before eliminating either function."""
    params = set().union(*(v.free_symbols for v in (A, B, C)))
    if len(params) != 1:
        raise ValueError("shifted_odd.parameter_contract")
    p = next(iter(params))
    known = {}
    for row in sources["values"]:
        a = row["ast"]
        if a[1][0] != "function_call" or _function_calls(a[2]):
            raise ValueError("shifted_odd.parameter_known_values_required")
        ref, q, v = a[1][1][1], scalar(a[1][2]), scalar(a[2])
        if q.free_symbols or v.free_symbols:
            raise ValueError("shifted_odd.parameter_numeric_values_required")
        if (ref, q) in known and known[ref, q] != v:
            raise ValueError("shifted_odd.conditions_inconsistent")
        known[ref, q] = v
    equations = []
    for (ref, q), v in list(known.items()):
        if ref == odd:
            if (q == 0 and v != 0) or ((odd, -q) in known and known[odd, -q] != -v):
                raise ValueError("shifted_odd.conditions_inconsistent")
            known[odd, -q] = -v
    for (ref, q), v in known.items():
        if ref != f:
            continue
        if (f, -q) in known:
            equations.append(sp.expand(A * (v + known[f, -q]) + 2 * C))
        if (odd, q) in known:
            equations.append(sp.expand(A * v + B * known[odd, q] + C))
        if q == 0:
            equations.append(sp.expand(A * v + C))
    allowed = sp.S.Reals

    def zero_set(poly):
        poly = sp.Poly(poly, p, extension=True)
        for coefficient in poly.all_coeffs():
            function_cells.exact_point(exact_budget(coefficient))
        if poly.is_zero:
            return sp.S.Reals
        if poly.degree() == 0:
            return sp.S.EmptySet
        if poly.degree() != 1:
            raise ValueError("shifted_odd.parameter_degree_budget")
        return sp.FiniteSet(
            function_cells.exact_point(exact_budget(-poly.nth(0) / poly.nth(1)))
        )

    for e in equations:
        allowed &= zero_set(e)
    zero = zero_set(A)
    odd_zero = zero_set(B)
    cuts = sp.Union(*(z for z in (zero, odd_zero) if isinstance(z, sp.FiniteSet)))
    partition = [sp.S.Reals - cuts, *(sp.FiniteSet(v) for v in sorted(cuts))]
    cases = []
    for part in partition:
        extra = []
        a_zero = part.is_subset(zero) is True
        b_zero = part.is_subset(odd_zero) is True
        if a_zero:
            # B*g+C=0 on a nonempty symmetric domain requires C=0. Only
            # nonzero B forces g=0; A=B=C=0 leaves both functions unconstrained.
            extra.append(C)
            if not b_zero:
                extra.extend(B * v + C for (ref, _), v in known.items() if ref == odd)
        elif b_zero:
            # f is constant here. Pair sums alone do not check each known value.
            extra.extend(A * v + C for (ref, _), v in known.items() if ref == f)
        admitted = part & allowed
        for e in extra:
            admitted &= zero_set(e)
        cases.append({"scope": part, "equations": extra, "allowed": admitted})
    allowed = sp.Union(*(case["allowed"] for case in cases))
    parameter_goal = (
        len(originals) == 1
        and not _function_calls(originals[0]["ast"])
        and scalar(originals[0]["ast"]) == p
    )

    # Domain obligations are independent of the coefficient parameter.
    sets = [fixed_set(a) for a in sources["domains"].values()]
    if sets and (
        any(a != sets[0] for a in sets)
        or sets[0] == sp.S.EmptySet
        or reflect_set(sets[0]) != sets[0]
    ):
        raise ValueError("shifted_odd.domain_not_symmetric")
    domain = sets[0] if sets else None
    if domain is not None and any(domain.contains(q) is not sp.true for _, q in known):
        raise ValueError("shifted_odd.input_outside_domain")
    info = {
        "symbol": p,
        "coefficient": A,
        "odd_coefficient": B,
        "constant": C,
        "equations": equations,
        "cases": cases,
        "allowed": allowed,
        "zero_branch": allowed & zero,
        "nonzero_branch": allowed - zero,
        "is_parameter_target": parameter_goal,
    }
    branches = []

    def rewritten_at(value):
        def replace(a):
            if isinstance(a, list):
                if a[:2] == ["ref", str(p)]:
                    from .symmetry_value_math import _literal

                    return _literal(value)
                return [replace(z) for z in a]
            return a

        rewritten = deepcopy(d)
        rewritten["given_entries"] = [
            {**r, "ast": replace(r["ast"])} for r in d["given_entries"]
        ]
        rewritten["goal_ast"] = replace(d["goal_ast"])
        return rewritten

    if not parameter_goal:
        if allowed == sp.S.EmptySet:
            raise ValueError("shifted_odd.conditions_inconsistent")
        pieces = [case["allowed"] for case in cases if case["allowed"] != sp.S.EmptySet]
        for index, part in enumerate(pieces):
            single = isinstance(part, sp.FiniteSet) and len(part) == 1
            rewritten = rewritten_at(next(iter(part))) if single else d
            supplied = (
                evidence["parameter"]["branches"][index]["model"] if evidence else None
            )
            if single:
                sub = solve(rewritten) if supplied is None else supplied
                if supplied is not None and not verify(rewritten, sub):
                    raise ValueError("shifted_odd.parameter_target_certificate_invalid")
            else:
                sub = system(rewritten, symbolic_parameter=True, evidence=supplied)
                if supplied is None:
                    sub["proof"] = symmetry_linear.certificate(
                        sub["rows"],
                        len(sub["bases"]),
                        sub["rhs"],
                        sub["target"],
                        sub["constant"],
                    )
                else:
                    if set(supplied) != {*sub, "proof"} or any(
                        sub[k] != supplied[k] for k in sub
                    ):
                        raise ValueError(
                            "shifted_odd.parameter_target_certificate_invalid"
                        )
                    sub["proof"] = supplied["proof"]
                if not _verify_symbolic_linear(sub, p, part):
                    raise ValueError("shifted_odd.parameter_linear_unproved")
            branches.append({"scope": part, "model": sub})
        proof = _parameter_conclusion(
            branches, p, supplied=evidence.get("proof") if evidence else None
        )
    else:
        value = (
            next(iter(allowed))
            if isinstance(allowed, sp.FiniteSet) and len(allowed) == 1
            else allowed
        )
        proof = {
            "status": "determined",
            "value": value,
            "multipliers": None,
            "witnesses": [],
        }
    info["branches"] = branches
    return {
        "version": VERSION,
        "description": deepcopy(d),
        "identity": None,
        "existence": None,
        "domain": domain,
        "K": None,
        "maps": [],
        "groups": originals,
        "bases": [],
        "rows": [],
        "rhs": [],
        "target": [],
        "constant": sp.S.Zero,
        "extrema": None,
        "parameter": info,
        "proof": proof,
    }


def _verify_symbolic_linear(m, p, scope):
    proof = m["proof"]
    rows, rhs, target = m["rows"], m["rhs"], m["target"]
    if set(proof) != {"status", "value", "multipliers", "witnesses"}:
        return False
    witnesses = proof["witnesses"]
    if not witnesses or any(len(w) != len(target) for w in witnesses):
        return False
    scalars = [
        *rhs,
        *target,
        m["constant"],
        *[v for row in rows for v in row],
        *[v for w in witnesses for v in w],
    ]
    multipliers = proof["multipliers"]
    if isinstance(multipliers, list):
        scalars += multipliers
    if proof["value"] is not None:
        scalars.append(proof["value"])
    for v in scalars:
        if (
            isinstance(v, bool)
            or not isinstance(v, (int, sp.Expr))
            or sp.sympify(v).free_symbols - {p}
        ):
            return False
        _, den = sp.fraction(sp.cancel(v))
        if sp.solveset(den, p, domain=scope) != sp.S.EmptySet:
            return False
    zero = lambda v: sp.cancel(v) == 0
    if any(
        not zero(sum(a * b for a, b in zip(row, w)) - v)
        for w in witnesses
        for row, v in zip(rows, rhs)
    ):
        return False
    if proof["status"] == "determined":
        return (
            len(witnesses) == 1
            and isinstance(multipliers, list)
            and len(multipliers) == len(rows)
            and all(
                zero(
                    sum(multipliers[i] * rows[i][j] for i in range(len(rows)))
                    - target[j]
                )
                for j in range(len(target))
            )
            and zero(
                sum((a * b for a, b in zip(multipliers, rhs)), m["constant"])
                - proof["value"]
            )
        )
    return (
        proof["status"] == "underdetermined"
        and proof["value"] is None
        and multipliers is None
        and len(witnesses) == 2
        and not zero(sum(a * (b - c) for a, b, c in zip(target, *witnesses)))
    )


def _parameter_conclusion(branches, p, *, supplied=None):
    values = [b["model"]["proof"]["value"] for b in branches]
    if (
        all(v is not None and not sp.sympify(v).free_symbols for v in values)
        and len(set(values)) == 1
    ):
        return {
            "status": "determined",
            "value": values[0],
            "multipliers": None,
            "witnesses": [],
        }

    def valid(w):
        if not isinstance(w, dict) or set(w) != {
            "branch",
            "parameter",
            "basis_values",
            "value",
        }:
            return False
        i, t = w["branch"], w["parameter"]
        if (
            not isinstance(i, int)
            or not 0 <= i < len(branches)
            or not isinstance(t, sp.Expr)
        ):
            return False
        branch = branches[i]
        m = branch["model"]
        v = w["basis_values"]
        if branch["scope"].contains(t) is not sp.true or len(v) != len(m["target"]):
            return False
        try:
            for x in [t, *v]:
                function_cells.exact_point(exact_budget(sp.sympify(x)))
        except (ValueError, TypeError, AttributeError):
            return False
        at = lambda x: sp.cancel(sp.sympify(x).subs(p, t))
        return (
            all(
                sp.cancel(sum(at(a) * b for a, b in zip(row, v)) - at(r)) == 0
                for row, r in zip(m["rows"], m["rhs"])
            )
            and at(m["constant"]) + sum(at(a) * b for a, b in zip(m["target"], v))
            == w["value"]
        )

    if supplied is not None:
        ws = supplied.get("witnesses", [])
        if (
            set(supplied) == {"status", "value", "multipliers", "witnesses"}
            and supplied["status"] == "underdetermined"
            and supplied["value"] is None
            and supplied["multipliers"] is None
            and len(ws) == 2
            and all(valid(w) for w in ws)
            and ws[0]["value"] != ws[1]["value"]
        ):
            return supplied
        raise ValueError("shifted_odd.parameter_witness_invalid")
    witnesses = []
    for index, branch in enumerate(branches):
        m = branch["model"]
        scope = branch["scope"]
        points = (
            list(scope)
            if isinstance(scope, sp.FiniteSet)
            else [sp.Rational(n) for n in range(-4, 5)]
        )
        for t in points:
            if scope.contains(t) is not sp.true:
                continue
            at = lambda x, t=t: sp.cancel(sp.sympify(x).subs(p, t))
            for basis in m["proof"]["witnesses"]:
                basis = [at(v) for v in basis]
                value = at(m["constant"]) + sum(
                    at(a) * b for a, b in zip(m["target"], basis)
                )
                witness = {
                    "branch": index,
                    "parameter": t,
                    "basis_values": basis,
                    "value": value,
                }
                if valid(witness) and value not in [w["value"] for w in witnesses]:
                    witnesses.append(witness)
                if len(witnesses) == 2:
                    return {
                        "status": "underdetermined",
                        "value": None,
                        "multipliers": None,
                        "witnesses": witnesses,
                    }
    raise ValueError("shifted_odd.parameter_countermodels_unproved")


def solve(d):
    m = system(d)
    if "parameter" not in m:
        m["proof"] = symmetry_linear.certificate(
            m["rows"], len(m["bases"]), m["rhs"], m["target"], m["constant"]
        )
    return m


def _verify_exact_linear(m):
    """T6 permits exact quadratic values without widening the shared rational contract."""
    proof = m["proof"]
    if not isinstance(proof, dict) or set(proof) != {
        "status",
        "value",
        "multipliers",
        "witnesses",
    }:
        return False
    rows, rhs, target = m["rows"], m["rhs"], m["target"]
    witnesses, multipliers = proof["witnesses"], proof["multipliers"]
    if (
        not isinstance(witnesses, list)
        or not witnesses
        or any(not isinstance(w, list) or len(w) != len(target) for w in witnesses)
    ):
        return False
    values = [
        *rhs,
        *target,
        m["constant"],
        *[v for r in rows for v in r],
        *[v for w in witnesses for v in w],
    ]
    if isinstance(multipliers, list):
        values += multipliers
    if proof["value"] is not None:
        values.append(proof["value"])
    for v in values:
        if isinstance(v, bool) or not isinstance(v, (int, sp.Expr)):
            return False
        function_cells.exact_point(exact_budget(sp.sympify(v)))
    zero = lambda v: sp.simplify(v) == 0
    if any(
        not zero(sum(a * b for a, b in zip(row, w)) - b)
        for w in witnesses
        for row, b in zip(rows, rhs)
    ):
        return False
    if proof["status"] == "determined":
        return (
            len(witnesses) == 1
            and isinstance(multipliers, list)
            and len(multipliers) == len(rows)
            and all(
                zero(sum(multipliers[i] * rows[i][j] for i in range(len(rows))) - t)
                for j, t in enumerate(target)
            )
            and zero(
                sum((a * b for a, b in zip(multipliers, rhs)), m["constant"])
                - proof["value"]
            )
        )
    return (
        proof["status"] == "underdetermined"
        and proof["value"] is None
        and multipliers is None
        and len(witnesses) == 2
        and not zero(sum(a * (b - c) for a, b, c in zip(target, *witnesses)))
    )


def verify(d, m):
    try:
        actual = system(d, evidence=m)
        if "parameter" in actual:
            return m == actual
        return (
            set(m) == {*actual, "proof"}
            and all(m[k] == v for k, v in actual.items())
            and _verify_exact_linear(m)
        )
    except (
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        AttributeError,
        ZeroDivisionError,
        NotImplementedError,
    ):
        return False
