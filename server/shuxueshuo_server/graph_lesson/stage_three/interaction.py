"""Compile step interactions from frozen exact seeds.

Pure functions: callers supply seeds, rules and the repetition context, and own
scheduling, budgets and persistence. A distractor is kept only with a concrete
witness that it differs from the checked answer in this problem; candidates
that cannot be told apart are dropped, never presented as wrong.
"""

import hashlib
import json
import random
from copy import deepcopy
from dataclasses import dataclass, field, replace
from functools import cmp_to_key
from pathlib import Path
from types import SimpleNamespace

import sympy as sp
from jsonschema import Draft202012Validator, ValidationError

from . import domain_borrow, domain_interaction, domain_visuals, equality_presentation
from . import interaction_graph_contract as graph_contract
from . import interaction_graphs as drawing
from .capabilities import CapabilityGap
from .capabilities.cases import exact_set_equal
from .capabilities.parametric import _compare
from .capabilities.ranges import _sign, quadratic_interval_range, reciprocal_range
from .capabilities.substitution import (
    inspect_affine_reciprocal,
    restore_substitution_range,
)
from .contracts import ROOT
from .interaction_graphs import GraphUnavailable
from .math_values import (
    BOUND_EXPLANATION,
    BOUND_NAMES,
    BOUND_TEX,
    EXTREMUM_NAMES,
    EXTREMUM_TEX,
    polynomial_extrema_attained,
)
from .math_values import latex as _latex
from .presentation_intervals import in_set, merge_view, oriented
from .presentation_templates import _render
from .route_constraints import apply_visible_constraints
from .trajectory import decode_value

CONTRACT = "graph-step-interaction/v1"
REGISTRY_PATH = ROOT / "site/data/knowledge-next/interactions/registry.json"
REGISTRY_SCHEMA = ROOT / "internal/schemas/graph-interaction-registry-v1.schema.json"
CHUNK_SCHEMA = ROOT / "internal/schemas/graph-step-interaction-v1.schema.json"
# Interaction-only code, revisioned apart from the mathematical fingerprint.
ENGINE_FILES = (Path(__file__).resolve(), Path(drawing.__file__).resolve(),
                Path(graph_contract.__file__).resolve(), Path(domain_borrow.__file__).resolve(),
                Path(domain_interaction.__file__).resolve(), Path(domain_visuals.__file__).resolve(),
                Path(equality_presentation.__file__).resolve(), CHUNK_SCHEMA)
MAX_REPRESENTATIVES = 12
# Policies can need exact equality witnesses outside the generic constant grid.
MAX_POLICY_REPRESENTATIVES = 2 * MAX_REPRESENTATIVES
GRID = tuple(sp.Integer(value) for value in range(-4, 5))
NEIGHBOR = sp.Rational(1, 2)

LOCATION_NAMES = {"left_endpoint": "左端点", "right_endpoint": "右端点", "vertex": "顶点", "critical": "转折点"}
LATEX_OPERATORS = {"<=": r"\leq", "<": "<", ">=": r"\geq", ">": ">"}
MIRROR = {"<=": ">=", "<": ">", ">=": "<=", ">": "<"}
FLIP_STRICTNESS = {"<=": "<", "<": "<=", ">=": ">", ">": ">="}


class NotInteractive(Exception):
    """The group is answered by a read-only card, for the stated reason."""

    def __init__(self, reason, diagnostics=()):
        super().__init__(reason)
        self.reason = reason
        self.diagnostics = list(diagnostics)


@dataclass
class Candidate:
    key: str
    label: str
    value: object = None
    variant: str = "default"
    facts: dict = field(default_factory=dict)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _math(value):
    return f"${_latex(value)}$"


def _cmp(left, right):
    result = _compare(sp.simplify(left), sp.simplify(right))
    return 0 if result == 0 else (1 if result > 0 else -1)


def _finite(value):
    return isinstance(value, sp.Expr) and not value.free_symbols and value.is_finite is True and value.is_real is True


# --- Registry -----------------------------------------------------------------

def _rows(part):
    if part["component"] == "checklist":
        return part["rows"]
    return [{"seed": 0, "answer": part["answer"], "distractors": part["distractors"]}]


def _apply_override(rule, override):
    """Field-by-field replacement; parts are replaced field by field per index."""
    updated = deepcopy(rule)
    for key, value in override.items():
        if key != "parts":
            updated[key] = deepcopy(value)
            continue
        for index, fields in enumerate(value):
            if index >= len(updated["parts"]):
                raise ValueError("interaction.override_part_missing")
            updated["parts"][index].update(deepcopy(fields))
    return updated


def _rule_validator(schema, definition):
    return Draft202012Validator({"$defs": schema["$defs"], "$ref": f"#/$defs/{definition}"})


def _validate_graphs(part):
    graphs, sources = part.get("graphs", {}), {row["answer"]["from"] for row in _rows(part)}
    for slot, table, components in (("stem", STEM_GRAPHS, ("choice", "multi", "checklist")),
                                    ("options", OPTION_GRAPHS, ("choice", "multi"))):
        name = graphs.get(slot)
        if name is not None and (name not in table or part["component"] not in components
                                 or not sources <= table[name][0]):
            raise ValueError(f"interaction.graph_not_allowed:{slot}:{name}")
    if graphs.get("completion") is not None and graphs["completion"] not in COMPLETION_GRAPHS:
        raise ValueError("interaction.graph_not_allowed:completion:" + graphs["completion"])


def validate_registry(registry):
    schema = json.loads(REGISTRY_SCHEMA.read_text())
    Draft202012Validator(schema).validate(registry)
    allowed = set(registry["generators"])
    if allowed - IMPLEMENTED_GENERATORS:
        raise ValueError("interaction.unimplemented_generator:" + ",".join(sorted(allowed - IMPLEMENTED_GENERATORS)))
    rules = [*((rule, 1) for rule in registry["templates"].values()), *((merge, 2) for merge in registry["merges"])]
    template_rule = _rule_validator(schema, "templateRule")
    for overrides in registry["overrides"].values():
        for template, override in overrides.items():
            if template not in registry["templates"]:
                raise ValueError("interaction.override_template_unknown:" + template)
            merged = _apply_override(registry["templates"][template], override)
            template_rule.validate(merged)
            rules.append((merged, 1))
    for rule, seeds in rules:
        for part in rule["parts"]:
            minimum = part.get("min_options", 2 if part["component"] == "checklist" else 3)
            if minimum > part.get("max_options", 4):
                raise ValueError("interaction.option_limits_conflict")
            _validate_graphs(part)
            for row in _rows(part):
                if row["seed"] >= seeds:
                    raise ValueError(f"interaction.seed_index_out_of_range:{row['seed']}")
                source = ANSWERS.get(row["answer"]["from"])
                if source is None:
                    raise ValueError("interaction.unknown_answer:" + row["answer"]["from"])
                if (part["component"] == "checklist") != source.get("checklist", source["kind"] == "fixed"):
                    raise ValueError("interaction.component_answer_mismatch:" + row["answer"]["from"])
                for distractor in row["distractors"]:
                    name = distractor["generator"]
                    if name not in allowed or name not in source["generators"]:
                        raise ValueError(f"interaction.generator_not_allowed:{row['answer']['from']}:{name}")
    pairs = [tuple(merge["display_units"]) for merge in registry["merges"]]
    identifiers = [merge["id"] for merge in registry["merges"]]
    if len(set(pairs)) != len(pairs) or len(set(identifiers)) != len(identifiers):
        raise ValueError("interaction.ambiguous_merge")
    return registry


def load_registry(path=REGISTRY_PATH):
    return validate_registry(json.loads(Path(path).read_text()))


def registry_revision(registry):
    return _sha256(registry)


def engine_revision():
    return hashlib.sha256(b"".join(path.read_bytes() for path in ENGINE_FILES)).hexdigest()


def select_rule(registry, seeds):
    if len(seeds) == 2:
        units = [seed["display_unit"] for seed in seeds]
        return next((deepcopy(merge) for merge in registry["merges"] if merge["display_units"] == units), None)
    seed = seeds[0]
    base = registry["templates"].get(seed["template"])
    if base is None:
        return None
    override = registry["overrides"].get(seed["method_ref"], {}).get(seed["template"])
    return _apply_override(base, override) if override else deepcopy(base)


def merge_prefix(registry, seed):
    return any(merge["display_units"][0] == seed["display_unit"] for merge in registry["merges"])


def merge_match(registry, first, second):
    if (first["route_id"] != second["route_id"] or first["target_ref"] != second["target_ref"]
            or first["case_path"] != second["case_path"]
            or first.get("branch_id") != second.get("branch_id")
            or first.get('option_context') != second.get('option_context')
            or second["ordinal"] != first["ordinal"] + 1):
        return None
    units = [first["display_unit"], second["display_unit"]]
    return next((merge for merge in registry["merges"] if merge["display_units"] == units), None)


def plan_groups(seeds, registry, *, final):
    """Group one route's seeds in card order.

    Returns ``(groups, pending)``. A merge prefix whose follower has not been
    produced stays pending until the route can no longer append cards.
    """
    groups, index = [], 0
    while index < len(seeds):
        seed = seeds[index]
        if seed.get("status") == "ready" and merge_prefix(registry, seed):
            if index + 1 == len(seeds) and not final:
                return groups, seeds[index:]
            follower = seeds[index + 1] if index + 1 < len(seeds) else None
            if follower and follower.get("status") == "ready" and merge_match(registry, seed, follower):
                groups.append([seed, follower])
                index += 2
                continue
        groups.append([seed])
        index += 1
    return groups, []


def repeat_context(seeds, start):
    template = seeds[start]["template"]
    return {"template": template,
            "previous": sum(1 for seed in seeds[:start] if seed["template"] == template)}


def _repeat_allows(rule, values, context):
    repeat = rule["repeat"]
    if repeat == "always":
        return True
    if repeat == "never":
        return False
    if context["previous"] == 0:
        return True
    if repeat == "first":
        return False
    condition = repeat["first_or"]
    return values.get(condition["binding"]) == condition["equals"]


# --- Representative parameter values and exact single-variable ranges ------------

