"""Bounded exact function evaluation with original-domain and occurrence evidence.

The evaluator records restrictions before substitution/cancellation. Verification
walks the source independently and reconstructs domains without consuming those
recorded restrictions. A sum is a multiset of occurrences, never a set of inputs.
"""

from collections import defaultdict, deque
from copy import deepcopy
import hashlib
import json

import sympy as sp

from ..problem_understanding.notation_parser import NotationError
from .stage_one.function_domain import ARGUMENT, MAX_COEFFICIENT_BITS, expression_latex

VERSION = "function-evaluation/v1"
METHOD_ID = "method-function-evaluation"
MAX_AST_NODES = 256
MAX_AST_DEPTH = 24
MAX_FUNCTIONS = 8
MAX_CALL_DEPTH = 2
MAX_CALLS = 32
MAX_DEGREE = 8
MAX_SUM_TERMS = 4096
MAX_INDEX = 10000
MAX_DOMAIN_POINTS = 32


def _fail(code):
    raise NotationError("function_evaluation." + code)


def _rational(value):
    try:
        value = sp.Rational(value)
    except (TypeError, ValueError, ZeroDivisionError):
        _fail("rational_required")
    if max(int(value.p).bit_length(), int(value.q).bit_length()) > MAX_COEFFICIENT_BITS:
        _fail("coefficient_budget")
    return value


def _children(ast):
    return [part for part in ast[1:] if isinstance(part, list)]


def _growth(ast):
    """Bound expansion before asking any symbolic library to expand a tree."""
    kind = ast[0]
    if kind == "number":
        return 0, 0
    if kind in ("bound", "ref"):
        return 1, 0
    if kind == "function_call":
        size = 2 * max(_growth(ast[2]))
        result = size, size
    elif kind == "neg":
        result = _growth(ast[1])
    else:
        a, b = _growth(ast[1])
        c, d = _growth(ast[2])
        if kind in ("+", "-"):
            result = max(a + d, c + b), b + d
        elif kind == "*":
            result = a + c, b + d
        elif kind == "/":
            result = a + d, b + c
        else:
            power = int(_rational(ast[2][1]))
            result = a * power, b * power
    if max(result) > MAX_DEGREE:
        _fail("expansion_budget")
    return result


def _syntax(ast, *, refs=(), body=False, depth=0, counts=None, calls=0):
    counts = counts if counts is not None else [0, 0]
    counts[0] += 1
    if counts[0] > MAX_AST_NODES or depth > MAX_AST_DEPTH:
        _fail("ast_budget")
    if not isinstance(ast, list) or not ast:
        _fail("invalid_ast")
    kind = ast[0]
    if ast == ARGUMENT and body:
        return
    if kind == "number" and len(ast) == 2:
        _rational(ast[1])
        return
    if kind == "ref" and len(ast) >= 3 and ast[2] == "scalar" and ast[1] in refs and not body:
        return
    if kind == "function_call" and len(ast) == 3 and not body:
        if ast[1][0] != "ref" or len(ast[1]) < 3 or ast[1][2] != "function":
            _fail("function_ref_required")
        counts[1] += 1
        if counts[1] > MAX_CALLS or calls >= MAX_CALL_DEPTH:
            _fail("call_budget")
        _syntax(ast[2], refs=refs, depth=depth + 1, counts=counts, calls=calls + 1)
        return
    if kind == "neg" and len(ast) == 2:
        _syntax(ast[1], refs=refs, body=body, depth=depth + 1, counts=counts, calls=calls)
        return
    if kind not in ("+", "-", "*", "/", "^") or len(ast) != 3:
        _fail("unsupported_expression")
    if kind == "^":
        if ast[2][0] != "number" or _rational(ast[2][1]) not in (0, 1, 2):
            _fail("power_budget")
    for child in ast[1:]:
        _syntax(child, refs=refs, body=body, depth=depth + 1, counts=counts, calls=calls)


def _set(ast):
    if ast == ["real"]:
        return sp.S.Reals
    if not isinstance(ast, list) or not ast:
        _fail("invalid_domain")
    if ast[0] == "set" and len(ast) - 1 <= MAX_DOMAIN_POINTS:
        return sp.FiniteSet(*(_endpoint(p) for p in ast[1:]))
    if ast[0] == "set_difference" and len(ast) == 3:
        return _set(ast[1]) - _set(ast[2])
    if ast[0] == "interval" and len(ast) == 5:
        lo, hi = _endpoint(ast[3]), _endpoint(ast[4])
        if (lo == -sp.oo and ast[1]) or (hi == sp.oo and ast[2]) or lo > hi:
            _fail("invalid_domain")
        return sp.Interval(lo, hi, left_open=not ast[1], right_open=not ast[2])
    _fail("unsupported_domain")


