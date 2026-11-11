"""Auditable structural features over validated mathematical notation.

This module never solves a parameter range, checks a method's applicability,
or executes text supplied by a model. Symbolic work starts at the bound AST.
"""

import re
from copy import deepcopy
from dataclasses import asdict, dataclass

import sympy as sp

from ...problem_understanding.notation_compile import NotationValidator, children
from ...problem_understanding.notation_parser import NotationError, parse
from ...problem_understanding.notation_semantics import Canonical, bounded_expand
from ...problem_understanding.review_contract import pointer
from . import contracts
from .abstract_function_domain import VERSION as ABSTRACT_DOMAIN_VERSION
from .abstract_function_domain import describe_abstract_domain_goal
from .abstract_function_range import VERSION as ABSTRACT_RANGE_VERSION
from .abstract_function_range import describe_abstract_range_goal
from .function_domain import VERSION as DOMAIN_VERSION
from .function_domain import describe_domain_goal
from .function_domain_parameter import VERSION as DOMAIN_PARAMETER_VERSION
from .function_domain_parameter import describe_match_domain_goal
from .function_equality import VERSION as COMPARISON_VERSION
from .function_equality import describe_comparison_goal
from .function_evaluation import VERSION as EVALUATION_VERSION
from .function_evaluation import describe_evaluation_goal
from .function_range import VERSION as RANGE_VERSION
from .function_range import describe_range_goal

SCHEMA_VERSION = "graph-stage-one-features/v1"
EXTRACTOR_VERSION = "structural-polynomial/v1"


@dataclass(frozen=True)
class FeatureSpec:
    feature_id: str
    dependencies: tuple[str, ...]
    output_type: str
    knowledge_refs: tuple[str, ...]
    student_template: str
    category: str = "structural"
    version: str = EXTRACTOR_VERSION
    supported_structures: tuple[str, ...] = ("single_quantified_scalar_relation",)
    computation_boundary: str = (
        "bound AST, polynomial expansion and coefficient collection only"
    )