def _numbers(value, sink):
    if isinstance(value, sp.Set):
        _set_points(value, sink)
    elif isinstance(value, sp.Basic):
        sink.extend(sorted(value.atoms(sp.Rational), key=float))
    elif isinstance(value, dict):
        for item in value.values():
            _numbers(item, sink)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _numbers(item, sink)


def _set_points(value, sink):
    pieces = value.args if isinstance(value, sp.Union) else (value,)
    for piece in pieces:
        if isinstance(piece, sp.Interval):
            sink.extend(point for point in (piece.start, piece.end) if _finite(point))
        elif isinstance(piece, sp.FiniteSet):
            sink.extend(point for point in piece if _finite(point))


def _parameter_sets(value, sink, *, top=True):
    """Finite endpoints of parameter sets; the variable's own domain is a constant."""
    if isinstance(value, sp.Set):
        _set_points(value, sink)
    elif isinstance(value, dict):
        for key, item in value.items():
            if not (top and key == "domain"):
                _parameter_sets(item, sink, top=False)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _parameter_sets(item, sink, top=False)


def known_set(seed):
    """Parameter values allowed by the route's visible conditions, read once per seed."""
    context = seed.get("constraint_context")
    if context is None:
        raise NotInteractive("known_conditions_unknown")
    try:
        known, _ = apply_visible_constraints(context, sp.S.Reals)
    except Exception as exc:  # Unreadable conditions confirm no witness.
        raise NotInteractive("known_conditions_unknown",
                             [{"exception_type": type(exc).__name__, "message": str(exc)[:200]}]) from exc
    return known


def representatives(values, context, restrict=sp.S.Reals):
    """Only this card's frozen data and a fixed grid; at most twelve values."""
    special, constants = [], []
    _set_points(restrict, special)
    _parameter_sets(values, special)
    _numbers(values, constants)
    _numbers(context, constants)
    pool = []
    for point in special:
        pool.extend((point, point - NEIGHBOR, point + NEIGHBOR))
    pool.extend(constants)
    pool.extend(GRID)
    chosen = []
    for point in pool:
        if len(chosen) == MAX_REPRESENTATIVES:
            break
        if _finite(point) and point not in chosen and restrict.contains(point) is sp.true:
            chosen.append(point)
    # Witnesses come from the first decisive value; prefer points inside a case
    # over the breakpoints themselves, where positions may coincide.
    return sorted(chosen, key=lambda point: point in special)


def range_at(function, variable, domain):
    """Exact range and every bound position of a parameter-free function."""
    if function.free_symbols - {variable}:
        raise NotInteractive("parameter_not_substituted")
    if function.is_polynomial(variable) and sp.degree(function, variable) <= 2:
        outputs = quadratic_interval_range(sp.expand(function), variable, domain)["outputs"]
        ends, critical, name = outputs["endpoint_values"], outputs["critical_points"], "vertex"
    else:
        try:
            outputs = reciprocal_range(function, variable, domain)["outputs"]
        except CapabilityGap:
            substitution = inspect_affine_reciprocal(function, variable, domain)
            transformed = reciprocal_range(substitution["expression"], substitution["new_variable"],
                                           substitution["domain"])["outputs"]
            outputs = restore_substitution_range(
                substitution["mapping"], transformed["range"], transformed["critical_points"],
                transformed["endpoint_values"], transformed["turning_point"],
            )["outputs"]
        ends, critical, name = outputs["endpoint_values"], outputs["critical_points"], "critical"
    positions = []
    for row in ends:
        location = "left_endpoint" if row["point"] == domain.start else "right_endpoint"
        positions.append({"location": location, "point": row["point"], "value": row["value"],
                          "attained": bool(row["attained"])})
    positions.extend({"location": name, "point": row["point"], "value": row["value"], "attained": True}
                     for row in critical)
    return {**{key: outputs["range"][key] for key in ("inf", "sup", "inf_attained", "sup_attained")},
            "positions": positions}


class _Ranges:
    def __init__(self, function, variable, domain, parameter):
        self.function, self.variable, self.domain, self.parameter = function, variable, domain, parameter
        self.cache = {}

    def __call__(self, point):
        varying = self.parameter is not None and self.function.has(self.parameter)
        key = point if varying else None
        if key not in self.cache:
            value = self.function.subs(self.parameter, point) if varying else self.function
            self.cache[key] = range_at(value, self.variable, self.domain)
        return self.cache[key]


def _attempt(function, *arguments):
    try:
        return function(*arguments)
    except Exception:  # noqa: BLE001 -- an undecided point is no evidence either way.
        return None


def _bound_positions(ranges, point, bound):
    value = ranges(point)
    return {row["location"] for row in value["positions"] if _cmp(row["value"], value[bound]) == 0}


def _named_function(values, function, variable):
    """``h(x)`` when the method named this function on an earlier card, else None."""
    name = values.get("function_name")
    return f"{name}({_latex(variable)})" if name and function is not None and function.has(variable) else None


# --- Policy -------------------------------------------------------------------

def _policy_facts(values, context):
    policy = values["policy"]
    function, expression = values["function"], values["parameter_expression"]
    operator, bound = policy["operator"], policy["bound"]
    numeric = not expression.free_symbols
    relation = (sp.Rel(function, expression, MIRROR[operator], evaluate=False) if numeric
                else sp.Rel(expression, function, operator, evaluate=False))
    named = _named_function(values, function, values["x"])
    attained = polynomial_extrema_attained(function, values["x"], context["domain"])
    label = named or _latex(function)
    definition = f"记 ${named}={_latex(function)}$，" if named and values.get("define_name") else ""
    shown = (f"{label} {LATEX_OPERATORS[MIRROR[operator]]} {_latex(expression)}" if numeric
             else f"{_latex(expression)} {LATEX_OPERATORS[operator]} {label}")
    return {
        "policy": policy, "function": function, "expression": expression, "operator": operator,
        "bound": bound, "x": values["x"], "domain": context["domain"], "parameter": context.get("parameter"),
        "numeric": numeric, "relation": relation, "label": label, "named": bool(named), "attained": attained,
        "display": {"x": values["x"], "domain": context["domain"], "relation": shown, "function": label,
                    "definition": definition, "bound_explanation": "" if attained else BOUND_EXPLANATION,
                    "bound_name": (EXTREMUM_NAMES if attained else BOUND_NAMES)[bound],
                    "extremum_name": EXTREMUM_NAMES[bound],
                    "quantifier_text": "对所有" if policy["quantifier"] == "∀" else "至少存在一个",
                    "quantifier_goal": (f"对所有 ${_latex(values['x'])}$ 都成立" if policy["quantifier"] == "∀"
                                        else f"至少有一个 ${_latex(values['x'])}$ 使它成立"),
                    "parameter": context.get("parameter")},
    }


def _compare_holds(operator, comparison):
    return {"<=": comparison <= 0, "<": comparison < 0, ">=": comparison >= 0, ">": comparison > 0}[operator]


def _bound_condition(operator, expression, value, key):
    """expression OP f(x) for all x, read through bound ``key`` and its attainment."""
    comparison = _cmp(expression, value[key])
    if operator in ("<=", ">="):
        return _compare_holds(operator, comparison)
    return _compare_holds(operator, comparison) or (comparison == 0 and not value[key + "_attained"])


def _literal(operator, key):
    """Exactly the displayed comparison ``expression OP bound``, nothing implied."""
    return lambda expression, value: _compare_holds(operator, _cmp(expression, value[key]))


def _quantified(quantifier, operator, expression, value):
    if quantifier == "∀":
        return _bound_condition(operator, expression, value, "inf" if operator in ("<=", "<") else "sup")
    key = "sup" if operator in ("<=", "<") else "inf"
    comparison = _cmp(expression, value[key])
    weak = operator in ("<=", ">=")
    strictly = comparison < 0 if operator in ("<=", "<") else comparison > 0
    return strictly or (weak and comparison == 0 and value[key + "_attained"])


def _bound_tex(facts, key, *, attained=False):
    body = facts["label"] if facts["named"] or facts["function"].is_Atom \
        else rf"\left({facts['label']}\right)"
    return f"{body}_{{{(EXTREMUM_TEX if attained or facts.get('attained') else BOUND_TEX)[key]}}}"


def _scope(facts):
    return f"${_latex(facts['x'])} \\in {_latex(facts['domain'])}$ 时，"


def _relation_label(facts, operator, key):
    bound = _bound_tex(facts, key)
    if facts["numeric"]:
        return f"{_scope(facts)}${bound} {LATEX_OPERATORS[MIRROR[operator]]} {_latex(facts['expression'])}$"
    return f"{_scope(facts)}${_latex(facts['expression'])} {LATEX_OPERATORS[operator]} {bound}$"


def _policy_proposition(facts, truth):
    if "ranges" not in facts:
        facts["ranges"] = _Ranges(facts["function"], facts["x"], facts["domain"], facts["parameter"])
    ranges = facts["ranges"]
    expression, parameter = facts["expression"], facts["parameter"]

    def evaluate(point):
        value = ranges(point)
        return truth(expression.subs(parameter, point) if parameter is not None else expression, value)
    return evaluate


def _policy_answer(facts):
    policy, operator, bound = facts["policy"], facts["operator"], facts["bound"]
    universal = policy["quantifier"] == "∀"
    needs_attainment = not facts.get("attained")
    label_operator = FLIP_STRICTNESS[operator] if needs_attainment and universal and operator in ("<", ">") else operator
    label = _relation_label(facts, label_operator, bound)
    if needs_attainment and universal and operator in ("<", ">"):
        label += f"，且{BOUND_NAMES[bound]}取到时不能相等"
    elif needs_attainment and not universal and operator in ("<=", ">="):
        label += f"，且等号成立时{BOUND_NAMES[bound]}必须能取到"
    truth = _policy_proposition(facts, lambda e, v: _quantified(policy["quantifier"], operator, e, v))
    return [{"answer": Candidate("policy:answer", label, truth)}]


def _swap_bound(facts, item):
    other = "sup" if facts["bound"] == "inf" else "inf"
    operator = facts["operator"]
    truth = _policy_proposition(facts, _literal(operator, other))
    return [Candidate("policy:swap_bound", _relation_label(facts, operator, other), truth)]