def _endpoint(ast):
    if ast[0] == "number":
        return _rational(ast[1])
    if ast[0] == "infinity":
        return sp.oo if len(ast) == 1 else sp.oo * ast[1]
    if ast[0] == "neg":
        return -_endpoint(ast[1])
    if ast[0] == "/":
        a, b = _endpoint(ast[1]), _endpoint(ast[2])
        if not b or not a.is_Rational or not b.is_Rational:
            _fail("invalid_domain_endpoint")
        return _rational(a / b)
    _fail("invalid_domain_endpoint")


def _bounded(value, variable, *, numerator_degree=MAX_DEGREE, denominator_degree=MAX_DEGREE):
    if value.has(sp.zoo, sp.nan, sp.oo, -sp.oo):
        _fail("nonfinite_expression")
    num, den = sp.fraction(sp.cancel(value))
    for expr, limit in ((num, numerator_degree), (den, denominator_degree)):
        poly = sp.Poly(expr, variable, domain=sp.QQ)
        if poly.degree() > limit:
            _fail("expansion_budget")
        for coefficient in poly.all_coeffs():
            _rational(coefficient)
    return sp.cancel(value)


def _apply(kind, left, right=None, *, raw=False):
    if raw:
        if kind == "neg":
            return sp.Mul(-1, left, evaluate=False)
        if kind in ("+", "-"):
            return sp.Add(left, right if kind == "+" else sp.Mul(-1, right, evaluate=False), evaluate=False)
        if kind == "*":
            return sp.Mul(left, right, evaluate=False)
        if kind == "/":
            return sp.Mul(left, sp.Pow(right, -1, evaluate=False), evaluate=False)
        return sp.Pow(left, right, evaluate=False)
    if kind == "neg":
        return -left
    if kind == "+":
        return left + right
    if kind == "-":
        return left - right
    if kind == "*":
        return left * right
    if kind == "/":
        return left / right if right != 0 else sp.S.Zero
    return left ** right


def _body_value(ast, argument, *, raw=False):
    if ast == ARGUMENT:
        return argument
    if ast[0] == "number":
        return _rational(ast[1])
    children = [_body_value(child, argument, raw=raw) for child in ast[1:]]
    return _apply(ast[0], *children, raw=raw)


def _substitution_latex(body, argument):
    # Source positions stay visible even when SymPy's printer evaluates a
    # numeric power inside an unevaluated product.
    return expression_latex(body, r"\left(" + sp.latex(argument) + r"\right)")


def _zeros(value, variable):
    numerator = sp.fraction(sp.cancel(value))[0]
    if numerator == 0:
        return sp.S.Reals
    poly = sp.Poly(numerator, variable, domain=sp.QQ)
    if poly.degree() > MAX_DEGREE:
        _fail("condition_budget")
    return sp.FiniteSet(*sp.polys.polytools.real_roots(poly)) if poly.degree() > 0 else sp.S.EmptySet


def _relation_set(value, op, variable):
    value = sp.cancel(value)
    if op == "!=":
        return sp.S.Reals - _zeros(value, variable)
    if op == "=":
        return _zeros(value, variable)
    relation = {">": sp.Gt, ">=": sp.Ge, "<": sp.Lt, "<=": sp.Le}[op](value, 0)
    if relation in (sp.S.true, sp.S.false):
        return sp.S.Reals if relation == sp.S.true else sp.S.EmptySet
    result = sp.solve_univariate_inequality(relation, variable, relational=False)
    if not isinstance(result, (sp.Interval, sp.Union, sp.FiniteSet, type(sp.S.EmptySet), type(sp.S.Reals))):
        _fail("unresolved_domain")
    return result


def _preimage(value, domain, variable):
    if domain == sp.S.Reals:
        return sp.S.Reals
    if domain == sp.S.EmptySet:
        return sp.S.EmptySet
    if isinstance(domain, sp.FiniteSet):
        return sp.Union(*(_relation_set(value - point, "=", variable) for point in domain))
    if isinstance(domain, sp.Union):
        return sp.Union(*(_preimage(value, component, variable) for component in domain.args))
    if isinstance(domain, sp.Interval):
        result = sp.S.Reals
        if domain.start != -sp.oo:
            result &= _relation_set(value - domain.start, ">" if domain.left_open else ">=", variable)
        if domain.end != sp.oo:
            result &= _relation_set(value - domain.end, "<" if domain.right_open else "<=", variable)
        return result
    _fail("unresolved_domain")


