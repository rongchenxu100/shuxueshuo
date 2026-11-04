"""Conservative proofs over bound notation; no answer solving or text matching."""

import itertools
import json
from copy import deepcopy
from hashlib import sha256

import sympy as sp

from .algebra import scalar_expression
from .identity import revision
from .notation_compile import NotationValidator
from .notation_implication import equivalent as prove_equivalent
from .notation_implication import fact_proof
from .notation_parser import NotationError
from .proof_budget import ProofBudget


def key(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def unique(items):
    return [json.loads(s) for s in sorted({key(x) for x in items})]


def bounded_expand(expression):
    """Bound expansion before SymPy materializes polynomial combinations."""

    def terms(value):
        if value.is_Add:
            count = sum(terms(x) for x in value.args)
        elif value.is_Mul:
            count = 1
            for argument in value.args:
                count *= terms(argument)
                if count > 4096:
                    break
        elif value.is_Pow and value.exp.is_Integer and value.exp > 0:
            base = terms(value.base)
            # Avoid even constructing a huge Python integer for nested powers.
            count = 4097 if base > 1 and value.exp > 12 else base ** int(value.exp)
        else:
            # Still inspect bases of radicals and denominators.
            count = max((terms(x) for x in value.args), default=1)
        if count > 4096:
            raise NotationError("semantic.expansion_limit")
        return count

    if sp.count_ops(expression) > 512:
        raise NotationError("semantic.operation_limit")
    terms(expression)
    return sp.expand(expression)


class Canonical:
    def __init__(self, aliases=None):
        self.aliases = aliases or {}
        self.atoms = {}
        self.obligations = []
        self.functions = {}
        self.algebra = {}

    def expr(self, ast, depth=0):
        if depth > 40:
            raise NotationError("semantic.depth_limit")
        kind = ast[0]
        expr = lambda x: self.expr(x, depth + 1)
        if kind == "infinity":
            raise NotationError("semantic.infinity_outside_interval")
        if kind == "number":
            return scalar_expression(ast[1])
        if kind == "certified_cut_ratio":
            # The certificate proves both cut lengths positive. Reversing the
            # first endpoint pair is safely represented by a reciprocal.
            first = self.tree(ast[1])[1:]
            canonical = self.tree(ast)
            code = sha256(key(canonical).encode()).hexdigest()
            ratio = sp.Symbol("n_" + code, positive=True)
            return ratio if first == canonical[1][1:] else 1 / ratio
        if kind == "neg":
            return -expr(ast[1])
        if kind == "degrees":
            # Angle units are checked before canonicalization; 45° is exact.
            return expr(ast[1])
        if kind in ("+", "-", "*", "/", "^"):
            a, b = expr(ast[1]), expr(ast[2])
            if kind == "+":
                return a + b
            if kind == "-":
                return a - b
            if kind == "*":
                if len(str(a)) * len(str(b)) > 100000:
                    raise NotationError("semantic.expansion_limit")
                return a * b
            if kind == "/":
                if b == 0:
                    raise NotationError("algebra.zero_denominator")
                if b.is_zero is not False:
                    self.obligations.append(["nonzero_denominator", sp.srepr(b)])
                return a / b
            if not b.is_Integer or abs(b) > 12:
                raise NotationError("algebra.power_limit")
            if (
                a.is_Rational
                and max(int(a.p).bit_length(), int(a.q).bit_length())
                * max(1, abs(int(b)))
                > 4096
            ):
                raise NotationError("algebra.numeric_limit")
            if a == 0 and b < 0:
                raise NotationError("algebra.zero_denominator")
            if b < 0 and a.is_zero is not False:
                self.obligations.append(["nonzero_denominator", sp.srepr(a)])
            return a**b
        if kind == "call" and ast[1] == "sqrt":
            value = expr(ast[2])
            if value.is_negative:
                raise NotationError("algebra.nonreal")
            if value.is_nonnegative is not True:
                self.obligations.append(["nonnegative_radicand", sp.srepr(value)])
            return sp.sqrt(value)
        if kind == "function_call":
            target = self.tree(ast[1])
            if key(target) not in self.functions:
                raise NotationError("semantic.unresolved_function")
            body = self.functions[key(target)]
            argument = ast[2]

            def substitute(x):
                if x == ["bound", "function_argument"]:
                    return argument
                return [substitute(v) if isinstance(v, list) else v for v in x]

            return self.expr(substitute(body), depth + 1)
        atom = self.tree(ast)
        code = sha256(key(atom).encode()).hexdigest()
        self.atoms[code] = atom
        return sp.Symbol("n_" + code, real=True)

    def math(self, ast):
        expr = self.expr(ast)
        if sp.count_ops(expr) > 512:
            raise NotationError("semantic.operation_limit")
        return sp.srepr(bounded_expand(expr))

    def tree(self, ast):
        kind = ast[0]
        if kind == "ref":
            return ["ref", self.aliases.get(ast[1], ast[1]), ast[2]]
        if kind == "certified_cut_ratio":
            return [
                kind,
                *[
                    ["endpoints", *sorted([self.tree(p) for p in pair[1:]], key=key)]
                    for pair in ast[1:]
                ],
            ]
        if kind == "extremum":
            return ["extremum", ast[1], self.math(ast[3])]
        if kind == "call":
            name = ast[1]
            args = [self.tree(x) for x in ast[2:]]
            if name in ("length", "line", "segment", "midpoint", "triangle"):
                args.sort(key=key)
            if name == "angle":
                ends = sorted([args[0], args[2]], key=key)
                args = [ends[0], args[1], ends[1]]
            if name in ("square", "parallelogram", "quadrilateral"):
                options = [args[i:] + args[:i] for i in range(len(args))]
                reverse = list(reversed(args))
                options += [reverse[i:] + reverse[:i] for i in range(len(args))]
                args = min(options, key=key)
            if name in ("bisects", "cut_ratio"):
                # Second line orientation is irrelevant; first ratio direction is not.
                args[1] = ["endpoints", *sorted(args[1][1:], key=key)]
                if name == "bisects":
                    args[0] = ["endpoints", *sorted(args[0][1:], key=key)]
            return ["call", name, *args]
        if kind in (
            "+",
            "-",
            "*",
            "/",
            "^",
            "neg",
            "number",
            "degrees",
            "function_call",
        ):
            # tree is only used for geometric arguments and inert scalar atoms.
            return ["math", self.math(ast)]
        if kind in ("∩", "set"):
            return [kind, *sorted([self.tree(x) for x in ast[1:]], key=key)]
        if kind == "tuple":
            return ["tuple", *[self.math(x) for x in ast[1:]]]
        if kind == "interval":
            if ast[3] == ["infinity", -1] and ast[4] == ["infinity", 1]:
                return ["real"]  # (-∞,+∞) and ℝ are the same domain.
            return [
                kind,
                ast[1],
                ast[2],
                *[
                    self.tree(x) if x[0] == "infinity" else self.math(x)
                    for x in ast[3:]
                ],
            ]
        return [self.tree(v) if isinstance(v, list) else v for v in ast]

    def fact(self, ast):
        kind = ast[0]
        if kind == "definition_prose":
            return ["and"]
        if kind == "default_domain" or (kind == "∈" and self.tree(ast[2]) == ["real"]):
            # x∈ℝ and x∈(-∞,+∞) only restate a real variable's domain. For any
            # other expression (sqrt(a-2), 1/0) membership adds its own
            # well-definedness requirement and must stay a condition.
            if ast[1][0] in ("ref", "bound"):
                return ["and"]
            return ["∈", self.tree(ast[1]), ["real"]]
        if kind == "role":
            # Moving tags are optional extraction hints, fixed remains a constraint.
            return (
                ["role", self.tree(ast[1]), "fixed"] if ast[2] == "fixed" else ["and"]
            )
        if kind in ("and", "or"):
            return [kind, *[self.fact(x) for x in ast[1:]]]
        if kind == "quantifier":
            return [kind, ast[1], self.tree(ast[3]), self.logic([ast[4]])]
        if kind in ("curve_definition", "function_definition"):
            return [kind, self.tree(ast[1]), self.math(ast[2])]
        if kind in ("=", "!=", "<", "<=", ">", ">="):
            from .notation_compile import typecheck

            types = [typecheck(x) for x in ast[1:]]
            if all(t in ("scalar", "length", "angle", "area") for t in types):
                value = self.expr(ast[1]) - self.expr(ast[2])
                if kind in (">", ">="):
                    kind = {">": "<", ">=": "<="}[kind]
                    value = -value
                value = sp.factor_terms(bounded_expand(value))
                coefficient, rest = value.as_coeff_Mul()
                if kind in ("=", "!=") and coefficient != 0:
                    value = rest
                    canonical = min(sp.srepr(value), sp.srepr(-value))
                else:
                    if coefficient.is_positive:
                        value = rest
                    canonical = sp.srepr(value)
                result = ["relation", kind, canonical]
                self.algebra[key(result)] = value
                return result
            args = [self.tree(x) for x in ast[1:]]
            if kind in ("=", "!="):
                args.sort(key=key)
            return [kind, *args]
        return self.tree(ast)

    def logic(self, facts):
        def dnf(x):
            if x[0] == "or":
                result = [clause for child in x[1:] for clause in dnf(child)]
            elif x[0] == "and":
                result = [[]]
                for child in x[1:]:
                    alternatives = dnf(child)
                    if len(result) * len(alternatives) > 4096:
                        raise NotationError("logic.expansion_limit")
                    result = [a + b for a in result for b in alternatives]
            else:
                result = [[x]]
            if len(result) > 4096:
                raise NotationError("logic.expansion_limit")
            return result

        return unique([unique(c) for c in dnf(["and", *[self.fact(x) for x in facts]])])

    def scope(self, scope):
        inherited = dict(self.functions)
        for ast in scope["facts"]:
            if ast[0] == "function_definition":
                self.functions[key(self.tree(ast[1]))] = ast[2]
        facts = self.logic(scope["facts"])
        goals = []
        for g in scope["goals"]:
            from .notation_compile import typecheck
            from .notation_evaluation import canonical_evaluation, is_evaluation_goal

            if 'pricing' in g:
                goals.append({k: deepcopy(v) for k, v in g.items() if k != 'target'})
                continue
            if is_evaluation_goal(g) and 'relation' not in g:
                goals.append(canonical_evaluation(g, self.aliases))
                continue
            if g['kind'] in ('find_monotonic_intervals', 'prove_monotonicity_on_interval', 'select_function_graph', 'draw_function_graph', 'solve_graph_inequality'):
                # Include the complete source facts and ordered option identities.
                goals.append({key: deepcopy(value) for key, value in g.items() if key != 'target'})
                continue
            if g['kind'] in ('select_range_domain', 'find_extrema_expression'):
                from .notation_range_tasks import canonical_range_task

                goals.append(canonical_range_task(g))
                continue
            if g['kind'] == 'find_function_formula' or (g['kind'] in ('find_value', 'find_range') and 'relation' in g):
                from .notation_function_formula import canonical_function_formula

                goals.append(canonical_function_formula(g))
                continue
            if g['kind'] == 'find_translation_range':
                from .notation_translation_range import canonical_translation_range

                goals.append(canonical_translation_range(g))
                continue
            if g['kind'] == 'compare_functions':
                from .notation_function_comparison import canonical_comparison

                goals.append(canonical_comparison(g))
                continue
            if g['kind'] in ('find_abstract_domain', 'find_abstract_domain_parameter', 'find_abstract_range'):
                from .notation_abstract_domain import canonical_abstract_domain

                goals.append(canonical_abstract_domain(g))
                continue
            target = (
                self.math(g["target"])
                if typecheck(g["target"]) in ("scalar", "length", "angle", "area")
                else self.tree(g["target"])
            )
            goal = {"kind": g["kind"], "target": target}
            if 'answer_request' in g:
                goal['answer_request'] = deepcopy(g['answer_request'])
                goal['input_domain'] = self.tree(g.get('input_domain', ['real']))
            if g["kind"] == "find_domain":
                goal["input_domain"] = self.tree(g.get("input_domain", ["real"]))
            if g["kind"] == "match_domain":
                goal["parameter"] = self.tree(g["parameter"])
                goal["domain"] = self.tree(g["domain"])
            if g['kind'] == 'match_range':
                goal['function'] = self.tree(g['function'])
                goal['range'] = self.tree(g['range'])
            if "in_terms_of" in g:
                goal["in_terms_of"] = sorted(
                    [self.tree(x) for x in g["in_terms_of"]], key=key
                )
            goals.append(goal)
        # Wording is not semantic, but uncertainty type and scope must survive.
        result = {
            "facts": facts,
            "goals": sorted(goals, key=key),
            "uncertainties": sorted(x["kind"] for x in scope["uncertainties"]),
            "children": [self.scope(c) for c in scope["children"]],
        }
        self.functions = inherited
        return result


def canonical(report, aliases=None, *, compiler=None):
    compiler = compiler or Canonical(aliases)
    tree = compiler.scope(report.semantic_normalization.get("root", report.semantic))
    # Hash atoms encode complete bound geometry, not merely printed labels.
    return {
        "root": tree,
        "well_definedness": sorted({key(x) for x in compiler.obligations}),
    }


def alias_candidates(expected, actual):
    """Anchor existing names; try bounded, type/scope preserving alternate names."""
    groups = {}
    for obj in expected.semantic_normalization.get("objects", expected.objects):
        groups.setdefault((obj["scope"], obj["kind"]), [[], []])[0].append(obj)
    for obj in actual.semantic_normalization.get("objects", actual.objects):
        groups.setdefault((obj["scope"], obj["kind"]), [[], []])[1].append(obj)
    candidates = [{}]
    for (scope, kind), (left, right) in sorted(groups.items()):
        if len(left) != len(right):
            return
        anchors = {x["name"]: x for x in left}
        fixed = {
            x["ref"]: anchors[x["name"]]["ref"] for x in right if x["name"] in anchors
        }
        remaining_left = [x for x in left if x["ref"] not in fixed.values()]
        remaining_right = [x for x in right if x["ref"] not in fixed]
        if len(remaining_left) > 6:
            return
        variants = [
            {**fixed, **{a["ref"]: b["ref"] for a, b in zip(remaining_right, order)}}
            for order in itertools.islice(itertools.permutations(remaining_left), 256)
        ]
        candidates = [{**c, **v} for c in candidates for v in variants][:256]
    yield from candidates


def compare(expected, actual):
    left, right = (
        NotationValidator().validate(expected),
        NotationValidator().validate(actual),
    )
    return compare_reports(left, right)


def compare_roots(expected, actual):
    """Compare mathematical scopes independently of an extraction schema."""
    return compare_reports(
        NotationValidator().validate_root(expected),
        NotationValidator().validate_root(actual),
    )


def compare_reports(left, right):
    """Compare validated reports using the existing conservative proof engine."""
    if not left.ok or not right.ok:
        return {
            "ok": False,
            "classification": "invalid_notation",
            "expected_issues": left.issues,
            "actual_issues": right.issues,
        }
    # Expose target-projection certificates in acceptance reports as well as
    # compiled artifacts; raw candidates and source-review pointers stay intact.
    state_proofs = [
        {"side": side, **proof}
        for side, report in (("expected", left), ("actual", right))
        for proof in report.semantic_normalization.get("proofs", [])
        if proof["rule"] == "parameter_state_extremum_witness"
    ]
    try:
        left_compiler, right_compiler = Canonical(), Canonical()
        a, b = (
            canonical(left, compiler=left_compiler),
            canonical(right, compiler=right_compiler),
        )
        if a == b:
            return {
                "ok": True,
                "classification": "equivalent",
                "differences": [],
                **({"proofs": state_proofs} if state_proofs else {}),
            }
        budget = ProofBudget()
        proofs = prove_equivalent(
            a, b, {**left_compiler.algebra, **right_compiler.algebra}, budget
        )
        if proofs is not None:
            return {
                "ok": True,
                "classification": "equivalent",
                "differences": [],
                "proofs": [*state_proofs, *proofs],
            }
        for aliases in alias_candidates(left, right):
            compiler = Canonical(aliases)
            aliased = canonical(right, compiler=compiler)
            proofs = (
                []
                if a == aliased
                else prove_equivalent(
                    a, aliased, {**left_compiler.algebra, **compiler.algebra}, budget
                )
            )
            if proofs is not None:
                return {
                    "ok": True,
                    "classification": "equivalent",
                    "differences": [],
                    "aliases": aliases,
                    "proofs": [*state_proofs, *proofs],
                }
        differences, partial_proofs = [], []
        common_domain = a["well_definedness"] == b["well_definedness"]

        def walk(a, b, path):
            if a == b:
                return
            if path.endswith("/facts") and common_domain:
                proof = fact_proof(
                    a,
                    b,
                    {**left_compiler.algebra, **right_compiler.algebra},
                    budget,
                    path,
                )
                if proof is not None:
                    partial_proofs.append(proof)
                    return
            if isinstance(a, dict) and isinstance(b, dict):
                for k in sorted(set(a) | set(b)):
                    walk(a.get(k), b.get(k), path + "/" + k)
            elif (
                isinstance(a, list)
                and isinstance(b, list)
                and path.endswith("children")
                and len(a) == len(b)
            ):
                for i, (x, y) in enumerate(zip(a, b)):
                    walk(x, y, path + f"/{i}")
            else:
                differences.append({"path": path, "expected": a, "actual": b})

        walk(a, b, "")
        return {
            "ok": False,
            "classification": "not_proven_equivalent",
            "differences": differences,
            "proofs": [*state_proofs, *partial_proofs],
        }
    except (NotationError, ValueError, TypeError, RecursionError) as exc:
        return {
            "ok": False,
            "classification": "canonicalization_failed",
            "issues": [str(exc)],
        }


def evaluate(expected, actual, policy=None):
    strict = compare(expected, actual)
    if policy is None:
        return {"ok": strict["ok"], "strict": strict, "accepted_omissions": []}
    if policy.get("schema_version") != "extraction-acceptance/v1" or policy.get(
        "expected_revision"
    ) != revision(expected):
        raise ValueError("acceptance.stale_policy")
    left, right = deepcopy(expected), deepcopy(actual)
    omissions = []
    for entry in policy["allowed_omissions"]:
        a, b = left["root"], right.get("root", {})
        try:
            for i in entry["scope"]:
                a, b = a["children"][i], b["children"][i]
            if not entry.get("reason") or entry["fact"] not in a.get("facts", []):
                raise ValueError("acceptance.invalid_policy")
            # A policy only permits this one reviewed condition, not arbitrary facts.
            a["facts"].remove(entry["fact"])
            if entry["fact"] in b.get("facts", []):
                b["facts"].remove(entry["fact"])
            else:
                omissions.append(entry)
        except (KeyError, IndexError, TypeError):
            return {"ok": False, "strict": strict, "accepted_omissions": []}
    if strict["ok"]:
        return {"ok": True, "strict": strict, "accepted_omissions": []}
    if strict["classification"] == "invalid_notation":
        return {"ok": False, "strict": strict, "accepted_omissions": []}
    checked = compare(left, right)
    return {
        "ok": checked["ok"],
        "strict": strict,
        "accepted_omissions": omissions if checked["ok"] else [],
        "comparison_under_policy": checked,
    }