def _swap_quantifier(facts, item):
    relation = f"${facts['display']['relation']}$"
    other = "∃" if facts["policy"]["quantifier"] == "∀" else "∀"
    truth = _policy_proposition(facts, lambda e, v: _quantified(other, facts["operator"], e, v))
    scope = f"${_latex(facts['x'])} \\in {_latex(facts['domain'])}$"
    label = f"存在 {scope}，使 {relation}" if other == "∃" else f"对所有 {scope}，{relation} 都成立"
    return [Candidate("policy:swap_quantifier", label, truth)]


def _endpoint_only(facts, item):
    domain, variable, function = facts["domain"], facts["x"], facts["function"]
    result = []
    for point, closed in ((domain.start, not domain.left_open), (domain.end, not domain.right_open)):
        if not closed or not _finite(point):
            continue
        relation = facts["relation"].subs(variable, point)

        def truth(at, point=point):
            expression = facts["expression"].subs(facts["parameter"], at) if facts["parameter"] is not None \
                else facts["expression"]
            value = function.subs(variable, point).subs(facts["parameter"], at) if facts["parameter"] is not None \
                else function.subs(variable, point)
            return _compare_holds(facts["operator"], _cmp(expression, value))
        label = f"当 ${_latex(variable)}={_latex(point)}$ 时 ${_latex(relation)}$"
        result.append(Candidate(f"policy:endpoint:{point}", label, truth))
    return result


def _require_attained(facts, item):
    bound, operator = facts["bound"], facts["operator"]
    truth = _policy_proposition(
        facts, lambda e, v: bool(v[bound + "_attained"]) and _compare_holds(operator, _cmp(e, v[bound])))
    value = _bound_tex(facts, bound, attained=True)
    phrase = f"{_scope(facts)}${value}$ 存在"
    if facts["numeric"]:
        label = f"{phrase}且 ${LATEX_OPERATORS[MIRROR[operator]]} {_latex(facts['expression'])}$"
    else:
        label = f"{phrase}，且 ${_latex(facts['expression'])} {LATEX_OPERATORS[operator]} {value}$"
    return [Candidate("policy:require_attained", label, truth)]


def _flip_strictness(facts, item):
    operator, bound = FLIP_STRICTNESS[facts["operator"]], facts["bound"]
    truth = _policy_proposition(facts, _literal(operator, bound))
    return [Candidate("policy:flip_strictness", _relation_label(facts, operator, bound), truth)]


def _flip_direction(facts, item):
    operator, bound = MIRROR[facts["operator"]], facts["bound"]
    truth = _policy_proposition(facts, _literal(operator, bound))
    return [Candidate("policy:flip_direction", _relation_label(facts, operator, bound), truth)]


def _policy_roots(expression, parameter):
    """Bounded exact linear/quadratic roots; unsupported equations add no evidence."""
    if expression.free_symbols - {parameter} or expression.has(sp.Float) or sp.count_ops(expression) > 128:
        return []
    try:
        polynomial = sp.Poly(expression, parameter)
    except sp.PolynomialError:
        return []
    degree = polynomial.degree()
    if degree not in (1, 2) or any(not _finite(c) for c in polynomial.all_coeffs()):
        return []
    if degree == 1:
        roots = [-polynomial.nth(0) / polynomial.nth(1)]
    else:
        a, b, c = (polynomial.nth(index) for index in (2, 1, 0))
        discriminant = sp.simplify(b**2 - 4 * a * c)
        if discriminant.is_nonnegative is not True:
            return []
        roots = [(-b - sp.sqrt(discriminant)) / (2 * a),
                 (-b + sp.sqrt(discriminant)) / (2 * a)]
    return [point for root in roots if _finite(point := sp.simplify(root))]


def _policy_breakpoints(facts):
    """Threshold/shape changes from this card's function, relation and domain only."""
    function, variable, parameter = facts["function"], facts["x"], facts["parameter"]
    domain, expression = facts["domain"], facts["expression"]
    if parameter is None or not isinstance(domain, sp.Interval):
        return []
    equations = []
    residual = function - expression
    if residual.free_symbols <= {variable, parameter} and sp.count_ops(residual) <= 128:
        try:
            polynomial = sp.Poly(residual, variable)
        except sp.PolynomialError:
            polynomial = None
        if polynomial is not None and polynomial.degree() <= 2:
            a, b, c = (polynomial.nth(index) for index in (2, 1, 0))
            endpoints = [point for point in (domain.start, domain.end) if _finite(point)]
            equations.extend(residual.subs(variable, point) for point in endpoints)
            equations.extend((b**2 - 4 * a * c, a, b, c))
            equations.extend(2 * a * point + b for point in endpoints)
            if len(endpoints) == 2:
                equations.append(residual.subs(variable, endpoints[0]) - residual.subs(variable, endpoints[1]))
    # A separated parameter is compared with a numeric range, including a range
    # proved after an affine coordinate change. Its extrema give exact thresholds.
    if not function.free_symbols - {variable}:
        bounds = _attempt(range_at, function, variable, domain)
        if bounds:
            equations.extend(expression - bounds[key] for key in ("inf", "sup") if _finite(bounds[key]))
    roots = []
    for equation in equations:
        for point in _policy_roots(equation, parameter):
            if point not in roots:
                roots.append(point)
    return roots


def _policy_representatives(facts, values, context):
    allowed = sp.Intersection(facts["known"], values.get("case", {}).get("domain", sp.S.Reals))
    chosen = representatives(values, context, allowed)
    roots = _policy_breakpoints(facts)
    # Retain existing witness order, then exact equalities and interior points
    # between adjacent thresholds. A fixed count bounds all candidate checking;
    # missing or unsupported witnesses stay unproven in _proposition_check.
    ordered = sorted(roots, key=cmp_to_key(_cmp))
    pool = []
    for point in roots:
        index = ordered.index(point)
        left = (point + ordered[index - 1]) / 2 if index else point - NEIGHBOR
        right = (point + ordered[index + 1]) / 2 if index + 1 < len(ordered) else point + NEIGHBOR
        pool.extend((point, sp.simplify(left), sp.simplify(right)))
    for point in pool:
        if len(chosen) == MAX_POLICY_REPRESENTATIVES:
            break
        if _finite(point) and point not in chosen and allowed.contains(point) is sp.true:
            chosen.append(point)
    return chosen


def _by_quantifier(generator):
    """Feedback dictionaries may be keyed ``universal``/``existential``."""
    def tagged(facts, item):
        variant = "universal" if facts["policy"]["quantifier"] == "∀" else "existential"
        return [replace(candidate, variant=variant) for candidate in generator(facts, item)]
    return tagged


# --- Interval cases -------------------------------------------------------------

def _breakpoints(cases):
    points = []
    for case in cases:
        for point in case["domain"].boundary:
            if _finite(point) and point not in points:
                points.append(point)
    return sorted(points, key=lambda point: float(point))


def _coefficients(function, variable):
    poly = sp.Poly(sp.expand(function), variable)
    return [poly.nth(index) for index in (2, 1, 0)]


def _cases_facts(values, context):
    cases, parameter = values["cases"], values["parameter"]
    function, variable, domain = cases[0]["expression"], context["x"], context["domain"]
    bound = cases[0]["range"]["bound"]
    vertex = next((case["vertex"] for case in cases if case.get("vertex") is not None), None)
    return {
        "cases": cases, "parameter": parameter, "function": function, "x": variable, "domain": domain,
        "bound": bound, "breakpoints": _breakpoints(cases), "critical": cases[0].get("critical_polynomials", []),
        "vertex": vertex,
        "display": {"function": _named_function(values, function, variable) or function, "domain": domain,
                    "parameter": parameter, "x": variable, "bound_name": BOUND_NAMES[bound],
                    "vertex": vertex if vertex is not None else sp.S.Zero},
    }


def _sign_at(polynomial, parameter, point):
    return _sign(polynomial.subs(parameter, point))


def _basis_label(facts, used):
    pieces = []
    identifiers = {row["id"] for row in used}
    leading, slope, _ = _coefficients(facts["function"], facts["x"])
    if "leading" in identifiers:
        pieces.append(f"二次项系数 {_math(leading)} 的正负（开口方向）")
    if any(name.startswith("axis_boundary") for name in identifiers) and facts["vertex"] is not None:
        pieces.append(f"对称轴 ${_latex(facts['x'])}={_latex(facts['vertex'])}$ 与区间端点的位置")
    if "endpoint_order" in identifiers:
        pieces.append("两端点处函数值的大小")
    if "slope" in identifiers and not pieces:
        pieces.append(f"一次项系数 {_math(slope)} 的正负")
    return "、".join(pieces)


def _cases_answer(facts):
    used = [row for row in facts["critical"]
            if any(root in facts["breakpoints"] for root in row.get("roots", []))]
    label = _basis_label(facts, used)
    if not used or not label:
        raise NotInteractive("case_basis_unknown")
    parameter = facts["parameter"]
    classify = (lambda point: tuple(_sign_at(row["polynomial"], parameter, point) for row in used))
    return [{"answer": Candidate("basis:" + ",".join(row["id"] for row in used), label, classify)}]


def _covered(facts, polynomial):
    points = [point for point in facts["breakpoints"] if sp.simplify(polynomial.subs(facts["parameter"], point)) == 0]
    return "、".join(_math(point) for point in points) or "任何分界点"


def _case_basis_alternatives(facts, item):
    parameter, variable = facts["parameter"], facts["x"]
    leading, slope, constant = _coefficients(facts["function"], variable)
    variants = []
    discriminant = sp.expand(slope**2 - 4 * leading * constant)
    if parameter in discriminant.free_symbols:
        variants.append(("discriminant", f"判别式 $\\Delta={_latex(discriminant)}$ 的正负", discriminant))
    variants.append(("parameter_sign", f"参数 {_math(parameter)} 的正负", parameter))
    used = {row["id"] for row in facts["critical"]
            if any(root in facts["breakpoints"] for root in row.get("roots", []))}
    if "leading" not in used and parameter in leading.free_symbols:
        variants.append(("leading_sign", f"二次项系数 {_math(leading)} 的正负（开口方向）", leading))
    result = []
    for variant, label, polynomial in variants:
        if label == item["answer"].label:
            continue
        missing = [point for point in facts["breakpoints"]
                   if sp.simplify(polynomial.subs(parameter, point)) != 0]
        result.append(Candidate(
            "basis:" + variant, label,
            (lambda point, polynomial=polynomial: _sign(polynomial.subs(parameter, point))),
            variant, {"covered": _covered(facts, polynomial),
                      "missing": "、".join(_math(point) for point in missing) or "其他分界点"}))
    return result