FEATURE_REGISTRY = (
    FeatureSpec('parity_parameter', ('goal',), 'parity_parameter',
                ('function-parity#definition', 'function-parity#zero'), '已知奇偶性求函数参数',
                version='parity-parameter/r3-v1', supported_structures=('quadratic_parity_parameter', 'affine_parity_domain', 'original_parity_parameter', 'joint_affine_parity_parameter'),
                computation_boundary='bound parity, original polynomial/local rule and affine domain syntax; no parameter solving'),
    FeatureSpec('function_parity', ('goal',), 'function_parity',
                ('function-parity#definition', 'function-parity#domain'), '判断具体函数的奇偶性',
                version='function-parity-definition/v2', supported_structures=('explicit_function_parity',),
                computation_boundary='original bound rule, declared input set and its role only; no reflected rule or natural domain'),
    FeatureSpec('abstract_monotonicity', ('goal',), 'abstract_monotonicity',
                ('function-monotonicity#definition', 'quantifiers#instantiation'), '由函数关系与符号条件判断抽象函数的单调性',
                version='abstract-monotonicity/v2', supported_structures=('additive_relation', 'multiplicative_input_relation', 'exponential_relation', 'power_relation'),
                computation_boundary='original relation, its universal variables and scope, a strict sign condition and the asked interval; no formula for the function'),
    FeatureSpec('monotonicity_parameter', ('goal',), 'monotonicity_parameter',
                ('function-monotonicity#definition',), '已知指定区间上的严格增减性求函数参数',
                version='monotonicity-parameter/v6', supported_structures=('quadratic_parameter', 'piecewise_parameter', 'radical_parameter', 'reciprocal_parameter'),
                computation_boundary='parametric degree-≤2 expression, its square root, c/x+d, s*x+c/x+d, or explicit piecewise including singleton branches; fixed interval, strict direction and one real parameter'),
    FeatureSpec('monotonicity_inequality', ('goal',), 'monotonicity_inequality',
                ('function-monotonicity#definition',), '利用严格单调性把函数值比较转为输入比较',
                version='monotonicity-inequality/v1', supported_structures=('known_strict_order',),
                computation_boundary='known monotonicity fact, same-function calls and polynomial inputs'),
    FeatureSpec('function_extremum', ('goal',), 'function_extremum',
                ('function-range-extrema#extrema',), '利用增减与取得性求最值或参数',
                version='function-extremum/v1', supported_structures=('bounded_extrema',),
                computation_boundary='original function, ordered quantifiers, extrema condition and source domains'),
    FeatureSpec('function_monotonicity', ('goal',), 'function_monotonicity',
                ('function-monotonicity#definition',), '判断原函数的严格单调区间',
                version='function-monotonicity/v1', supported_structures=('bounded_quadratic_root_absolute',),
                computation_boundary='original expression, direction, declared domain and structure only'),
    FeatureSpec('piecewise_modeling', ('goal',), 'piecewise_modeling',
                ('piecewise-function#definition',), '根据超出部分的单价累计各档费用',
                version='piecewise-modeling/v1', supported_structures=('marginal_electricity_pricing',),
                computation_boundary='source terms, decimal prices, thresholds and units only'),
    FeatureSpec('piecewise_range_parameter', ('goal',), 'piecewise_range_parameter',
                ('piecewise-function#domain-range',), '已知完整值域，求分段函数中的参数范围',
                version='piecewise-range-parameter/v1', supported_structures=('fixed_piece_parametric_quadratic',),
                computation_boundary='original definition, given output set and fixed branch predicates only'),
    FeatureSpec('piecewise_inequality', ('goal',), 'piecewise_inequality',
                ('piecewise-function#definition', 'piecewise-function#inequality'),
                '先确定比较值，再逐段解不等式并检查本段范围', version='piecewise-inequality/v1',
                supported_structures=('single_layer_polynomial_piecewise_inequality',),
                computation_boundary='bound source definition, relation, numeric threshold input, branch predicates and degree only'),
    FeatureSpec('piecewise_equation', ('goal',), 'piecewise_equation',
                ('piecewise-function#definition', 'piecewise-function#equation'),
                '已知分段函数的值，逐段求输入并检查本段范围', version='piecewise-equation/v1',
                supported_structures=('single_layer_polynomial_piecewise_equation',),
                computation_boundary='bound source definition, equality, fixed branch predicates and degree only'),
    FeatureSpec('function_graph', ('goal',), 'function_graph',
                ('function-representations#graph', 'function-graph-transformations#translation'),
                '由解析式或已核对的原图判断目标图像', version='function-graph/v5',
                supported_structures=('affine_absolute_graph_choices', 'absolute_polynomial_graph_tasks', 'absolute_quadratic_translation_choices', 'schematic_horizontal_transform_choices'),
                computation_boundary='inspect source formula, domain, goal and labelled graph facts; do not solve or infer option formulas'),
    FeatureSpec('function_formula', ('goal',), 'function_formula',
                ('function-concept#elements', 'function-representations#analytic'),
                '由未知函数的整体输入关系恢复规则', version='function-formula-root/v1',
                supported_structures=('affine_root_input',),
                computation_boundary='仅检查原式结构和范围约束，不恢复函数或读取答案'),
    FeatureSpec('translation_range', ('goal',), 'translation_range',
                ('function-concept#elements', 'function-range-extrema#attainability'),
                '按整数平移传递已知完整值域', version='translation-range/v1',
                supported_structures=('linear_plus_periodic_function',),
                computation_boundary='source-bound periodic identity and range assertions only'),
    FeatureSpec('abstract_function_range', ('goal',), 'abstract_function_range',
                ('function-concept#elements', 'function-concept#composite-domain'),
                '检验新输入覆盖原定义域后传递已知值域', version=ABSTRACT_RANGE_VERSION,
                supported_structures=('known_range_affine_input_transfer',),
                computation_boundary='original known domain, range and affine input syntax only'),
    FeatureSpec('function_range', ('goal',), 'function_range',
                ('function-concept#elements', 'function-range-extrema#attainability'),
                '确定给定输入范围内的全部函数输出', version=RANGE_VERSION,
                supported_structures=('fixed_polynomial_interval_image',),
                computation_boundary='original function, interval sources and bounded coefficients only'),
    FeatureSpec(
        'function_evaluation', ('goal',), 'function_evaluation',
        ('function-concept#definition', 'function-concept#elements'),
        '将完整输入放进已有函数规则', version=EVALUATION_VERSION,
        supported_structures=('explicit_function_forward_evaluation',),
        computation_boundary='original bound calls, complete visible definitions and shared structural budgets only',
    ),
    FeatureSpec(
        'function_comparison', ('goal',), 'function_comparison',
        ('function-concept#identity',), '比较各函数的定义域和对应关系',
        version=COMPARISON_VERSION,
        supported_structures=('option_scoped_function_comparison',),
        computation_boundary='original scoped expression and declared-domain syntax only; no solving',
    ),
    FeatureSpec(
        'abstract_function_domain', ('goal',), 'abstract_function_domain',
        ('function-concept#elements', 'function-concept#composite-domain'),
        '抽象对应关系的已知输入范围与目标完整输入为 {value}',
        version=ABSTRACT_DOMAIN_VERSION,
        supported_structures=('identity_known_affine_target_domain',),
        computation_boundary='original call and declared-domain syntax only; no solving',
    ),
    FeatureSpec(
        "function_domain", ("goal",), "function_domain",
        ("function-concept#elements",), "具体函数的原始输入结构为 {value}",
        version=DOMAIN_VERSION,
        supported_structures=("fixed_affine_function_domain", "domain_parameter_reals_quadratic",
                              "domain_parameter_halfline_root_ratio"),
        computation_boundary="original bound AST and exact rational affine syntax only; no condition solving",
    ),
    FeatureSpec(
        "quantifier",
        (),
        "enum",
        ("quantifiers#universal", "quantifiers#existential"),
        "量词为 {value}",
    ),
    FeatureSpec(
        "bound_vars",
        ("quantifier",),
        "symbols",
        ("quantifiers#roles",),
        "量词变量为 {value}",
    ),
    FeatureSpec(
        "free_vars",
        ("quantifier", "goal"),
        "symbols",
        ("quantifiers#roles",),
        "自由变量为 {value}",
    ),
    FeatureSpec("goal", (), "goal", ("quantifiers#roles",), "所求为 {value}"),
    FeatureSpec(
        "domain",
        ("quantifier",),
        "domain",
        ("quantifiers#domain",),
        "变量范围为 {value}",
    ),
    FeatureSpec(
        "domain_kind",
        ("domain",),
        "enum",
        ("quantifiers#domain",),
        "范围类型为 {value}",
    ),
    FeatureSpec(
        "relation",
        ("quantifier",),
        "relation",
        ("quadratic-inequality#definition",),
        "原关系为 {value}",
    ),
    FeatureSpec(
        "normal_form",
        ("relation",),
        "relation",
        ("quadratic-inequality#definition",),
        "移项整理为 {value}",
    ),
    FeatureSpec(
        "degree_in_bound",
        ("normal_form", "bound_vars"),
        "polynomial_degree",
        ("quadratic-function-properties#definition",),
        "关于量词变量的次数为 {value}",
    ),
    FeatureSpec(
        "degree_in_goal",
        ("normal_form", "goal"),
        "polynomial_degree",
        ("quadratic-function-properties#definition",),
        "关于所求变量的次数为 {value}",
    ),
    FeatureSpec(
        "leading_coeff_in_bound",
        ("degree_in_bound",),
        "coefficient",
        ("quadratic-function-properties#definition",),
        "首项系数为 {value}",
    ),
    FeatureSpec(
        "coefficients",
        ("degree_in_bound",),
        "coefficients",
        ("quadratic-function-properties#definition",),
        "各项系数为 {value}",
    ),
    FeatureSpec(
        "range_var_is_principal",
        ("degree_in_bound", "degree_in_goal"),
        "boolean",
        ("quantifiers#roles",),
        "给出范围的变量是否为二次式主元：{value}",
    ),
)
_SPECS = {item.feature_id: item for item in FEATURE_REGISTRY}