def _guard_domain(guards, variable):
    domain = sp.S.Reals
    for row in guards:
        if row["kind"] == "nonzero":
            domain &= _relation_set(row["expression"], "!=", variable)
        else:
            domain &= _preimage(row["expression"], row["allowed"], variable)
    return domain


def _signature(description):
    # All fields, including source and target identities, bind the certificate.
    return hashlib.sha256(json.dumps(description, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _prepare(description):
    if description.get("kind") not in ("find_value", "check_constant", "finite_sum"):
        _fail("goal_unsupported")
    functions = description.get("functions", [])
    if not 1 <= len(functions) <= MAX_FUNCTIONS:
        _fail("function_budget")
    found = {}
    for function in functions:
        ref = function.get("function_ref")
        if not isinstance(ref, str) or not ref or ref in found or not function.get("source_ref"):
            _fail("function_identity")
        _syntax(function["expression_ast"], body=True)
        _growth(function["expression_ast"])
        _set(function.get("input_domain_ast", ["real"]))
        # Inspect the uncancelled body as well as its simplified result.
        dummy = sp.Symbol("_function_input", real=True)
        raw = _body_value(function["expression_ast"], dummy, raw=True)
        numerator, denominator = sp.fraction(sp.together(raw))
        _bounded(numerator, dummy, numerator_degree=2, denominator_degree=0)
        _bounded(denominator, dummy, numerator_degree=1, denominator_degree=0)
        found[ref] = function
    outer_ref = description.get("variable_ref", "")
    refs = {outer_ref} if outer_ref else set()
    _set(description.get("input_domain_ast", ["real"]))
    targets = [description["expression_ast"]] if description["kind"] != "finite_sum" else []
    if description["kind"] == "finite_sum":
        terms = description.get("terms", [])
        if not terms or len(terms) > MAX_SUM_TERMS:
            _fail("sum_budget")
        count = 0
        for term in terms:
            index_ref = term.get("index_ref")
            term_refs = {index_ref} if index_ref else set()
            if index_ref:
                lo, hi = term.get("lower"), term.get("upper")
                if type(lo) is not int or type(hi) is not int or max(abs(lo), abs(hi)) > MAX_INDEX:
                    _fail("sum_index_budget")
                count += max(0, hi - lo + 1)
            else:
                count += 1
            if count > MAX_SUM_TERMS:
                _fail("sum_budget")
            _syntax(term["expression_ast"], refs=term_refs)
            targets.append(term["expression_ast"])
    else:
        _syntax(description["expression_ast"], refs=refs)
    def check_calls(ast):
        if ast[0] == "function_call" and ast[1][1] not in found:
            _fail("unknown_function")
        for child in _children(ast):
            check_calls(child)
    for target in targets:
        check_calls(target)
        _growth(target)
    def contains_call(ast):
        return ast[0] == "function_call" or any(contains_call(child) for child in _children(ast))
    if not any(contains_call(target) for target in targets):
        _fail("function_call_required")
    return found


def structural_inspect(description):
    try:
        _prepare(description)
        return {"structure_supported": True, "reason": "", "structure_version": VERSION}
    except (NotationError, KeyError, TypeError, ValueError, IndexError, ZeroDivisionError, sp.PolynomialError) as exc:
        return {"structure_supported": False, "reason": getattr(exc, "code", "function_evaluation.invalid_descriptor"),
                "structure_version": VERSION}


def _walk(ast, functions, symbols, variable, guards, calls, *, path="target", source_ref="", argument=None, depth=0):
    if ast == ARGUMENT:
        return argument
    kind = ast[0]
    if kind == "number":
        return _rational(ast[1])
    if kind == "ref":
        return symbols[ast[1]]
    if kind == "function_call":
        ref = ast[1][1]
        function = functions[ref]
        start = len(guards)
        value = _walk(ast[2], functions, symbols, variable, guards, calls,
                      path=path + "/input", source_ref=source_ref, depth=depth + 1)
        input_defined = _guard_domain(guards[start:], variable) != sp.S.EmptySet
        allowed = _set(function.get("input_domain_ast", ["real"]))
        if allowed != sp.S.Reals:
            guards.append({"kind": "membership", "expression": value, "allowed": allowed,
                           "path": path + "/declared-domain", "source_ref": function.get("input_domain_source_ref") or function["source_ref"]})
        output = _walk(function["expression_ast"], functions, symbols, variable, guards, calls,
                       path=path + "/body", source_ref=function["source_ref"], argument=value, depth=depth + 1)
        output = _bounded(output, variable)
        call_domain = _guard_domain(guards[start:], variable)
        defined = call_domain != sp.S.EmptySet
        substitution = _body_value(function["expression_ast"], value, raw=True)
        calls.append({"call_id": path, "function_ref": ref, "function_name": function.get("function_name") or ref.rsplit(":", 1)[-1],
                      "source_ref": function["source_ref"], "input_ast": deepcopy(ast[2]), "input": value if input_defined else None,
                      "rule_ast": deepcopy(function["expression_ast"]),
                      "substitution": substitution if defined else None,
                      "substitution_latex": _substitution_latex(function["expression_ast"], value) if defined else "",
                      "input_defined": input_defined, "defined": defined,
                      "output": output if defined else None, "domain": call_domain, "depth": depth})
        return output
    values = [_walk(child, functions, symbols, variable, guards, calls, path=path + "/" + str(index),
                    source_ref=source_ref, argument=argument, depth=depth)
              for index, child in enumerate(ast[1:], 1)]
    if kind == "/" or (kind == "^" and values[1] == 0):
        guards.append({"kind": "nonzero", "expression": values[1] if kind == "/" else values[0],
                       "path": path + ("/2" if kind == "/" else "/1"), "source_ref": source_ref})
    return _bounded(_apply(kind, *values), variable)


def _declared_functions(functions):
    variable = sp.Symbol("_function_input", real=True)
    for function in functions.values():
        guards = []
        _walk(function["expression_ast"], functions, {}, variable, guards, [],
              path="definition", source_ref=function["source_ref"], argument=variable)
        natural = _guard_domain(guards, variable)
        declared = _set(function.get("input_domain_ast", ["real"]))
        explicit = function.get("explicit_domain") or bool(function.get("input_domain_source_ref")) or declared != sp.S.Reals
        if natural == sp.S.EmptySet or declared == sp.S.EmptySet:
            _fail("invalid_function_declaration")
        if explicit and declared - natural != sp.S.EmptySet:
            _fail("declared_domain_conflict")


def _expression_result(description, functions):
    variable = sp.Symbol(description.get("variable") or "x", real=True)
    ref = description.get("variable_ref")
    symbols = {ref: variable} if ref else {}
    guards, calls = [], []
    value = _walk(description["expression_ast"], functions, symbols, variable, guards, calls,
                  source_ref=description.get("target_ref", ""))
    domain = _guard_domain(guards, variable) & _set(description.get("input_domain_ast", ["real"]))
    defined = domain != sp.S.EmptySet
    return {"kind": "expression_with_domain" if ref else "scalar_value", "defined": defined,
            "expression": value if defined else None, "value": value if defined and not ref else None,
            "domain": domain, "variable": variable, "calls": calls, "constraints": guards}


def _sample_values(domain, variable, value):
    if isinstance(domain, sp.FiniteSet):
        return [(point, sp.cancel(value.subs(variable, point))) for point in domain]
    points = []
    # A nonconstant rational of degree <= MAX_DEGREE cannot take one value at
    # more than 2*MAX_DEGREE distinct regular points unless it is constant.
    for denominator in range(1, 2 * MAX_DEGREE + 4):
        for numerator in range(-2 * MAX_DEGREE - 2, 2 * MAX_DEGREE + 3):
            point = sp.Rational(numerator, denominator)
            if domain.contains(point) is sp.S.true and point not in points:
                points.append(point)
    for component in (domain.args if isinstance(domain, sp.Union) else (domain,)):
        if isinstance(component, sp.Interval):
            a, b = component.start, component.end
            center = (a + b) / 2 if a != -sp.oo and b != sp.oo else (a + 1 if a != -sp.oo else b - 1 if b != sp.oo else sp.S.Zero)
            width = (b - a) / 3 if a != -sp.oo and b != sp.oo else sp.S.One
            for k in range(1, 2 * MAX_DEGREE + 3):
                point = sp.simplify(center + width / (k + 1))
                if domain.contains(point) is sp.S.true:
                    points.append(point)
    return [(point, sp.cancel(value.subs(variable, point))) for point in dict.fromkeys(points)]


def _constant_result(result):
    result["kind"] = "constant_check"
    result["is_constant"] = None
    result["witness"] = []
    if not result["defined"]:
        return result
    value, variable, domain = result["expression"], result["variable"], result["domain"]
    if not value.has(variable):
        result.update(is_constant=True, value=value, proof={"kind": "rational_identity", "residual": sp.S.Zero})
        return result
    samples = _sample_values(domain, variable, value)
    if isinstance(domain, sp.FiniteSet) and samples and len({output for _, output in samples}) == 1:
        result.update(is_constant=True, value=samples[0][1], proof={"kind": "complete_finite_domain", "inputs": list(domain)})
        return result
    for point, output in samples[1:]:
        if sp.simplify(output - samples[0][1]) != 0:
            result.update(is_constant=False, value=None,
                          witness=[{"input": samples[0][0], "output": samples[0][1]}, {"input": point, "output": output}],
                          proof={"kind": "two_legal_outputs"})
            return result
    _fail("constant_check_unresolved")


def _occurrences(description):
    for block_index, term in enumerate(description["terms"]):
        index_ref = term.get("index_ref")
        indices = range(term["lower"], term["upper"] + 1) if index_ref else (None,)
        for position, index in enumerate(indices):
            yield {"occurrence_id": f"term:{block_index}:{position}", "index": index,
                   "symbols": {index_ref: sp.Integer(index)} if index_ref else {},
                   "source_ref": term.get("source_ref") or description.get("target_ref", ""),
                   "expression_ast": term["expression_ast"]}


def _pair_expression(function_ref):
    variable_ref = "evaluation:reciprocal_input"
    ref = ["ref", variable_ref, "scalar"]
    call = lambda argument: ["function_call", ["ref", function_ref, "function"], argument]
    return ["+", call(ref), call(["/", ["number", "1"], ref])], variable_ref


def _sum_result(description, functions):
    variable = sp.Symbol(description.get("variable") or "x", real=True)
    terms, all_guards, all_calls = [], [], []
    for item in _occurrences(description):
        guards, calls = [], []
        value = _walk(item["expression_ast"], functions, item["symbols"], variable, guards, calls,
                      path=item["occurrence_id"], source_ref=item["source_ref"])
        defined = _guard_domain(guards, variable) != sp.S.EmptySet
        ast = item["expression_ast"]
        top_call = next((row for row in calls if row["call_id"] == item["occurrence_id"]), None)
        terms.append({"occurrence_id": item["occurrence_id"], "index": item["index"], "input_ast": deepcopy(ast),
                      "value": value if defined else None, "defined": defined,
                      "input": top_call["input"] if top_call else None,
                      "function_ref": ast[1][1] if ast[0] == "function_call" else None,
                      "source_ref": item["source_ref"], "calls": calls})
        all_guards.extend(guards)
        all_calls.extend(calls)
    defined = all(term["defined"] for term in terms)
    result = {"kind": "finite_sum", "defined": defined, "terms": terms, "calls": all_calls,
              "constraints": all_guards, "pairs": [], "leftovers": [], "pairing": None,
              "term_count": len(terms), "pair_count": 0, "leftover_count": 0,
              "domain": sp.S.Reals if defined else sp.S.EmptySet, "variable": variable,
              "expression": None, "value": None, "total": None}
    if not defined:
        return result
    refs = {term["function_ref"] for term in terms}
    if len(refs) == 1 and None not in refs:
        function_ref = next(iter(refs))
        ast, ref = _pair_expression(function_ref)
        pair_desc = {**description, "kind": "check_constant", "expression_ast": ast,
                     "variable_ref": ref, "variable": "t", "input_domain_ast": ["real"]}
        paired = _constant_result(_expression_result(pair_desc, functions))
        if paired["is_constant"] is True:
            result["pairing"] = {"kind": "reciprocal", "function_ref": function_ref,
                                 "constant": paired["value"], "domain": paired["domain"],
                                 "expression": paired["expression"], "proof": deepcopy(paired["proof"]),
                                 "verified": True}
    available = defaultdict(deque)
    for term in terms:
        available[term["input"]].append(term)
    consumed = set()
    if result["pairing"]:
        for term in terms:
            ident, value = term["occurrence_id"], term["input"]
            if ident in consumed or value in (0, 1, -1):
                continue
            matches = available[1 / value]
            while matches and matches[0]["occurrence_id"] in consumed:
                matches.popleft()
            if matches:
                other = matches.popleft()
                if result["pairing"]["domain"].contains(value) is not sp.S.true:
                    _fail("pair_domain_mismatch")
                consumed.update((ident, other["occurrence_id"]))
                result["pairs"].append({"left_id": ident, "right_id": other["occurrence_id"],
                                        "left_input": value, "right_input": other["input"],
                                        "pair_value": result["pairing"]["constant"]})
    result["leftovers"] = [term["occurrence_id"] for term in terms if term["occurrence_id"] not in consumed]
    result["pair_count"] = len(result["pairs"])
    result["leftover_count"] = len(result["leftovers"])
    total = sum((term["value"] for term in terms), sp.S.Zero)
    result.update(value=total, total=total, expression=total)
    return result


def evaluate(description):
    functions = _prepare(description)
    _declared_functions(functions)
    result = _sum_result(description, functions) if description["kind"] == "finite_sum" else _expression_result(description, functions)
    if description["kind"] == "check_constant":
        result = _constant_result(result)
        result["trials"] = []
        if result["defined"] and description.get("variable_ref"):
            candidates = _sample_values(result["domain"], result["variable"], result["variable"])
            # Prefer ordinary small positive inputs for the teaching examples.
            points = [point for point in (sp.S.One, sp.Integer(2), sp.Integer(3))
                      if result["domain"].contains(point) is sp.S.true]
            points = list(dict.fromkeys([*points, *(point for point, _ in candidates)]))[:2]
            for point in points:
                guards, calls = [], []
                total = _walk(description["expression_ast"], functions, {description["variable_ref"]: point},
                              result["variable"], guards, calls, source_ref=description.get("target_ref", ""))
                result["trials"].append({"input": point, "total": total, "calls": calls})
    result.update(target_ref=description.get("target_ref", ""), source_signature=_signature(description), version=VERSION)
    return result


analyze = evaluate


def _check_source(ast, functions, symbols, variable, *, argument=None, path="target", source_ref="", depth=0,
                  calls=None, guards=None):
    """Independent source interpreter: domain sets travel with every operand."""
    if ast == ARGUMENT:
        return argument, sp.S.Reals
    if ast[0] == "number":
        return _rational(ast[1]), sp.S.Reals
    if ast[0] == "ref":
        return symbols[ast[1]], sp.S.Reals
    if ast[0] == "function_call":
        ref = ast[1][1]
        function = functions[ref]
        value, domain = _check_source(ast[2], functions, symbols, variable, path=path + "/input",
                                     source_ref=source_ref, depth=depth + 1, calls=calls, guards=guards)
        input_defined = domain != sp.S.EmptySet
        declared = _set(function.get("input_domain_ast", ["real"]))
        if guards is not None and declared != sp.S.Reals:
            guards.append({"kind": "membership", "expression": value, "allowed": declared,
                           "path": path + "/declared-domain", "source_ref": function.get("input_domain_source_ref") or function["source_ref"]})
        output, body_domain = _check_source(function["expression_ast"], functions, symbols, variable, argument=value,
                                           path=path + "/body", source_ref=function["source_ref"], depth=depth + 1,
                                           calls=calls, guards=guards)
        domain &= body_domain & _preimage(value, declared, variable)
        if calls is not None:
            defined = domain != sp.S.EmptySet
            substitution = _body_value(function["expression_ast"], value, raw=True)
            calls.append({"call_id": path, "function_ref": ref, "function_name": function.get("function_name") or ref.rsplit(":", 1)[-1],
                          "source_ref": function["source_ref"], "input_ast": deepcopy(ast[2]), "input": value if input_defined else None,
                          "rule_ast": deepcopy(function["expression_ast"]), "substitution": substitution if defined else None,
                          "substitution_latex": _substitution_latex(function["expression_ast"], value) if defined else "",
                          "input_defined": input_defined, "defined": defined,
                          "output": output if defined else None, "domain": domain, "depth": depth})
        return output, domain
    operands = [_check_source(child, functions, symbols, variable, argument=argument,
                              path=path + "/" + str(index), source_ref=source_ref, depth=depth, calls=calls, guards=guards)
                for index, child in enumerate(ast[1:], 1)]
    domain = sp.Intersection(*(item[1] for item in operands))
    values = [item[0] for item in operands]
    if ast[0] == "/" or (ast[0] == "^" and values[1] == 0):
        base = values[1] if ast[0] == "/" else values[0]
        if guards is not None:
            guards.append({"kind": "nonzero", "expression": base,
                           "path": path + ("/2" if ast[0] == "/" else "/1"), "source_ref": source_ref})
        # Unlike evaluator root isolation, checker solves the original rational
        # equality, then removes every zero from the carried operand domains.
        zero_set = sp.solveset(base, variable, domain=sp.S.Reals)
        if isinstance(zero_set, sp.ConditionSet):
            _fail("verification_unresolved_domain")
        domain -= zero_set
    value = _apply(ast[0], *values)
    return sp.cancel(value), domain


def _same_value(left, right):
    if left is None or right is None:
        return left is right
    return sp.cancel(left - right) == 0


def _same_records(expected, actual):
    """Compare evidence after a trajectory codec may simplify display objects."""
    if not isinstance(actual, list) or len(expected) != len(actual):
        return False
    for wanted, received in zip(expected, actual, strict=True):
        if set(wanted) != set(received):
            return False
        for key, value in wanted.items():
            if key in ("input", "output", "substitution", "expression"):
                if not _same_value(value, received[key]):
                    return False
            elif value != received[key]:
                return False
    return True


def _verify_constant_claim(value, variable, domain, constant, proof):
    """Verify constancy on the complete legal domain, including finite domains."""
    if constant is None or constant.free_symbols or domain == sp.S.EmptySet:
        return False
    identity_proof = {"kind": "rational_identity", "residual": sp.S.Zero}
    if isinstance(domain, sp.FiniteSet):
        expected_proof = (identity_proof if not value.has(variable)
                          else {"kind": "complete_finite_domain", "inputs": list(domain)})
        return proof == expected_proof and all(_same_value(value.subs(variable, point), constant) for point in domain)
    return proof == identity_proof and _same_value(value, constant)


def verify(description, result):
    """Check original syntax, exact output/domain and all sum occurrence claims."""
    try:
        functions = _prepare(description)
        definition_variable = sp.Symbol("_function_input", real=True)
        for function in functions.values():
            _, natural = _check_source(function["expression_ast"], functions, {}, definition_variable, argument=definition_variable)
            declared = _set(function.get("input_domain_ast", ["real"]))
            explicit = function.get("explicit_domain") or function.get("input_domain_source_ref") or declared != sp.S.Reals
            if natural == sp.S.EmptySet or declared == sp.S.EmptySet or (explicit and declared - natural != sp.S.EmptySet):
                return False
        if result.get("source_signature") != _signature(description) or result.get("target_ref") != description.get("target_ref", "") or result.get("version") != VERSION:
            return False
        variable = sp.Symbol(description.get("variable") or "x", real=True)
        if result.get("variable") != variable:
            return False
        if description["kind"] != "finite_sum":
            ref = description.get("variable_ref")
            calls, guards = [], []
            value, domain = _check_source(description["expression_ast"], functions, {ref: variable} if ref else {}, variable,
                                         source_ref=description.get("target_ref", ""), calls=calls, guards=guards)
            if not _same_records(calls, result["calls"]) or not _same_records(guards, result["constraints"]):
                return False
            domain &= _set(description.get("input_domain_ast", ["real"]))
            if result["domain"] != domain or result["defined"] != (domain != sp.S.EmptySet):
                return False
            if not _same_value(result["expression"], value if result["defined"] else None):
                return False
            expected_kind = "constant_check" if description["kind"] == "check_constant" else "expression_with_domain" if ref else "scalar_value"
            if result["kind"] != expected_kind:
                return False
            if expected_kind != "constant_check":
                return _same_value(result["value"], value if not ref and result["defined"] else None)
            for trial in result.get("trials", []):
                if domain.contains(trial["input"]) is not sp.S.true:
                    return False
                trial_calls = []
                total, trial_domain = _check_source(description["expression_ast"], functions, {ref: trial["input"]}, variable,
                                                    source_ref=description.get("target_ref", ""), calls=trial_calls)
                if trial_domain == sp.S.EmptySet or not _same_value(total, trial["total"]) or not _same_records(trial_calls, trial["calls"]):
                    return False
            if not result["defined"]:
                return result["is_constant"] is None and result["value"] is None
            if result["is_constant"] is True:
                return _verify_constant_claim(value, variable, domain, result["value"], result.get("proof"))
            if result["is_constant"] is not False or len(result["witness"]) != 2:
                return False
            outputs = []
            for row in result["witness"]:
                if domain.contains(row["input"]) is not sp.S.true:
                    return False
                output = sp.cancel(value.subs(variable, row["input"]))
                if not _same_value(output, row["output"]):
                    return False
                outputs.append(output)
            return result.get("proof") == {"kind": "two_legal_outputs"} and not _same_value(*outputs)
        original = list(_occurrences(description))
        if result["kind"] != "finite_sum" or result["term_count"] != len(original) or len(result["terms"]) != len(original):
            return False
        outputs = {}
        undefined = False
        all_calls, all_guards, term_inputs = [], [], {}
        for source, term in zip(original, result["terms"], strict=True):
            calls, guards = [], []
            value, domain = _check_source(source["expression_ast"], functions, source["symbols"], variable,
                                         path=source["occurrence_id"], source_ref=source["source_ref"],
                                         calls=calls, guards=guards)
            defined = domain != sp.S.EmptySet
            if term["occurrence_id"] != source["occurrence_id"] or term["index"] != source["index"] or term["defined"] != defined or not _same_value(term["value"], value if defined else None):
                return False
            if (not _same_records(calls, term["calls"]) or term["input_ast"] != source["expression_ast"]
                    or term["source_ref"] != source["source_ref"]):
                return False
            top_call = next((row for row in calls if row["call_id"] == source["occurrence_id"]), None)
            expected_input = top_call["input"] if top_call else None
            expected_ref = source["expression_ast"][1][1] if top_call else None
            if not _same_value(term["input"], expected_input) or term["function_ref"] != expected_ref:
                return False
            term_inputs[term["occurrence_id"]] = (expected_input, expected_ref)
            outputs[term["occurrence_id"]] = value
            undefined |= not defined
            all_calls.extend(calls)
            all_guards.extend(guards)
        if not _same_records(all_calls, result["calls"]) or not _same_records(all_guards, result["constraints"]):
            return False
        if result["defined"] == undefined:
            return False
        if undefined:
            return (result["total"] is None and result["value"] is None and result["expression"] is None
                    and result["domain"] == sp.S.EmptySet and result["pairs"] == []
                    and result["leftovers"] == [] and result["pairing"] is None
                    and result["pair_count"] == result["leftover_count"] == 0)
        if result["domain"] != sp.S.Reals or not _same_value(result["total"], sum(outputs.values(), sp.S.Zero)) or not _same_value(result["value"], result["total"]):
            return False
        if not _same_value(result["expression"], result["total"]):
            return False
        ids = []
        for pair in result["pairs"]:
            left, right = pair["left_id"], pair["right_id"]
            if left == right or left not in outputs or right not in outputs or not _same_value(outputs[left] + outputs[right], pair["pair_value"]):
                return False
            if not _same_value(pair["left_input"], term_inputs[left][0]) or not _same_value(pair["right_input"], term_inputs[right][0]):
                return False
            ids.extend((left, right))
        ids.extend(result["leftovers"])
        if len(ids) != len(set(ids)) or set(ids) != set(outputs):
            return False
        if result["pair_count"] != len(result["pairs"]) or result["leftover_count"] != len(result["leftovers"]):
            return False
        pairing = result["pairing"]
        if pairing:
            ast, ref = _pair_expression(pairing["function_ref"])
            t = sp.Symbol("t", real=True)
            value, domain = _check_source(ast, functions, {ref: t}, t)
            if (pairing.get("kind") != "reciprocal"
                    or not _verify_constant_claim(value, t, domain, pairing["constant"], pairing.get("proof"))
                    or not _same_value(value, pairing["expression"]) or pairing["domain"] != domain or pairing.get("verified") is not True):
                return False
            for pair in result["pairs"]:
                if (not _same_value(pair["left_input"] * pair["right_input"], sp.S.One)
                        or not _same_value(pair["pair_value"], pairing["constant"])
                        or term_inputs[pair["left_id"]][1] != pairing["function_ref"]
                        or term_inputs[pair["right_id"]][1] != pairing["function_ref"]
                        or domain.contains(pair["left_input"]) is not sp.S.true):
                    return False
        elif result["pairs"]:
            return False
        return True
    except (NotationError, KeyError, TypeError, ValueError, IndexError, ZeroDivisionError, sp.PolynomialError, NotImplementedError):
        return False