def _cases_representatives(facts, values, context):
    return representatives(values, context, facts["known"])


def _breakpoint_answer(facts):
    points = facts["breakpoints"]
    if not points:
        raise NotInteractive("no_breakpoints")
    return [{"answer": Candidate("breakpoints", "", list(points))}]


def _boundary_scale(facts, item):
    result = []
    for point in facts["breakpoints"]:
        if point != 0:
            result.extend(Candidate(f"number:{value}", _math(value), value) for value in (point / 2, point * 2))
    return result


def _domain_endpoints(facts, item):
    domain = facts["domain"]
    return [Candidate(f"number:{point}", _math(point), point)
            for point in (domain.start, domain.end) if _finite(point)]


# --- Bound location in every case (one checklist row per case) -------------------

def _case_row_label(facts, case, point):
    parameter, bound = facts["parameter"], facts["bound"]
    leading, _, _ = _coefficients(facts["function"], facts["x"])
    where = []
    if parameter in leading.free_symbols:
        where.append("开口向上" if _sign(leading.subs(parameter, point)) > 0 else "开口向下")
    vertex = case.get("vertex")
    if vertex is not None and parameter in sp.sympify(vertex).free_symbols:
        where.append(f"对称轴在区间{_axis_place(vertex.subs(parameter, point), facts['domain'])}")
    condition = f"${in_set(parameter, case['domain'])}$"
    head = f"{'、'.join(where)}（{condition}）" if where else f"当 {condition} "
    name = EXTREMUM_NAMES[bound] if case["range"][bound + "_attained"] else BOUND_NAMES[bound]
    return f"{head}时，{name}"


def _case_location_answers(facts):
    """Every case whose bound sits at an end or the vertex; a constant or linear case has no place to find."""
    rows = []
    for case in facts["cases"]:
        selected = case["range"]["candidates"][0]
        region = sp.Intersection(case["domain"], facts["known"])
        if selected["location"] not in LOCATION_NAMES or selected["location"] == "critical" \
                or case.get("kind") != "quadratic" or region.is_empty:
            continue
        try:
            point = drawing.representative_parameter(region)
        except GraphUnavailable:
            point = next(iter(region), None) if isinstance(region, sp.FiniteSet) else None
        if point is None:
            continue
        local = {**facts, "selected": selected, "vertex": case.get("vertex"), "case_domain": case["domain"]}
        answer = _location_answer(local)[0]["answer"]
        rows.append({"label": _case_row_label(facts, case, point), "answer": answer, "facts": local})
    if len(rows) < 2:
        raise NotInteractive("too_few_cases")
    return rows


def _case_location_check(facts, values, context, item, candidates):
    region = sp.Intersection(item["facts"]["case_domain"], facts["known"])
    return _claim_check(item["answer"], candidates, representatives(values, context, region))


# --- Bound location -----------------------------------------------------------

def _range_facts(values, context):
    case = values.get("case") or {}
    bound = values["range"]["bound"]
    selected = values["range"]["candidates"][0]
    parameter = case.get("parameter", context.get("parameter"))
    function, variable, domain = values["before"][0], values["x"], values["domain"]
    return {
        "function": function, "x": variable, "domain": domain, "parameter": parameter, "bound": bound,
        "selected": selected, "vertex": values.get("vertex"), "case_domain": case.get("domain", sp.S.Reals),
        "display": {"function": _named_function(values, function, variable) or function, "x": variable,
                    "domain": domain, "parameter": parameter,
                    "condition": values.get("condition", sp.true),
                    "bound_name": (EXTREMUM_NAMES if values["range"][bound + "_attained"] else BOUND_NAMES)[bound]},
    }


def _natural_attained(facts, location):
    domain = facts["domain"]
    if location == "left_endpoint":
        return _finite(domain.start) and not domain.left_open
    if location == "right_endpoint":
        return _finite(domain.end) and not domain.right_open
    return True


def _claim_label(facts, location, attained):
    domain, variable = facts["domain"], _latex(facts["x"])
    if location in ("left_endpoint", "right_endpoint"):
        left = location == "left_endpoint"
        point = domain.start if left else domain.end
        if not _finite(point):
            return f"当 ${variable}\\to {'-' if left else '+'}\\infty$ 时趋近，取不到"
        if attained:
            return f"在{LOCATION_NAMES[location]} ${variable}={_latex(point)}$ 处取到"
        return f"当 ${variable}\\to {_latex(point)}^{{{'+' if left else '-'}}}$ 时趋近，取不到"
    point = facts["vertex"]
    where = f"{LOCATION_NAMES[location]} ${variable}={_latex(point)}$" if point is not None else LOCATION_NAMES[location]
    return f"在{where} 处取到" if attained else f"在{where} 附近趋近，取不到"


def _claim(facts, location, attained):
    ranges = _Ranges(facts["function"], facts["x"], facts["domain"], facts["parameter"])
    bound = facts["bound"]

    def holds(point):
        value = ranges(point)
        row = next((row for row in value["positions"] if row["location"] == location), None)
        return (row is not None and row["attained"] == attained
                and _cmp(row["value"], value[bound]) == 0)

    def witness(point):
        value = ranges(point)
        row = next((row for row in value["positions"] if row["location"] == location), None)
        parameter = f"${_latex(facts['parameter'])}={_latex(point)}$ 时"
        if row is None:
            return f"{parameter}{LOCATION_NAMES[location]}不在区间内"
        reading = "处的函数值为" if row["attained"] else "处函数趋近"
        return (f"{parameter}{LOCATION_NAMES[location]}{reading} {_math(row['value'])}，"
                f"而{BOUND_NAMES[bound]}为 {_math(value[bound])}")
    return holds, witness


def _location_answer(facts):
    selected = facts["selected"]
    location, attained = selected["location"], bool(selected["attained"])
    if location == "constant":
        raise NotInteractive("constant_function")
    holds, witness = _claim(facts, location, attained)
    return [{"answer": Candidate(f"claim:{location}:{attained}", _claim_label(facts, location, attained),
                                 (holds, witness))}]


def _location_alternatives(facts, item):
    selected = facts["selected"]["location"]
    locations = ["left_endpoint", "right_endpoint"]
    if facts["function"].is_polynomial(facts["x"]) and sp.degree(facts["function"], facts["x"]) == 2:
        locations.insert(1, "vertex")
    result = []
    for location in locations:
        if location == selected:
            continue
        attained = _natural_attained(facts, location)
        result.append(Candidate(f"claim:{location}:{attained}", _claim_label(facts, location, attained),
                                _claim(facts, location, attained)))
    return result


def _flip_location_attained(facts, item):
    selected = facts["selected"]
    location = selected["location"]
    point = facts["domain"].start if location == "left_endpoint" else facts["domain"].end
    if location not in ("left_endpoint", "right_endpoint") or not _finite(point) or selected["attained"]:
        return []
    return [Candidate(f"claim:{location}:True", _claim_label(facts, location, True),
                      _claim(facts, location, True), facts={"point": point})]


def _range_representatives(facts, values, context):
    return representatives(values, context, sp.Intersection(facts["case_domain"], facts["known"]))


# --- Parameter sets -----------------------------------------------------------

def _conditions_facts(values, context):
    case = values.get("case") or {}
    parameter = case.get("parameter", context.get("parameter"))
    return {
        "answer": values["after"][-1], "solutions": values["solutions"], "combiner": values["combiner"],
        "case_domain": case.get("domain"), "parameter": parameter,
        "display": {"condition": case.get("condition", sp.true), "parameter": parameter,
                    "conditions": "、".join(_math(item) for item in values["conditions"])},
    }


def _set_candidate(prefix, value):
    return Candidate(f"{prefix}:{sp.srepr(value)}", _math(value), value)


def _case_solution_answer(facts):
    return [{"answer": _set_candidate("set", facts["answer"])}]


def _skip_intersection(facts, item):
    if facts["case_domain"] is None:
        return []
    operation = sp.Intersection if facts["combiner"] == "all" else sp.Union
    return [_set_candidate("set", operation(*facts["solutions"]))]


def _case_only(facts, item):
    return [] if facts["case_domain"] is None else [_set_candidate("set", facts["case_domain"])]


def _flip_endpoint(facts, item):
    answer = item["answer"].value
    pieces = list(answer.args) if isinstance(answer, sp.Union) else [answer]
    result = []
    for index, piece in enumerate(pieces):
        if not isinstance(piece, sp.Interval):
            continue
        for left in (True, False):
            point = piece.start if left else piece.end
            if not _finite(point):
                continue
            flipped = sp.Interval(piece.start, piece.end,
                                  left_open=(not piece.left_open) if left else piece.left_open,
                                  right_open=piece.right_open if left else not piece.right_open)
            result.append(_set_candidate("set", sp.Union(*pieces[:index], flipped, *pieces[index + 1:])))
    return result


CASE_COUNTS = {2: "两", 3: "三", 4: "四", 5: "五"}
REQUIREMENT_WORDS = {">=": "不小于", ">": "大于", "<=": "不大于", "<": "小于"}


def _merge_requirement(values, results):
    """Summarize a shared bound condition without assuming that every case attains it."""
    relations = {(oriented(item).rel_op, oriented(item).rhs) for result in results
                 for item in result["outputs"]["conditions"] if isinstance(item, sp.Rel)}
    single = all(len(result["outputs"]["conditions"]) == 1 for result in results)
    if not single or len(relations) != 1 or next(iter(relations))[0] not in REQUIREMENT_WORDS:
        return "各情况分别要满足下面的条件"
    operator, bound = next(iter(relations))
    count = CASE_COUNTS.get(len(results), "各")
    return (f"{count}种情况下，都要求区间上的{BOUND_NAMES[values['cases'][0]['range']['bound']]}"
            f"{REQUIREMENT_WORDS[operator]} ${_latex(bound)}$")