def registry():
    """Serializable registry; method-precondition entries belong to stage three."""
    return {
        "schema_version": "graph-feature-registry/v1",
        "categories": ["structural", "method_precondition"],
        "features": [asdict(item) for item in FEATURE_REGISTRY],
    }


def _math(expression):
    return sp.sstr(expression).replace("**", "^")


def _json_path(path):
    path = re.sub(r"^r(?=\.|$)", "/root", path)
    path = re.sub(r"\.c(\d+)", r"/children/\1", path)
    return re.sub(r"\[(\d+)\]", r"/\1", path.replace(".", "/"))


def _refs(ast, kind):
    found = [ast] if ast[0] == kind else []
    for child in children(ast):
        found.extend(_refs(child, kind))
    return found


def _is_node(value):
    return isinstance(value, list) and bool(value) and isinstance(value[0], str)


def _substitute(ast, argument):
    if ast == ["bound", "function_argument"]:
        return deepcopy(argument)
    return [_substitute(item, argument) if _is_node(item) else item for item in ast]


def _inline(ast, functions, used, arguments, depth=0):
    """Replace calls of visible one-argument function definitions by their bodies.

    Arguments are collected as well: a body may ignore its argument, but the
    argument's well-definedness conditions (e.g. f(1/x)) still apply.
    """
    if depth > 12:
        raise NotationError("feature.function_depth_limit")
    if ast[0] == "function_call":
        if len(ast) != 3 or ast[1][1] not in functions:
            raise NotationError("feature.unsupported_function_call")
        used.add(ast[1][1])
        argument = _inline(ast[2], functions, used, arguments, depth + 1)
        arguments.append(argument)
        return _inline(
            _substitute(functions[ast[1][1]], argument),
            functions,
            used,
            arguments,
            depth + 1,
        )
    return [
        _inline(item, functions, used, arguments, depth) if _is_node(item) else item
        for item in ast
    ]


def _scopes(scope, ancestors=()):
    yield scope, ancestors
    for child in scope["children"]:
        yield from _scopes(child, (*ancestors, scope))


def conjunct_quantifiers(ast):
    """Quantifiers asserted as a fact or as a conjunct of one; never nested ones."""
    if ast[0] == "quantifier":
        return [ast]
    if ast[0] == "and":
        return [found for child in ast[1:] for found in conjunct_quantifiers(child)]
    return []


# Domain failures that only mean "this domain form is not modelled"; the
# relation is still read. Any other failure makes the domain invalid or unknown.
_REPRESENTATION_ONLY = ("feature.unsupported_",)


class _Algebra(Canonical):
    """Reuse bounded arithmetic, preserving readable names and obligations."""

    def __init__(self, objects, bound_names):
        super().__init__()
        self.names = {obj["ref"]: obj["name"] for obj in objects}
        self.bound_names = bound_names
        self.conditions = []
        self.values = {}

    def expr(self, ast, depth=0):
        if depth > 40:
            raise NotationError("semantic.depth_limit")
        if id(ast) in self.values:
            return self.values[id(ast)]
        kind = ast[0]
        if kind == "ref" and ast[2] == "scalar":
            return sp.Symbol(self.names[ast[1]], real=True)
        if kind == "bound":
            if ast[1] not in self.bound_names:
                raise NotationError("feature.unsupported_bound_variable")
            return sp.Symbol(self.bound_names[ast[1]], real=True)
        if kind not in ("number", "+", "-", "*", "/", "^", "neg", "call"):
            raise NotationError("feature.unsupported_scalar_structure", kind)
        if kind == "call" and ast[1] != "sqrt":
            raise NotationError("feature.unsupported_scalar_function", ast[1])
        result = super().expr(ast, depth)
        self.values[id(ast)] = result
        if kind == "/":
            denominator = self.expr(ast[2], depth + 1)
            if denominator.is_zero is not False:
                self._condition(denominator, "!=")
        elif kind == "^" and self.expr(ast[2], depth + 1).is_negative:
            base = self.expr(ast[1], depth + 1)
            if base.is_zero is not False:
                self._condition(base, "!=")
        elif kind == "call" and ast[1] == "sqrt":
            radicand = self.expr(ast[2], depth + 1)
            if radicand.is_nonnegative is not True:
                self._condition(radicand, ">=")
        return result

    def _condition(self, expression, operator):
        if not expression.free_symbols:
            holds = expression != 0 if operator == "!=" else expression >= 0
            if holds is sp.false or holds is False:
                raise NotationError("feature.undefined_expression", _math(expression))
            if holds is sp.true or holds is True:
                return
        item = {
            "expression": _math(expression),
            "operator": operator,
            "rhs": "0",
            "origin": "well_definedness",
        }
        if item not in self.conditions:
            self.conditions.append(item)


def _domain(ast, algebra):
    if ast[0] == "real":
        return {
            "expression": "ℝ",
            "lower": "-∞",
            "upper": "∞",
            "left_closed": False,
            "right_closed": False,
            "bounded": False,
        }, "real"
    if ast[0] != "interval":
        raise NotationError("feature.unsupported_domain")
    ends = [
        ("-∞" if value[1] == -1 else "∞")
        if value[0] == "infinity"
        else _math(algebra.expr(value))
        for value in ast[3:]
    ]
    infinite = sum(value[0] == "infinity" for value in ast[3:])
    return {
        "expression": f"{'[' if ast[1] else '('}{ends[0]},{ends[1]}{']' if ast[2] else ')'}",
        "lower": ends[0],
        "upper": ends[1],
        "left_closed": ast[1],
        "right_closed": ast[2],
        "bounded": infinite == 0,
    }, {0: "bounded_interval", 1: "half_infinite_interval", 2: "real"}[infinite]


def _polynomial(expression, variable):
    symbol = sp.Symbol(variable, real=True)
    poly = sp.Poly(expression, symbol)
    if poly.is_zero:
        degree, kind = None, "zero_polynomial"
    else:
        degree = int(poly.degree())
        # Parameter-dependent coefficients may vanish; no root/sign analysis
        # is performed here, even if SymPy could prove a stronger statement.
        kind = "upper_bound" if poly.LC().free_symbols else "exact"
    return poly, {
        "variable": variable,
        "degree": degree,
        "degree_kind": kind,
        "expression": _math(expression),
    }