def _merge_facts(values, context):
    parameter = values["cases"][0].get("parameter", context.get("parameter"))
    results = values.get("results") or []
    view = merge_view(values)
    return {
        "answer": values["after"][-1], "solutions": values["solutions"], "parameter": parameter,
        "cases": values["cases"], "results": results,
        "display": {"parameter": parameter, "pieces": "、".join(_math(item) for item in values["solutions"]),
                    "requirement": _merge_requirement(values, results),
                    "case_requirements": [f"{row['mark']} ${row['condition']}$：${row['requirement']}$"
                                          for row in view["merge_rows"]]},
    }


def _skip_case_intersection(facts, item):
    """Each case's conditions solved over all parameters, without keeping only that case."""
    pieces = []
    for result in facts["results"]:
        sets = result["outputs"].get("condition_sets")
        if not sets:
            return []
        pieces.append((sp.Union if result["outputs"].get("combiner") == "any" else sp.Intersection)(*sets))
    return [_set_candidate("set", sp.Union(*pieces))] if pieces else []


def _drop_piece(facts, item):
    pieces = facts["solutions"]
    return [_set_candidate("set", sp.Union(*pieces[:index], *pieces[index + 1:]))
            for index, piece in enumerate(pieces) if piece != sp.S.EmptySet and len(pieces) > 1]


def _seam_puncture(facts, item):
    answer, result = item["answer"].value, []
    pieces = [piece for piece in facts["solutions"] if piece != sp.S.EmptySet]
    for index, left in enumerate(pieces):
        for right in pieces[index + 1:]:
            left_points, right_points = [], []
            _set_points(left, left_points)
            _set_points(right, right_points)
            for point in left_points:
                if point in right_points and answer.contains(point) is sp.true:
                    result.append(_set_candidate("set", sp.Complement(answer, sp.FiniteSet(point))))
    return result


# --- Boundary and goal rows (exact evidence) -------------------------------------

def _boundary_facts(values, context):
    # Abstract-domain boundaries concern the target's outer variable, not a
    # parameter. The closing projection freezes that symbol with the evidence.
    parameter = values.get("boundary_variable", context.get("parameter"))
    return {"checks": values["checks"], "parameter": parameter,
            "display": {"feasible_set": values["feasible_set"], "parameter": parameter}}


def _boundary_answer(facts):
    rows = []
    for check in facts["checks"]:
        point = check.get("point")
        if point is None or type(check.get("holds")) is not bool:
            raise NotInteractive("boundary_point_missing")
        label = f"${_latex(facts['parameter'])}={_latex(point)}$ 时，原题条件是否成立？"
        keep = check["holds"]
        rows.append({"label": label, "answer": Candidate(f"keep:{keep}", _keep_label(point, keep), keep),
                     "point": point})
    return rows


def _keep_label(point, keep):
    return f"成立，保留 {_math(point)}" if keep else f"不成立，排除 {_math(point)}"


def _flip_keep(facts, item):
    keep = not item["answer"].value
    return [Candidate(f"keep:{keep}", _keep_label(item["point"], keep), keep)]


def _goal_facts(values, context):
    bound = "inf" if values["goal_kind"] == "find_minimum" else "sup"
    parameter = context.get("parameter")
    return {"status": values["status"], "bound": values["bound"], "parameter": parameter,
            "display": {"goal_name": EXTREMUM_NAMES[bound], "goal_bound_name": BOUND_NAMES[bound],
                        "feasible_set": values["feasible_set"], "parameter": parameter}}


def _goal_label(facts, attained):
    if attained and facts["bound"] is not None:
        return _math(facts["bound"])
    if facts["status"] == "not_attained" and not attained:
        return f"不存在（只能趋近 {_math(facts['bound'])}）"
    return "不存在"


def _goal_answer(facts):
    attained = facts["status"] == "attained"
    label = f"${_latex(facts['parameter'])}$ 的{facts['display']['goal_name']}"
    return [{"label": label, "answer": Candidate(f"goal:{attained}", _goal_label(facts, attained), attained)}]


def _flip_goal(facts, item):
    if facts["status"] not in ("attained", "not_attained"):
        return []
    attained = not item["answer"].value
    return [Candidate(f"goal:{attained}", _goal_label(facts, attained), attained)]


# --- Pictures (stem, options, completion) ---------------------------------------------

def _sample(facts, region):
    """The function to draw: itself, or at a representative parameter inside ``region``."""
    function, parameter = facts["function"], facts["parameter"]
    if parameter is None or parameter not in function.free_symbols:
        return function, None
    point = drawing.representative_parameter(region)
    return function.subs(parameter, point), point


def _sample_caption(facts, point, situation=""):
    return f"示意图：取 ${_latex(facts['parameter'])}={_latex(point)}${situation}" if point is not None else None


def _function_stem(facts, values, context):
    function, point = _sample(facts, facts["known"])
    variable, domain = facts["x"], facts["domain"]
    drawn = drawing.family(function, variable)
    marks = drawing.drawable(drawn, variable, drawing.domain_points(domain))
    bounds, x_ticks = drawing.function_frame(drawn, variable, domain, marks=marks)
    return drawing.function_graph(
        drawn, variable, domain, bounds=bounds, x_ticks=x_ticks, marks=marks,
        title=f"y={drawing.plain(drawn['function'])} 在 {drawing.plain(domain)} 上的图像",
        description=drawing.endpoint_story(drawn, variable, domain), caption=_sample_caption(facts, point))


def _axis_place(axis, domain):
    if domain.contains(axis) is sp.true:
        return "内"
    return "左侧" if _cmp(axis, domain.start) <= 0 else "右侧"


def _case_stem(facts, values, context):
    """A case where the bound sits at the vertex, so the axis and the interval both show."""
    case = next((case for case in facts["cases"] if case["range"]["candidates"][0]["location"] == "vertex"),
                facts["cases"][0])
    variable, domain = facts["x"], facts["domain"]
    function, point = _sample(facts, sp.Intersection(case["domain"], facts["known"]))
    drawn = drawing.family(function, variable)
    if drawn["kind"] != "quadratic":
        raise GraphUnavailable("family_unsupported")
    expected = case["range"]["candidates"][0]["location"]
    ranges = _Ranges(facts["function"], variable, domain, facts["parameter"])
    if expected not in _bound_positions(ranges, point, facts["bound"]):
        raise GraphUnavailable("representative_unverified")
    marks = drawing.drawable(drawn, variable, drawing.domain_points(domain))
    bounds, x_ticks = drawing.function_frame(drawn, variable, domain, marks=marks, show_vertex=True)
    place = _axis_place(drawn["vertex"][0], domain)
    return drawing.function_graph(
        drawn, variable, domain, bounds=bounds, x_ticks=x_ticks, marks=marks, show_vertex=True,
        title=f"y={drawing.plain(drawn['function'])} 的对称轴与区间 {drawing.plain(domain)}",
        description=f"对称轴 {variable}={drawing.short_label(drawn['vertex'][0])} 在区间{place}；"
                    + drawing.endpoint_story(drawn, variable, domain),
        caption=_sample_caption(facts, point, f"，此时对称轴在区间{place}"))


def _axis_stem(facts, values, context):
    """The student drags the axis across every case; a parabola whose opening moves keeps the sample picture."""
    parameter, variable, domain = facts["parameter"], facts["x"], facts["domain"]
    case = next((case for case in facts["cases"] if case["range"]["candidates"][0]["location"] == "vertex"),
                facts["cases"][0])
    known = facts.get("known", sp.S.Reals)
    lowest = facts["bound"] == "inf"
    try:
        start = drawing.representative_parameter(sp.Intersection(case["domain"], known))
        return drawing.axis_explorer(
            facts["function"], variable, parameter, domain, breakpoints=facts["breakpoints"], start=start,
            target="min" if lowest else "max", allowed=known,
            title=f"y={drawing.plain(facts['function'])} 的对称轴与区间 {drawing.plain(domain)}",
            description=f"拖动对称轴 {variable}={drawing.short_label(facts['vertex'])}，观察区间上的"
                        f"{'最低' if lowest else '最高'}点",
            caption=f"拖动对称轴 ${_latex(variable)}={_latex(facts['vertex'])}$，"
                    f"观察区间上的{'最低' if lowest else '最高'}点在哪里")
    except GraphUnavailable:
        return _case_stem(facts, values, context)


def _claim_mark(drawn, facts, positions, location, attained):
    domain = facts["domain"]
    if location == "left_endpoint":
        return domain.start
    if location == "right_endpoint":
        return domain.end
    if location == "vertex" and drawn["kind"] == "quadratic":
        return drawn["vertex"][0]
    row = next((row for row in positions if row["location"] == location), None)
    if row is None:
        raise GraphUnavailable("mark_missing")
    return row["point"]


def _location_options(facts, values, context, candidates):
    """The same curve in every option, with the claimed point marked (hollow when not attained)."""
    variable, domain = facts["x"], facts["domain"]
    function, point = _sample(facts, sp.Intersection(facts["case_domain"], facts["known"]))
    drawn = drawing.family(function, variable)
    positions = range_at(drawn["function"], variable, domain)["positions"]
    marks = []
    for candidate, correct in candidates:
        _, location, attained = candidate.key.split(":")
        holds, _ = candidate.value
        # The picture must show the case as claimed: exactly the correct claims hold at this value.
        if _attempt(holds, point) is not correct:
            raise GraphUnavailable("representative_unverified")
        marks.append((_claim_mark(drawn, facts, positions, location, attained == "True"), attained == "True"))
    bounds, x_ticks = drawing.function_frame(drawn, variable, domain, marks=marks)
    drawing.require_distinct([drawing.mark_signature(drawn, variable, bounds, *mark) for mark in marks])
    graphs = [drawing.function_graph(
        drawn, variable, domain, bounds=bounds, x_ticks=x_ticks, marks=[mark],
        title=f"y={drawing.plain(drawn['function'])} 上标出的点",
        description=(f"在 {variable}={drawing.short_label(mark[0])} 处标出"
                     f"{'实心点（取到）' if mark[1] else '空心点（取不到）'}"))
        for mark in marks]
    note = f"图中取 ${_latex(facts['parameter'])}={_latex(point)}$。" if point is not None else None
    return graphs, note


def _set_options(facts, values, context, candidates):
    parameter = facts["parameter"]
    return drawing.number_lines([candidate.value for candidate, _ in candidates], parameter,
                                title=f"{parameter} 的取值范围"), None


def _relation_side(context):
    """Which side of the axis breaks the condition, read from the frozen relation."""
    operator = context.get("interval_operator")
    if operator is not None and context.get("zero") == 0:
        return ("below" if operator in ("<=", "<") else "above"), operator in ("<", ">")
    relation = context.get("relation")
    if isinstance(relation, sp.Rel) and relation.rhs == 0:
        return ("below" if relation.rel_op in (">=", ">") else "above"), relation.rel_op in ("<", ">")
    return None, False


def _boundary_completion(seeds):
    """The kept boundary value: the curve at that parameter on the problem's interval."""
    values, context = decode_value(seeds[0]["values"]), decode_value(seeds[0]["context"])
    check = next((row for row in values.get("checks", []) if row.get("holds") is True and _finite(row.get("point"))),
                 None)
    function = context.get("interval_function", context.get("expression"))
    parameter, variable, domain = context.get("parameter"), context.get("x"), context.get("domain")
    if check is None or function is None or parameter is None or not isinstance(domain, sp.Interval):
        raise GraphUnavailable("boundary_unavailable")
    point = check["point"]
    drawn = drawing.family(function.subs(parameter, point), variable)
    side, strict = _relation_side(context)
    if side is not None:
        operator = ("<" if strict else "<=") if side == "below" else (">" if strict else ">=")
        reached = range_at(drawn["function"], variable, domain)
        if not _bound_condition(operator, sp.S.Zero, reached, "inf" if side == "below" else "sup"):
            raise GraphUnavailable("representative_unverified")
    marks = drawing.drawable(drawn, variable, drawing.domain_points(domain))
    # Outside the interval the curve may dip below the axis; keep that dip in view (faded) without marking it.
    outside = [drawn["vertex"][0]] if drawn["kind"] == "quadratic" and domain.contains(drawn["vertex"][0]) is not sp.true \
        else []
    bounds, x_ticks = drawing.function_frame(drawn, variable, domain, marks=marks, extra=outside)
    story = [drawing.endpoint_story(drawn, variable, domain)]
    for end, attained in marks:
        slope = sp.simplify(sp.diff(drawn["function"], variable).subs(variable, end))
        if attained and drawing.value_at(drawn, end, variable) == 0 and slope != 0:
            story.append(f"{variable}={drawing.short_label(end)} 处导数为 {drawing.short_label(slope)}，"
                         "曲线穿过横轴而不是相切")
    if drawn["kind"] == "quadratic":
        axis, low = drawn["vertex"]
        story.append(f"顶点 ({drawing.short_label(axis)}, {drawing.short_label(low)})")
    return drawing.function_graph(
        drawn, variable, domain, bounds=bounds, x_ticks=x_ticks, marks=marks,
        mark_sign=side, strict=strict,
        title=f"{parameter}={drawing.short_label(point)} 时 y={drawing.plain(drawn['function'])} 的图像",
        description="；".join(story),
        caption=f"${_latex(parameter)}={_latex(point)}$ 时的函数图像，只看区间 ${_latex(domain)}$")


CASE_MARKS = "①②③④⑤⑥⑦⑧⑨"


def _case_completion(seeds):
    """One explorer per case in a shared window, its axis held inside that case; all cases or none."""
    values, context = decode_value(seeds[0]["values"]), decode_value(seeds[0]["context"])
    facts = _cases_facts(values, context)
    try:
        facts["known"] = known_set(seeds[0])
        rows = _case_location_answers(facts)
    except NotInteractive as exc:
        raise GraphUnavailable("cases_unavailable") from exc
    present = [(index, case) for index, case in enumerate(facts["cases"])
               if not sp.Intersection(case["domain"], facts["known"]).is_empty]
    if len(rows) != len(present) or len(present) > len(CASE_MARKS):
        raise GraphUnavailable("case_not_drawable")
    parameter, variable, domain = facts["parameter"], facts["x"], facts["domain"]
    lowest, bound_name = facts["bound"] == "inf", EXTREMUM_NAMES[facts["bound"]]
    graphs = []
    for (index, case), row in zip(present, rows, strict=True):
        region = sp.Intersection(case["domain"], facts["known"])
        if row["facts"]["case_domain"] != case["domain"]:
            raise GraphUnavailable("case_not_drawable")
        label, mark = row["answer"].label, CASE_MARKS[index]
        statement = f"{bound_name}{label}" if label.startswith("在") else label.replace("取不到", f"{bound_name}不存在")
        graphs.append(drawing.axis_explorer(
            facts["function"], variable, parameter, domain, breakpoints=facts["breakpoints"],
            start=None, target="min" if lowest else "max",
            allowed=facts["known"], within=region,
            title=f"情况{mark}：{parameter} 在 {drawing.plain(case['domain'])} 内",
            description=f"对称轴 {variable}={drawing.short_label(facts['vertex'])} 只在本情况内拖动；{statement}",
            caption=f"情况{mark}：${in_set(parameter, case['domain'])}$，{statement}"))
    return graphs


STEM_GRAPHS = {"function_sample": ({"policy_statement"}, _function_stem),
               "case_sample": ({"case_basis"}, _case_stem),
               "axis_explorer": ({"case_basis", "case_locations"}, _axis_stem)}
OPTION_GRAPHS = {"location_marks": ({"bound_location"}, _location_options),
                 "parameter_sets": ({"case_solution", "merged_set"}, _set_options)}
COMPLETION_GRAPHS = {"boundary_function": _boundary_completion, "case_explorers": _case_completion}


def _picture(builder, diagnostics, part, *arguments, option_count=None):
    """A picture, or None with a diagnostic: pictures never block the question."""
    try:
        result = builder(*arguments)
        try:
            if option_count is None and isinstance(result, list):
                if len(result) < 2:
                    raise ValueError("interaction.graph_set_shape")
                for graph in result:
                    graph_contract.validate_graph(graph)
            elif option_count is None:
                graph_contract.validate_graph(result)
            else:
                if (not isinstance(result, tuple) or len(result) != 2 or not isinstance(result[0], list)
                        or len(result[0]) != option_count or (result[1] is not None and not isinstance(result[1], str))):
                    raise ValueError("interaction.graph_option_shape")
                for graph in result[0]:
                    graph_contract.validate_graph(graph)
        except (ValidationError, ValueError, TypeError) as exc:
            raise GraphUnavailable("invalid_graph") from exc
        return result
    except GraphUnavailable as exc:
        diagnostics.append({"part": part, "result": "graph_fallback", "reason": exc.reason})
    except Exception as exc:  # noqa: BLE001 -- a drawing fault keeps the text question.
        diagnostics.append({"part": part, "result": "graph_fallback", "reason": "graph_error",
                            "exception_type": type(exc).__name__, "message": str(exc)[:200]})
    return None


ANSWERS = {
    "policy_statement": {"kind": "proposition", "facts": _policy_facts, "answer": _policy_answer,
                         "representatives": _policy_representatives,
                         "generators": {name: _by_quantifier(generator) for name, generator in (
                             ("swap_bound", _swap_bound), ("swap_quantifier", _swap_quantifier),
                             ("endpoint_only", _endpoint_only), ("require_attained", _require_attained),
                             ("flip_strictness", _flip_strictness), ("flip_direction", _flip_direction))}},
    "case_basis": {"kind": "basis", "facts": _cases_facts, "answer": _cases_answer,
                   "representatives": _cases_representatives,
                   "generators": {"case_basis_alternatives": _case_basis_alternatives}},
    "case_breakpoints": {"kind": "number", "facts": _cases_facts, "answer": _breakpoint_answer,
                         "generators": {"boundary_scale": _boundary_scale, "domain_endpoints": _domain_endpoints}},
    "case_locations": {"kind": "claims", "checklist": True, "requires_known": True, "facts": _cases_facts,
                       "answer": _case_location_answers, "validate": _case_location_check,
                       "generators": {"location_alternatives": lambda facts, item: _location_alternatives(
                                          item["facts"], item),
                                      "flip_attained": lambda facts, item: _flip_location_attained(
                                          item["facts"], item)}},
    "bound_location": {"kind": "claim", "facts": _range_facts, "answer": _location_answer,
                       "representatives": _range_representatives,
                       "generators": {"location_alternatives": _location_alternatives,
                                      "flip_attained": _flip_location_attained}},
    "case_solution": {"kind": "set", "facts": _conditions_facts, "answer": _case_solution_answer,
                      "generators": {"skip_intersection": _skip_intersection, "case_only": _case_only,
                                     "flip_endpoint": _flip_endpoint}},
    "merged_set": {"kind": "set", "facts": _merge_facts, "answer": _case_solution_answer,
                   "label": lambda facts, value: "无解" if value == sp.S.EmptySet
                   else f"${in_set(facts['parameter'], value)}$",
                   "generators": {"drop_piece": _drop_piece, "flip_endpoint": _flip_endpoint,
                                  "seam_puncture": _seam_puncture,
                                  "skip_case_intersection": _skip_case_intersection}},
    "boundary_decisions": {"kind": "fixed", "facts": _boundary_facts, "answer": _boundary_answer,
                           "generators": {"flip_keep": _flip_keep}},
    "goal_value": {"kind": "fixed", "facts": _goal_facts, "answer": _goal_answer,
                   "generators": {"flip_attained": _flip_goal}},
}
# --- Validation -----------------------------------------------------------------

def _proposition_check(answer, candidates, points):
    def vector(candidate):
        return [_attempt(candidate.value, point) for point in points]
    expected = vector(answer)
    if all(value is None for value in expected):
        raise NotInteractive("answer_unverified")
    kept, records, seen = [], [], []
    for candidate in candidates:
        values = vector(candidate)
        witness = next((point for point, mine, theirs in zip(points, values, expected, strict=True)
                        if mine is not None and theirs is not None and mine != theirs), None)
        duplicate = any(all(a is None or b is None or a == b for a, b in zip(values, other, strict=True))
                        for other in seen)
        if witness is None or duplicate:
            records.append((candidate, "unproven" if witness is None else "duplicate", None))
            continue
        seen.append(values)
        kept.append(candidate)
        records.append((candidate, "witness", f"{_latex(witness)}"))
    return kept, records, []