def extract_features(candidate):
    """Extract structural features, retaining failures as explicit unknowns.

    Features are computed per goal. Each goal sees the facts of its own scope
    and its ancestors, never those of sibling sub-questions. ``ok`` says the
    input scope was valid and the extractor completed. It does not imply every
    feature is known: downstream acceptance checks required features
    explicitly. ``source_refs`` are JSON pointers into the candidate root.
    """
    report = NotationValidator().validate_root(
        candidate.get("root"), contracts.schema()["$defs"]
    )
    result = {
        "schema_version": SCHEMA_VERSION,
        "features": [],
        "ok": report.ok,
        "diagnostics": [],
    }
    if not report.ok:
        result["diagnostics"] = deepcopy(report.issues)
        return result
    goal_count = 0
    for scope, ancestors in _scopes(report.semantic):
        goal_count += len(scope["goals"])
        _scope_features(report, candidate, scope, ancestors, result["features"])
    if not goal_count:
        result.update(
            ok=False,
            diagnostics=[{"code": "feature.goal_required", "path": "/root/goals"}],
        )
    return result


def _scope_features(report, candidate, scope, ancestors, features):
    objects = {obj["ref"]: obj for obj in report.objects}
    scope_ref = _json_path(scope["scope"])
    visible = [*ancestors, scope]
    records = [
        record
        for item in visible
        for record in report.scope_facts.get(item["scope"], [])
    ]
    functions, function_sources = {}, {}
    for record in records:
        fact = record["value"]
        if fact[0] == "function_definition":
            functions[fact[1][1]] = fact[2]
            function_sources[fact[1][1]] = _json_path(record["path"])
    quantifiers = [
        (quantified, record)
        for record in records
        for quantified in conjunct_quantifiers(record["value"])
    ]

    for goal_index, goal in enumerate(scope["goals"]):
        target_ref = f"{scope_ref}/goals/{goal_index}"
        produced = {}
        # Conditions found while reading the domain travel with every later
        # feature; so does the evidence (domain and its definitions) behind them.
        inherited = {"conditions": 0, "source_refs": [], "dependencies": []}

        def add(
            feature_id,
            value=None,
            *,
            source_refs=(),
            calculation=None,
            conditions=(),
            diagnostic=None,
            _target_ref=target_ref,
            _produced=produced,
            _inherited=inherited,
        ):
            spec = _SPECS[feature_id]
            carries = len(conditions) >= _inherited["conditions"] > 0
            dependencies = list(spec.dependencies)
            if carries:
                source_refs = [*source_refs, *_inherited["source_refs"]]
                dependencies += [d for d in _inherited["dependencies"] if d not in dependencies]
            feature = {
                "feature_id": feature_id,
                "scope": scope_ref,
                "target_ref": _target_ref,
                "status": "unknown"
                if diagnostic
                else "conditional"
                if conditions
                else "known",
                "value": value,
                "conditions": deepcopy(list(conditions)),
                "dependencies": dependencies,
                "source_refs": sorted(set(source_refs)),
                "calculation": calculation or {"operation": "read_bound_ast"},
                "diagnostics": [diagnostic] if diagnostic else [],
                "extractor_version": spec.version,
                "knowledge_refs": list(spec.knowledge_refs),
            }
            _produced[feature_id] = feature
            features.append(feature)

        if 'pricing' in goal:
            from ..piecewise_modeling import describe
            desc = describe(report, scope, ancestors, goal_index, original_text=candidate['original_text'])
            add('goal', {'kind': goal['kind'], 'symbol': goal['target'][1].rsplit(':', 1)[-1]}, source_refs=[target_ref])
            add('piecewise_modeling', desc, source_refs=desc['source_refs'])
            for spec in FEATURE_REGISTRY:
                if spec.feature_id not in produced:
                    add(spec.feature_id, diagnostic={'code': 'feature.not_pricing'}, source_refs=[target_ref])
            continue
        if goal['kind'] == 'match_range':
            from ..piecewise_range_parameter import describe
            desc = describe(report, scope, ancestors, goal_index)
            add('goal', {'kind': 'match_range', 'symbol': desc['variable']}, source_refs=[target_ref])
            add('piecewise_range_parameter', desc, source_refs=desc['source_refs'])
            for spec in FEATURE_REGISTRY:
                if spec.feature_id not in produced:
                    add(spec.feature_id, diagnostic={'code': 'feature.not_range_parameter'}, source_refs=[target_ref])
            continue
        from ..extremum_math import routed_description as extremum_description
        from ..monotonicity_inequality_math import (
            routed_description as mono_inequality_description,
        )
        from ..monotonicity_parameter_math import (
            routed_description as mono_parameter_description,
        )
        original = pointer(candidate, target_ref)
        sources = [{'source_ref': _json_path(row['path']), 'expression': pointer(candidate, _json_path(row['path']))} for row in records]
        from ..parity_parameter_math import describe as parity_parameter_description
        parity_entries = [{**src, 'ast': row['value']} for src, row in zip(sources, records, strict=True)]
        if desc := parity_parameter_description(original, goal, target_ref, parity_entries, candidate=candidate):
            add('goal', {'kind': goal['kind'], **({'symbol': desc['parameter']} if goal['kind'] == 'find_range' else {})}, source_refs=[target_ref])
            add('parity_parameter', desc, source_refs=desc['source_refs'])
            for spec in FEATURE_REGISTRY:
                if spec.feature_id not in produced:
                    add(spec.feature_id, diagnostic={'code': 'feature.not_parity_parameter_goal'}, source_refs=[target_ref])
            continue
        if desc := mono_parameter_description(original, target_ref, sources):
            add('goal', {'kind': goal['kind'], 'symbol': original['symbol']}, source_refs=[target_ref])
            add('monotonicity_parameter', desc, source_refs=desc['source_refs'])
            for spec in FEATURE_REGISTRY:
                if spec.feature_id not in produced:
                    add(spec.feature_id, diagnostic={'code': 'feature.not_mono_parameter_goal'}, source_refs=[target_ref])
            continue
        if desc := mono_inequality_description(original, target_ref, sources):
            add('goal', {'kind': goal['kind'], 'symbol': original['symbol']}, source_refs=[target_ref])
            add('monotonicity_inequality', desc, source_refs=desc['source_refs'])
            for spec in FEATURE_REGISTRY:
                if spec.feature_id not in produced:
                    add(spec.feature_id, diagnostic={'code': 'feature.not_mono_inequality_goal'}, source_refs=[target_ref])
            continue
        if desc := extremum_description(original, target_ref, sources):
            identity = ({'object': original['object']} if 'object' in original else
                        {'symbol': original.get('symbol', original.get('expression'))})
            add('goal', {'kind': goal['kind'], **identity}, source_refs=[target_ref])
            add('function_extremum', desc, source_refs=desc['source_refs'])
            for spec in FEATURE_REGISTRY:
                if spec.feature_id not in produced:
                    add(spec.feature_id, diagnostic={'code': 'feature.not_extremum_goal'}, source_refs=[target_ref])
            continue
        from ..piecewise_inequality import describe as describe_piecewise_inequality
        from ..piecewise_inequality import relevant as piecewise_inequality_relevant
        if piecewise_inequality_relevant(goal, records):
            desc = describe_piecewise_inequality(report, scope, ancestors, goal_index)
            add('goal', {'kind': 'find_range', 'symbol': desc['variable']}, source_refs=[target_ref])
            add('piecewise_inequality', desc, source_refs=desc['source_refs'])
            for spec in FEATURE_REGISTRY:
                if spec.feature_id not in produced:
                    add(spec.feature_id, diagnostic={'code': 'feature.not_piecewise_inequality'}, source_refs=[target_ref])
            continue
        from ..piecewise_equation import describe as describe_piecewise_equation
        from ..piecewise_equation import relevant as piecewise_equation_relevant
        if piecewise_equation_relevant(goal, records):
            desc = describe_piecewise_equation(report, scope, ancestors, goal_index)
            add('goal', {'kind': 'find_range', 'symbol': desc['variable']}, source_refs=[target_ref])
            add('piecewise_equation', desc, source_refs=desc['source_refs'])
            for spec in FEATURE_REGISTRY:
                if spec.feature_id not in produced:
                    add(spec.feature_id, diagnostic={'code': 'feature.not_piecewise_equation'}, source_refs=[target_ref])
            continue
        if goal['kind'] == 'determine_monotonicity_on_interval' or (
                    goal['kind'] == 'prove_monotonicity_on_interval' and 'relation' in goal):
            from ..abstract_monotonicity_math import describe as describe_abstract
            original = {key: value for key, value in goal.items() if key != 'target'}
            sources = [{'source_ref': _json_path(row['path']), 'expression': pointer(candidate, _json_path(row['path']))}
                       for row in records]
            description = describe_abstract(original, target_ref, sources)
            add('goal', {'kind': goal['kind']}, source_refs=[target_ref])
            add('abstract_monotonicity', description, source_refs=description['source_refs'])
            for spec in FEATURE_REGISTRY:
                if spec.feature_id not in produced:
                    add(spec.feature_id, diagnostic={'code': 'feature.not_abstract_monotonicity_goal'}, source_refs=[target_ref])
            continue
        if goal['kind'] in ('find_monotonic_intervals', 'prove_monotonicity_on_interval'):
            from ..function_monotonicity import describe
            original = {key: value for key, value in goal.items() if key != 'target'}
            sources = [{'source_ref': _json_path(row['path']), 'expression': pointer(candidate, _json_path(row['path']))}
                       for row in records]
            description = describe(original, target_ref, sources)
            add('goal', {'kind': goal['kind']}, source_refs=[target_ref])
            add('function_monotonicity', description, source_refs=[*description['source_refs'], *description['extra_source_refs']])
            for spec in FEATURE_REGISTRY:
                if spec.feature_id not in produced:
                    add(spec.feature_id, diagnostic={'code': 'feature.not_monotonicity_goal'}, source_refs=[target_ref])
            continue
        if goal['kind'] in ('select_function_graph', 'draw_function_graph', 'solve_graph_inequality'):
            from ..function_graph import describe_scoped
            original = {key: value for key, value in goal.items() if key != 'target'}
            sources = [{'source_ref': _json_path(row['path']), 'expression': pointer(candidate, _json_path(row['path']))}
                       for row in records]
            description = describe_scoped(original, target_ref, sources)
            add('goal', {'kind': goal['kind']}, source_refs=[target_ref])
            add('function_graph', description, source_refs=[*description['source_refs'], *description['extra_source_refs']])
            for spec in FEATURE_REGISTRY:
                if spec.feature_id not in produced:
                    add(spec.feature_id, diagnostic={'code': 'feature.not_applicable_to_graph_goal'}, source_refs=[target_ref])
            continue
        if goal['kind'] == 'find_function_formula' or (goal['kind'] in ('find_value', 'find_range') and 'relation' in goal):
            from .function_formula import describe_function_formula
            description = describe_function_formula(report, scope, ancestors, goal_index)
            add('goal', {'kind': goal['kind'], **({'symbol': description['variable']} if goal['kind'] == 'find_range' else {})}, source_refs=[target_ref])
            add('function_formula', description,
                source_refs=[target_ref, *description['source_refs'], *description['extra_source_refs']])
            for spec in FEATURE_REGISTRY:
                if spec.feature_id not in produced:
                    add(spec.feature_id, diagnostic={'code': 'feature.not_function_formula_goal'}, source_refs=[target_ref])
            continue
        if goal['kind'] == 'find_translation_range':
            from .translation_range import describe_translation_range
            add('goal', {'kind': goal['kind']}, source_refs=[target_ref])
            description = describe_translation_range(report, scope, ancestors, goal_index)
            add('translation_range', description, source_refs=[target_ref, *description['source_refs']])
            for spec in FEATURE_REGISTRY:
                if spec.feature_id not in produced:
                    add(spec.feature_id, diagnostic={'code': 'feature.not_translation_range_goal'}, source_refs=[target_ref])
            continue
        goal_ast = goal["target"]
        if goal['kind'] in ('find_range', 'select_range_domain', 'find_extrema_expression') and goal_ast[:1] == ['ref'] and goal_ast[2] == 'function':
            add('goal', {'kind': goal['kind'], 'object': goal_ast[1].rsplit(':', 1)[-1]}, source_refs=[target_ref])
            try:
                description = describe_range_goal(report, scope, ancestors, goal_index)
                refs = [target_ref, description['source_ref'], description['declared_domain_source_ref'],
                        description['input_domain_source_ref'], *(r['source_ref'] for r in description['restriction_facts'])]
                add('function_range', description, source_refs=list(dict.fromkeys(
                    target_ref if ref.startswith(target_ref + '/') else ref for ref in refs if ref)))
            except (NotationError, ValueError, TypeError) as exc:
                add('function_range', diagnostic={'code': getattr(exc, 'code', 'range.invalid_structure')}, source_refs=[target_ref])
            for spec in FEATURE_REGISTRY:
                if spec.feature_id not in produced:
                    add(spec.feature_id, diagnostic={'code': 'feature.not_function_range_goal'}, source_refs=[target_ref])
            continue
        if goal['kind'] in ('find_value', 'check_constant', 'finite_sum'):
            add('goal', {'kind': goal['kind']}, source_refs=[target_ref])
            produced['goal']['knowledge_refs'] = ['function-concept#definition', 'function-concept#elements']
            try:
                description = describe_evaluation_goal(report, scope, ancestors, goal_index)
                source_refs = [target_ref, *(f['source_ref'] for f in description['functions'])]
                source_refs += [f['input_domain_source_ref'] for f in description['functions']
                                if f.get('input_domain_source_ref')]
                add('function_evaluation', description, source_refs=source_refs)
            except (NotationError, ValueError, TypeError) as exc:
                add('function_evaluation', diagnostic={'code': getattr(exc, 'code', 'evaluation.invalid_structure')},
                    source_refs=[target_ref])
            for spec in FEATURE_REGISTRY:
                if spec.feature_id not in produced:
                    add(spec.feature_id, diagnostic={'code': 'feature.not_evaluation_goal'}, source_refs=[target_ref])
            continue
        if goal['kind'] == 'compare_functions':
            add('goal', {'kind': 'compare_functions', 'mode': goal['mode'],
                         'select_relation': goal['select_relation'],
                         'selection_mode': goal['selection_mode']}, source_refs=[target_ref])
            produced['goal']['knowledge_refs'] = ['function-concept#identity']
            try:
                description = describe_comparison_goal(report, scope, ancestors, goal_index)
                refs = [target_ref, *(f[side]['source_ref'] for f in description['options']
                                     for side in ('left', 'right'))]
                add('function_comparison', description, source_refs=refs)
            except (NotationError, ValueError, TypeError) as exc:
                add('function_comparison', diagnostic={'code': getattr(exc, 'code', 'comparison.invalid_structure')},
                    source_refs=[target_ref])
            for spec in FEATURE_REGISTRY:
                if spec.feature_id not in produced:
                    add(spec.feature_id, diagnostic={'code': 'feature.not_quantified_comparison_goal'}, source_refs=[target_ref])
            continue
        if goal['kind'] == 'determine_function_parity':
            from ..function_parity import describe_parity_goal
            add('goal', {'kind': 'determine_function_parity'}, source_refs=[target_ref])
            produced['goal']['knowledge_refs'] = ['function-parity#definition']
            try:
                description = describe_parity_goal(report, scope, ancestors, goal_index, candidate=candidate)
                function = description['function']
                refs = [target_ref, function['source_ref'],
                        *([function['input_domain_source_ref']] if function['input_domain_source_ref'] else [])]
                add('function_parity', description, source_refs=refs)
            except (NotationError, ValueError, TypeError) as exc:
                add('function_parity', diagnostic={'code': getattr(exc, 'code', 'function_parity.invalid_structure')},
                    source_refs=[target_ref])
            for spec in FEATURE_REGISTRY:
                if spec.feature_id not in produced:
                    add(spec.feature_id, diagnostic={'code': 'feature.not_parity_goal'}, source_refs=[target_ref])
            continue
        if goal['kind'] == 'find_abstract_range':
            add('goal', {'kind': 'find_abstract_range', 'known_form': None,
                         'strength': goal['strength']}, source_refs=[target_ref])
            produced['goal']['knowledge_refs'] = ['function-concept#elements']
            description = describe_abstract_range_goal(report, scope, ancestors, goal_index)
            produced['goal']['value']['known_form'] = description['known_form']
            refs = [target_ref, *(description[key] for key in (
                'known_call_source_ref', 'known_domain_source_ref', 'known_range_source_ref', 'target_call_source_ref'))]
            if description['has_outer_domain']:
                refs.append(target_ref + '/input_domain')
            add('abstract_function_range', description, source_refs=refs)
            for spec in FEATURE_REGISTRY:
                if spec.feature_id not in produced:
                    add(spec.feature_id, diagnostic={'code': 'feature.not_abstract_range_goal'},
                        source_refs=[target_ref])
            continue
        if goal['kind'] in ('find_abstract_domain', 'find_abstract_domain_parameter'):
            add('goal', {
                'kind': goal['kind'],
                'known_form': None,
                'strength': goal.get('strength'),
            }, source_refs=[target_ref])
            produced['goal']['knowledge_refs'] = [
                'function-concept#elements', 'function-concept#composite-domain',
            ]
            try:
                description = describe_abstract_domain_goal(report, scope, ancestors, goal_index)
                produced['goal']['value']['known_form'] = description['known_form']
                source_refs = [
                    target_ref,
                    description.get('known_call_source_ref', target_ref),
                    description.get('known_domain_source_ref', target_ref),
                    description.get('target_call_source_ref', target_ref),
                ]
                if description.get('known_range_source_ref'):
                    source_refs.append(description['known_range_source_ref'])
                add('abstract_function_domain', description, source_refs=source_refs)
            except (NotationError, ValueError, TypeError) as exc:
                add('abstract_function_domain',
                    diagnostic={'code': getattr(exc, 'code', 'abstract_domain.invalid_structure')},
                    source_refs=[target_ref])
            for spec in FEATURE_REGISTRY:
                if spec.feature_id not in produced:
                    add(spec.feature_id, diagnostic={'code': 'feature.not_abstract_domain_goal'},
                        source_refs=[target_ref])
            continue
        if goal["kind"] == "find_domain":
            add("goal", {"kind": "find_domain", "symbol": objects[goal_ast[1]]["name"]}, source_refs=[target_ref])
            produced["goal"]["knowledge_refs"] = ["function-concept#elements"]
            try:
                description = describe_domain_goal(report, scope, ancestors, goal_index)
                add("function_domain", description, source_refs=[target_ref, description["source_ref"]])
            except (NotationError, ValueError, TypeError) as exc:
                add("function_domain", diagnostic={"code": getattr(exc, "code", "domain.invalid_structure")}, source_refs=[target_ref])
            for spec in FEATURE_REGISTRY:
                if spec.feature_id not in produced:
                    add(spec.feature_id, diagnostic={"code": "feature.not_quantified_domain_goal"}, source_refs=[target_ref])
            continue
        if goal["kind"] == "match_domain":
            parameter = goal.get("parameter")
            if (
                goal_ast[0] != "ref"
                or goal_ast[2] != "function"
                or not parameter
                or parameter[0] != "ref"
                or parameter[2] != "scalar"
            ):
                diagnostic = {"code": "feature.unsupported_goal", "path": target_ref}
                for spec in FEATURE_REGISTRY:
                    add(spec.feature_id, diagnostic=diagnostic, source_refs=[target_ref])
                continue
            add(
                "goal",
                {
                    "kind": "match_domain",
                    "symbol": objects[parameter[1]]["name"],
                    "object": objects[goal_ast[1]]["name"],
                },
                source_refs=[target_ref],
            )
            produced["goal"]["knowledge_refs"] = ["function-concept#elements", "quantifiers#universal"]
            try:
                description = describe_match_domain_goal(report, scope, ancestors, goal_index)
                add(
                    "function_domain",
                    description,
                    source_refs=[target_ref, description["source_ref"]],
                )
                if description.get("structure_supported"):
                    produced["function_domain"]["extractor_version"] = description.get(
                        "structure_version", DOMAIN_PARAMETER_VERSION,
                    )
            except (NotationError, ValueError, TypeError) as exc:
                add(
                    "function_domain",
                    diagnostic={"code": getattr(exc, "code", "domain.invalid_structure")},
                    source_refs=[target_ref],
                )
            for spec in FEATURE_REGISTRY:
                if spec.feature_id not in produced:
                    add(spec.feature_id, diagnostic={"code": "feature.not_match_domain_goal"}, source_refs=[target_ref])
            continue
        if (
            goal["kind"] not in ("find_range", "find_minimum", "find_maximum")
            or goal_ast[0] != "ref"
            or goal_ast[2] != "scalar"
        ):
            diagnostic = {"code": "feature.unsupported_goal", "path": target_ref}
            for spec in FEATURE_REGISTRY:
                add(spec.feature_id, diagnostic=diagnostic, source_refs=[target_ref])
            continue
        goal_name = objects[goal_ast[1]]["name"]
        # A scalar parameter's extremum uses the same structural variables as
        # its range. Preserve the requested kind; finding that extremum (or
        # proving it exists) remains a later solving-stage responsibility.
        add(
            "goal",
            {"kind": goal["kind"], "symbol": goal_name},
            source_refs=[target_ref],
        )
        if len(quantifiers) != 1:
            diagnostic = {
                "code": "feature.single_quantifier_required",
                "count": len(quantifiers),
            }
            for spec in FEATURE_REGISTRY:
                if spec.feature_id not in produced:
                    add(spec.feature_id, diagnostic=diagnostic)
            continue
        quantified, record = quantifiers[0]
        source_ref = _json_path(record["path"])
        raw_quantifiers = conjunct_quantifiers(parse(record["source"]))
        domain_used, domain_arguments, body_used, body_arguments = set(), [], set(), []
        try:
            if len(raw_quantifiers) != 1:
                raise NotationError("feature.single_quantifier_required")
            bound_name = raw_quantifiers[0][2]
            quantified = [
                *quantified[:3],
                _inline(quantified[3], functions, domain_used, domain_arguments),
                _inline(quantified[4], functions, body_used, body_arguments),
            ]
            # An argument the body ignores (f(t)=1, f(1/a)) still names a variable.
            scalars = {
                item[1]
                for tree in (quantified, *domain_arguments, *body_arguments)
                for item in _refs(tree, "ref")
                if item[2] == "scalar"
            } | {goal_ast[1]}
            # Symbols are created from display names; distinct bindings that
            # share a name (an outer x and a bound x) cannot be told apart.
            names = [objects[ref]["name"] for ref in scalars]
            if len(set(names)) != len(names) or bound_name in names:
                raise NotationError("feature.ambiguous_variable_name")
            algebra = _Algebra(report.objects, {quantified[2]: bound_name})
        except (NotationError, RecursionError) as exc:
            diagnostic = {
                "code": getattr(exc, "code", "feature.function_inline_failed"),
                "path": source_ref,
            }
            for spec in FEATURE_REGISTRY:
                if spec.feature_id not in produced:
                    add(
                        spec.feature_id, diagnostic=diagnostic, source_refs=[source_ref]
                    )
            continue
        def inlined_from(used):
            names = sorted(objects[ref]["name"] for ref in used)
            calculation = (
                {"operation": "read_bound_ast", "inlined_functions": names}
                if names
                else None
            )
            return [function_sources[ref] for ref in sorted(used)], calculation

        domain_functions, domain_calculation = inlined_from(domain_used)
        body_functions, body_calculation = inlined_from(body_used)
        common_sources = [source_ref, target_ref]
        derived_sources = [*common_sources, *body_functions]
        add("quantifier", quantified[1], source_refs=[source_ref])
        add("bound_vars", [bound_name], source_refs=[source_ref])
        add(
            "free_vars",
            sorted(set(names)),
            source_refs=[*common_sources, *domain_functions, *body_functions],
        )
        try:
            for argument in domain_arguments:
                algebra.expr(argument)
            domain, kind = _domain(quantified[3], algebra)
            for feature_id, value in (("domain", domain), ("domain_kind", kind)):
                add(
                    feature_id,
                    value,
                    source_refs=[source_ref, *domain_functions],
                    conditions=algebra.conditions,
                    calculation=domain_calculation,
                )
            inherited.update(
                conditions=len(algebra.conditions),
                source_refs=[source_ref, *domain_functions],
                dependencies=["domain"],
            )
        except (NotationError, ValueError, TypeError, ZeroDivisionError) as exc:
            diagnostic = {
                "code": getattr(exc, "code", "feature.domain_failed"),
                "message": str(exc),
            }
            for name in ("domain", "domain_kind"):
                add(name, diagnostic=diagnostic, source_refs=[source_ref, *domain_functions])
            if not diagnostic["code"].startswith(_REPRESENTATION_ONLY):
                # A domain whose endpoints cannot be evaluated as real numbers
                # (undefined, non-real or beyond limits) leaves the statement unusable.
                for spec in FEATURE_REGISTRY:
                    if spec.feature_id not in produced:
                        add(spec.feature_id, diagnostic=diagnostic, source_refs=derived_sources)
                continue
        try:
            for argument in body_arguments:
                algebra.expr(argument)
            body = quantified[4]
            if body[0] not in ("<", "<=", ">", ">=", "=", "!="):
                raise NotationError("feature.single_scalar_relation_required")
            if not _refs(body, "bound"):
                raise NotationError(
                    "feature.bound_variable_absent",
                    "Expand dependent-value definitions inside the quantified relation.",
                )
            lhs, rhs = algebra.expr(body[1]), algebra.expr(body[2])
            add(
                "relation",
                {
                    "operator": body[0],
                    "strict": body[0] in ("<", ">", "!="),
                    "lhs": _math(lhs),
                    "rhs": _math(rhs),
                },
                source_refs=[source_ref, *body_functions],
                conditions=algebra.conditions,
                calculation=body_calculation,
            )
            operator = {"<": ">", "<=": ">="}.get(body[0], body[0])
            expression = bounded_expand(
                rhs - lhs if body[0] in ("<", "<=") else lhs - rhs
            )
            normal = {
                "expression": _math(expression),
                "operator": operator,
                "rhs": "0",
                "variable": bound_name,
            }
            add(
                "normal_form",
                normal,
                source_refs=[source_ref, *body_functions],
                conditions=algebra.conditions,
                calculation={
                    "operation": "move_terms_and_expand",
                    "input_operator": body[0],
                    "flipped_sides": body[0] in ("<", "<="),
                },
            )
            polynomials = {}
            for feature_id, variable in (
                ("degree_in_bound", bound_name),
                ("degree_in_goal", goal_name),
            ):
                try:
                    polynomial, degree = _polynomial(expression, variable)
                    polynomials[feature_id] = (polynomial, degree)
                    add(
                        feature_id,
                        degree,
                        source_refs=derived_sources,
                        conditions=algebra.conditions,
                        calculation={
                            "operation": "collect_polynomial",
                            "variable": variable,
                            "expression": _math(expression),
                        },
                    )
                except sp.PolynomialError as exc:
                    add(
                        feature_id,
                        diagnostic={
                            "code": "feature.not_polynomial",
                            "variable": variable,
                            "message": str(exc),
                        },
                        source_refs=derived_sources,
                    )
            if "degree_in_bound" in polynomials:
                polynomial, degree = polynomials["degree_in_bound"]
                leading = polynomial.LC()
                add(
                    "leading_coeff_in_bound",
                    {
                        "variable": bound_name,
                        "expression": _math(leading),
                        "contains_parameters": bool(leading.free_symbols),
                        "may_be_zero": leading == 0 or bool(leading.free_symbols),
                    },
                    source_refs=derived_sources,
                    conditions=algebra.conditions,
                    calculation={
                        "operation": "leading_coefficient",
                        "expression": _math(expression),
                    },
                )
                items = [
                    {
                        "power": int(power[0]),
                        "expression": _math(coefficient),
                        "contains_parameters": bool(coefficient.free_symbols),
                    }
                    for power, coefficient in polynomial.terms()
                ]
                add(
                    "coefficients",
                    {
                        "variable": bound_name,
                        "expression": _math(expression),
                        "items": items,
                    },
                    source_refs=derived_sources,
                    conditions=algebra.conditions,
                    calculation={"operation": "collect_coefficients"},
                )
            bound_degree = polynomials.get("degree_in_bound", (None, {}))[1].get(
                "degree"
            )
            goal_degree = polynomials.get("degree_in_goal", (None, {}))[1].get("degree")
            if bound_degree == 2:
                add(
                    "range_var_is_principal",
                    True,
                    source_refs=derived_sources,
                    conditions=algebra.conditions,
                )
            elif bound_degree in (0, 1) and goal_degree == 2:
                add(
                    "range_var_is_principal",
                    False,
                    source_refs=derived_sources,
                    conditions=algebra.conditions,
                )
        except (
            NotationError,
            ValueError,
            TypeError,
            RecursionError,
            sp.PolynomialError,
        ) as exc:
            diagnostic = {
                "code": getattr(exc, "code", "feature.algebra_failed"),
                "message": str(exc),
                "path": source_ref,
            }
            for spec in FEATURE_REGISTRY:
                if spec.feature_id not in produced:
                    add(
                        spec.feature_id,
                        diagnostic=diagnostic,
                        source_refs=derived_sources,
                    )
        for spec in FEATURE_REGISTRY:
            if spec.feature_id not in produced:
                add(
                    spec.feature_id,
                    diagnostic={"code": "feature.unsupported_structure"},
                    source_refs=derived_sources,
                )