def _set_check(answer, candidates, known):
    """Sets that agree on every known-allowed parameter value are the same answer."""
    def same(left, right):
        return _attempt(lambda: exact_set_equal(sp.Intersection(left, known), sp.Intersection(right, known)))
    kept, records = [], []
    for candidate in candidates:
        equal = same(candidate.value, answer.value)
        different = None if equal is None else not equal
        duplicate = any(same(candidate.value, other.value) is not False for other in kept)
        if different is not True or duplicate:
            records.append((candidate, "unproven" if different is not True else "duplicate", None))
            continue
        kept.append(candidate)
        records.append((candidate, "witness", "exact_set_mismatch"))
    return kept, records, []


def _number_check(answer, candidates):
    kept, records, taken = [], [], list(answer.value)
    for candidate in candidates:
        same = [_attempt(_cmp, candidate.value, other) for other in taken]
        if any(value is None for value in same) or 0 in same:
            records.append((candidate, "duplicate", None))
            continue
        taken.append(candidate.value)
        kept.append(candidate)
        records.append((candidate, "witness", "distinct_number"))
    return kept, records, []


def _claim_check(answer, candidates, points):
    holds, _ = answer.value
    truths = [_attempt(holds, point) for point in points]
    if not any(value is True for value in truths) or any(value is False for value in truths):
        raise NotInteractive("answer_unverified")
    kept, records, also_correct, seen = [], [], [], {answer.key}
    for candidate in candidates:
        if candidate.key in seen:
            records.append((candidate, "duplicate", None))
            continue
        seen.add(candidate.key)
        check, witness = candidate.value
        values = [_attempt(check, point) for point in points]
        failed = next((point for point, value in zip(points, values, strict=True) if value is False), None)
        if failed is None:
            reason = "also_correct" if values and all(value is True for value in values) else "unproven"
            if reason == "also_correct":
                also_correct.append(candidate)
            records.append((candidate, reason, None))
            continue
        candidate.facts.setdefault("witness", _attempt(witness, failed) or _math(failed))
        kept.append(candidate)
        records.append((candidate, "witness", _latex(failed)))
    return kept, records, also_correct


def _basis_check(answer, candidates, points, positions, parameter, facts):
    table = {point: _attempt(positions, point) for point in points}
    table = {point: value for point, value in table.items() if value}

    def counterexample(classify):
        classes = {point: _attempt(classify, point) for point in table}
        pairs = [(first, second) for index, first in enumerate(table) for second in list(table)[index + 1:]
                 if classes[first] is not None and classes[first] == classes[second]
                 and not table[first] & table[second]]
        return min(pairs, key=lambda pair: len(table[pair[0]]) + len(table[pair[1]]), default=None)
    if len(table) < 2 or counterexample(answer.value) is not None:
        raise NotInteractive("answer_unverified")
    kept, records = [], []
    names = BOUND_NAMES[facts["bound"]]
    for candidate in candidates:
        pair = counterexample(candidate.value)
        if pair is None:
            records.append((candidate, "unproven", None))
            continue
        first, second = pair

        def where(point):
            return "、".join(LOCATION_NAMES[name] for name in sorted(table[point]))
        symbol = _latex(parameter)
        candidate.facts.setdefault("witness", (
            f"${symbol}={_latex(first)}$ 与 ${symbol}={_latex(second)}$ 属于同一类，但前者{names}在{where(first)}，"
            f"后者在{where(second)}"))
        kept.append(candidate)
        records.append((candidate, "witness", f"{_latex(first)},{_latex(second)}"))
    return kept, records, []


def _validate(source, facts, values, context, item, candidates):
    if source.get("validate"):
        return source["validate"](facts, values, context, item, candidates)
    kind, answer = source["kind"], item["answer"]
    if kind == "proposition":
        return _proposition_check(answer, candidates, source["representatives"](facts, values, context))
    if kind == "claim":
        return _claim_check(answer, candidates, source["representatives"](facts, values, context))
    if kind == "basis":
        ranges = _Ranges(facts["function"], facts["x"], facts["domain"], facts["parameter"])
        points = source["representatives"](facts, values, context)
        return _basis_check(answer, candidates, points,
                            lambda point: _bound_positions(ranges, point, facts["bound"]),
                            facts["parameter"], facts)
    if kind == "set":
        return _set_check(answer, candidates, facts["known"])
    if kind == "number":
        return _number_check(answer, candidates)
    kept = [candidate for candidate in candidates if candidate.key != answer.key]
    return kept, [(candidate, "witness", "exact_evidence") for candidate in kept], []


# --- Assembly -------------------------------------------------------------------

def _distractors(source, facts, values, context, item, specifications):
    candidates, origin = [], {}
    for specification in specifications:
        produced = source["generators"][specification["generator"]](facts, item)
        for candidate in produced[:specification.get("limit", len(produced))]:
            origin[id(candidate)] = specification
            candidates.append(candidate)
    kept, records, also_correct = _validate(source, facts, values, context, item, candidates)
    diagnostics = [{"generator": origin[id(candidate)]["generator"], "label": candidate.label,
                    "result": reason, **({"witness": witness} if witness else {})}
                   for candidate, reason, witness in records]
    return [(candidate, origin[id(candidate)]) for candidate in kept], also_correct, diagnostics


def _render_text(template, display):
    return _render(template, display)


def _feedback(specification, candidate, display):
    text = specification.get("feedback")
    if isinstance(text, dict):
        text = text.get(candidate.variant, text.get("default"))
    return _render_text(text, {**display, **candidate.facts}) if text else None


def _shuffled(items, key):
    ordered = list(items)
    random.Random(int(hashlib.sha256(key.encode()).hexdigest(), 16)).shuffle(ordered)
    return ordered


def _prepare(seed, source):
    values, context = decode_value(seed["values"]), decode_value(seed["context"])
    facts = source["facts"](values, context)
    if source["kind"] in ("proposition", "basis", "claim", "set") or source.get("requires_known"):
        facts["known"] = known_set(seed)
    return values, context, facts


def _choice_part(part, number, part_id, seed):
    row = _rows(part)[0]
    source = ANSWERS[row["answer"]["from"]]
    values, context, facts = _prepare(seed, source)
    item = source["answer"](facts)[0]
    kept, also_correct, diagnostics = _distractors(source, facts, values, context, item, row["distractors"])
    limit = part.get("max_options", 4)
    display = facts["display"]
    if source["kind"] == "number":
        return (*_fill_part(part, part_id, item, kept, display, diagnostics), display)
    multi = part["component"] == "multi"
    correct = [item["answer"], *(also_correct if multi else [])]
    chosen = kept[:max(0, limit - len(correct))]
    if len(correct) + len(chosen) < part.get("min_options", 3):
        raise NotInteractive("insufficient_options", diagnostics)
    entries = [(candidate, None) for candidate in correct] + chosen
    graphs = part.get("graphs", {})
    pictures = {}
    if graphs.get("options"):
        built = _picture(OPTION_GRAPHS[graphs["options"]][1], diagnostics, number, facts, values, context,
                         [(candidate, specification is None) for candidate, specification in entries],
                         option_count=len(entries))
        if built is not None:
            pictures = {id(candidate): picture for (candidate, _), picture in zip(entries, built[0], strict=True)}
    options, answers = [], []
    for index, (candidate, specification) in enumerate(_shuffled(entries, part_id), 1):
        label = source["label"](facts, candidate.value) if "label" in source else candidate.label
        option = {"value": f"o{index}", "label": label}
        if id(candidate) in pictures:
            option["graph"] = pictures[id(candidate)]
        if specification is not None:
            message = _feedback(specification, candidate, display)
            if message:
                option["feedback"] = message
        else:
            answers.append(option["value"])
        options.append(option)
    interaction = {"type": "multi", "options": options} if multi else \
        {"type": "choice", "field": part_id, "options": options}
    expected = {"required": answers, "allowed": answers} if multi else {"one_of": answers}
    body = {"interaction": interaction, "expected_answer": expected,
            "feedback": {"answer": _render_text(part.get("feedback", ""), display)}}
    if pictures and built[1]:
        body["question_note"] = built[1]
    if graphs.get("stem"):
        stem = _picture(STEM_GRAPHS[graphs["stem"]][1], diagnostics, number, facts, values, context)
        if stem is not None:
            body["graph"] = stem
    return body, diagnostics, display


def _fill_part(part, part_id, item, kept, display, diagnostics):
    correct = item["answer"].value
    distractors = [candidate.value for candidate, _ in kept][:max(0, part.get("max_options", 4) - len(correct))]
    terms = sorted([*correct, *distractors], key=lambda point: float(point))
    if len(terms) < part.get("min_options", 3):
        raise NotInteractive("insufficient_options", diagnostics)
    names = {point: f"t{index}" for index, point in enumerate(terms, 1)}
    slot_labels = (["较小的分界点", "较大的分界点"] if len(correct) == 2
                   else [f"第 {index} 个分界点" for index in range(1, len(correct) + 1)])
    interaction = {"type": "fill", "terms": [names[point] for point in terms],
                   "term_labels": {names[point]: _math(point) for point in terms}, "slot_labels": slot_labels}
    return {"interaction": interaction, "expected_answer": {"terms": [names[point] for point in correct]},
            "feedback": {"terms": _render_text(part.get("feedback", ""), display)}}, diagnostics


def _checklist_part(part, number, part_id, seeds):
    slots, terms, diagnostics, display, first = [], [], [], {}, None
    for row in part["rows"]:
        seed = seeds[row["seed"]]
        source = ANSWERS[row["answer"]["from"]]
        values, context, facts = _prepare(seed, source)
        first = first or (facts, values, context)
        for key, value in facts["display"].items():
            display.setdefault(key, value)
        for item in source["answer"](facts):
            kept, _, records = _distractors(source, facts, values, context, item, row["distractors"])
            diagnostics.extend(records)
            kept = kept[:part.get("max_options", 4) - 1]
            if len(kept) + 1 < part.get("min_options", 2):
                raise NotInteractive("insufficient_options", diagnostics)
            slot_key = f"{part_id}/{len(slots) + 1}"
            entries = _shuffled([item["answer"], *(candidate for candidate, _ in kept)], slot_key)
            options = [{"value": f"s{len(slots) + 1}o{index}", "label": candidate.label}
                       for index, candidate in enumerate(entries, 1)]
            terms.append(options[entries.index(item["answer"])]["value"])
            slots.append({"label": item["label"], "options": options})
    if not slots:
        raise NotInteractive("no_checklist_items", diagnostics)
    interaction = {"type": "checklist", "title": part["title"], "slots": slots}
    body = {"interaction": interaction, "expected_answer": {"terms": terms},
            "feedback": {"terms": _render_text(part.get("feedback", ""), display)}}
    if stem_name := part.get("graphs", {}).get("stem"):
        stem = _picture(STEM_GRAPHS[stem_name][1], diagnostics, number, *first)
        if stem is not None:
            body["graph"] = stem
    return body, diagnostics, display


def compile_interaction(seeds, rule, repeat_context, *, interaction_id):
    """Return ``{"parts", "diagnostics"}``; raise NotInteractive for read-only.

    ``seeds`` hold one card, or two for a merge, in card order. Only these seeds,
    their exact thresholds and the fixed grid feed representatives; later cards
    are never read.
    """
    if rule.get("compiler") == "function_domain":
        return domain_interaction.compile_domain(seeds, interaction_id)
    if rule.get('compiler') == 'function_equality':
        return equality_presentation.compile_equality(seeds, interaction_id)
    if rule.get('compiler') == 'abstract_function_domain':
        from . import abstract_domain_presentation
        return abstract_domain_presentation.compile_abstract(seeds, interaction_id)
    first_values = decode_value(seeds[0]["values"])
    if rule.get("compiler") == "separated_read":
        before, after = first_values.get("before"), first_values.get("after")
        if (len(seeds) != 1 or seeds[0]["template"] != "separated" or not isinstance(before, list)
                or not isinstance(after, list) or len(before) != 1 or len(after) != 1
                or not isinstance(before[0], sp.Rel) or not isinstance(after[0], sp.Rel)
                or (before[0] != after[0] and before[0].reversed != after[0])):
            raise ValueError("interaction.already_separated_source_mismatch")
        return {"parts": [{
            "id": interaction_id + "#1", "title": "确认已分离的形式",
            "question": f"当前关系为 ${_latex(after[0])}$，参数式与自变量式已分居两侧，可沿当前形式继续。",
            "submit_label": "继续", "interaction": {"type": "read"}, "expected_answer": {},
            "feedback": {"answer": "参数式与自变量式已经分居两侧。"},
        }], "diagnostics": [{"kind": "checked_already_separated", "passed": True}]}
    if not _repeat_allows(rule, first_values, repeat_context):
        raise NotInteractive("repeat")
    parts, diagnostics, failures = [], [], []
    for number, part in enumerate(rule["parts"], 1):
        part_id = f"{interaction_id}#{number}"
        try:
            if part["component"] == "checklist":
                body, records, display = _checklist_part(part, number, part_id, seeds)
            else:
                body, records, display = _choice_part(part, number, part_id, seeds[_rows(part)[0]["seed"]])
        except NotInteractive as exc:
            failures.append(exc.reason)
            diagnostics.extend({"part": number, **record} for record in exc.diagnostics)
            diagnostics.append({"part": number, "result": "readonly", "reason": exc.reason})
            continue
        diagnostics.extend({"part": number, **record} for record in records)
        question = _render_text(part["question"], display)
        if note := body.pop("question_note", None):
            question = f"{question}{note}"
        if board := part.get("board"):
            body["stem_board"] = {"caption": _render_text(board["caption"], display), "lines": display[board["lines"]]}
        completion = part.get("graphs", {}).get("completion")
        if completion:
            picture = _picture(COMPLETION_GRAPHS[completion], diagnostics, number, seeds)
            if picture is not None:
                body["completion_graphs" if isinstance(picture, list) else "completion_graph"] = picture
        if group := part.get("completion_group"):
            body["completion_group"] = _render_text(group, display)
        parts.append({"id": part_id, "title": _render_text(part["title"], display), "question": question,
                      **body, "submit_label": part.get("submit_label", "确认判断")})
    if not parts:
        raise NotInteractive(failures[0] if len(set(failures)) == 1 else "insufficient_options", diagnostics)
    return {"parts": parts, "diagnostics": diagnostics}


def interaction_identity(seeds, revision):
    first = seeds[0]
    return _sha256({
        **{key: first[key] for key in ("run_id", "lesson_version", "target_ref", "route_id")},
        "steps": [{"step_id": seed["step_id"], "math_step_sha256": seed["math_step_sha256"]} for seed in seeds],
        "interaction_revision": revision,
    })[:24]


def _chunk_head(seeds, revision):
    first = seeds[0]
    return {
        "contract": CONTRACT,
        **{key: first[key] for key in ("run_id", "lesson_version", "target_ref", "route_id")},
        "interaction_id": interaction_identity(seeds, revision),
        "steps": [{"step_id": seed["step_id"], "math_step_sha256": seed["math_step_sha256"]} for seed in seeds],
        "interaction_revision": revision,
    }


def chunk_sha256(chunk):
    return _sha256({key: value for key, value in chunk.items() if key != "interaction_sha256"})


def readonly_chunk(seeds, revision, reason):
    """A read-only result decided without compiling (pure, safe in the parent)."""
    chunk = {**_chunk_head(seeds, revision), "status": "readonly", "parts": [], "reason": reason}
    chunk["interaction_sha256"] = chunk_sha256(chunk)
    return chunk


def build_chunk(seeds, registry, context, *, revision=None):
    """Final ``graph-step-interaction/v1`` result for one group, and diagnostics."""
    revision = revision or registry_revision(registry)
    chunk = _chunk_head(seeds, revision)
    interaction_id = chunk["interaction_id"]
    diagnostics = []
    try:
        missing = next((seed for seed in seeds if seed.get("status") != "ready"), None)
        if missing is not None:
            raise NotInteractive(missing.get("reason", "seed_missing"))
        rule = select_rule(registry, seeds)
        if rule is None:
            raise NotInteractive("no_rule")
        # A folded case card is read inside the next step, which asks for all cases at once.
        if rule.get("fold") and seeds[0]["case_path"]:
            raise NotInteractive("folded")
        compiled = compile_interaction(seeds, rule, context, interaction_id=interaction_id)
        if seeds[0].get('option_context'):
            if any(seed.get('option_context') != seeds[0]['option_context'] for seed in seeds):
                raise ValueError('interaction.mixed_option_context')
            for part in compiled['parts']:
                part['option_context'] = deepcopy(seeds[0]['option_context'])
        chunk.update(status="interactive", parts=compiled["parts"])
        diagnostics = compiled["diagnostics"]
    except NotInteractive as exc:
        chunk.update(status="readonly", parts=[], reason=exc.reason)
        diagnostics = exc.diagnostics
    except Exception as exc:  # noqa: BLE001 -- a compiler fault yields a read-only card, never a math failure.
        chunk.update(status="readonly", parts=[], reason="compile_error")
        diagnostics = [{"result": "compile_error", "exception_type": type(exc).__name__, "message": str(exc)[:300]}]
    chunk["interaction_sha256"] = chunk_sha256(chunk)
    return chunk, diagnostics


def validate_chunk(chunk):
    Draft202012Validator(json.loads(CHUNK_SCHEMA.read_text())).validate(chunk)
    graph_contract.validate_part_graphs(chunk["parts"])
    return chunk


def compile_route(seeds, registry, *, final=True, revision=None):
    """Compile every decided group of one route (tests and offline tools)."""
    groups, pending = plan_groups(seeds, registry, final=final)
    results, position = [], {seed["step_id"]: index for index, seed in enumerate(seeds)}
    for group in groups:
        context = repeat_context(seeds, position[group[0]["step_id"]])
        results.append(build_chunk(group, registry, context, revision=revision))
    return results, pending


# Everything an extension may use. Adding a name is a reviewed change to this
# list (and to its test), never an implicit dependency on a private helper.
EXTENSION_API = SimpleNamespace(
    Candidate=Candidate, NotInteractive=NotInteractive, GraphUnavailable=GraphUnavailable, drawing=drawing,
    BOUND_NAMES=BOUND_NAMES, MIRROR=MIRROR, FLIP_STRICTNESS=FLIP_STRICTNESS,
    decode_value=decode_value, known_set=known_set, representatives=representatives, range_at=range_at,
    exact_set_equal=exact_set_equal,
    latex=_latex, math=_math, cmp=_cmp, finite=_finite, attempt=_attempt,
    set_candidate=_set_candidate, set_check=_set_check, case_solution_answer=_case_solution_answer,
    flip_endpoint=_flip_endpoint, drop_piece=_drop_piece, skip_intersection=_skip_intersection,
    flip_keep=_flip_keep, conditions_facts=_conditions_facts, merge_facts=_merge_facts,
    goal_facts=_goal_facts, boundary_facts=_boundary_facts, boundary_answer=_boundary_answer,
    function_stem=_function_stem, set_options=_set_options, named_function=_named_function)


def _register_extensions():
    from . import (
        interaction_algebra,
        interaction_opening_branches,
        interaction_ranges,
        interaction_variable,
    )

    modules = (interaction_algebra, interaction_opening_branches, interaction_ranges, interaction_variable)
    tables = {"answers": ANSWERS, "stem_graphs": STEM_GRAPHS, "option_graphs": OPTION_GRAPHS,
              "completion_graphs": COMPLETION_GRAPHS}
    for module in modules:
        for name, additions in module.register(EXTENSION_API).items():
            if name not in tables or tables[name].keys() & additions.keys():
                raise ValueError("interaction.extension_conflict:" + name)
            tables[name].update(additions)
    return tuple(Path(module.__file__).resolve() for module in modules)


ENGINE_FILES += _register_extensions()
IMPLEMENTED_GENERATORS = frozenset(name for source in ANSWERS.values() for name in source["generators"])
