"""Registered mathematical checks and input resolvers for method admission.

Configuration selects existing operations; it never evaluates Python or SymPy
source. These functions are called only from the supervised calculation worker.
New methods can compose the same resolvers/checks without editing the driver.
"""

from copy import deepcopy
from inspect import signature

import sympy as sp

from . import capabilities, judgments
from .capabilities import CapabilityGap
from .premises import FeatureMath, UnknownPremise, parse_expression


class Inputs:
    def __init__(self, features, context):
        indexed = features if isinstance(features, dict) else {
            row["feature_id"]: row for row in features if row["target_ref"] == context["target_ref"]
        }
        self.math = FeatureMath(indexed)
        self.context = context
        self.cache = {}

    def resolve(self, name):
        if name not in self.cache:
            self.cache[name] = RESOLVERS[name](self)
        value = self.cache[name]
        # SymPy values are immutable. deepcopy reconstructs an unevaluated
        # relation and may simplify x**2 + 1 >= 0 to BooleanTrue, losing the
        # original lhs/operator/rhs needed by the execution contract.
        return value if isinstance(value, sp.Basic) else deepcopy(value)


def _relation(source):
    value = source.math.value("relation")
    return capabilities.relation(parse_expression(value["lhs"]), value["operator"], parse_expression(value["rhs"]))


def _interval_function(source):
    relation = source.resolve("relation")
    return relation.lhs - relation.rhs


RESOLVERS = {
    "relation": _relation,
    "expression": lambda source: source.math.expression,
    "bound_variable": lambda source: source.math.x,
    "parameter": lambda source: source.math.parameter,
    "domain": lambda source: source.math.domain,
    "quantifier": lambda source: source.math.value("quantifier"),
    "strict": lambda source: source.math.value("relation")["strict"],
    "goal": lambda source: source.context["goal"],
    "constraint_context": lambda source: source.context,
    "abstract_range_mode": lambda source: source.context['goal']['kind'] == 'find_abstract_range',
    "abstract_domain_parameter_mode": lambda source: source.context["goal"]["kind"] == "find_abstract_domain_parameter",
    "interval_function": _interval_function,
    "interval_operator": lambda source: {"<": ">", "<=": ">=", ">": "<", ">=": "<="}[
        source.math.value("relation")["operator"]
    ],
    "zero": lambda source: sp.S.Zero,
}


def _quantifier(quantifier):
    return quantifier in ("∀", "∃")


def _polynomial_degree(expression, variable, degree):
    return capabilities.polynomial(expression, variable).degree() == degree


def _quantified_reals(quantifier, domain):
    return quantifier in ("∀", "∃") and domain == sp.S.Reals


def _rational_parameter_coefficients(expression, variable, parameter):
    polynomial = capabilities.polynomial(expression, variable)
    for coefficient in polynomial.all_coeffs():
        parameter_poly = capabilities.polynomial(coefficient, parameter, maximum=48)
        if parameter_poly.degree() > 48 or any(not item.is_Rational for item in parameter_poly.all_coeffs()):
            return False
    return True


def _separable_range(relation, parameter, variable, domain):
    separated = capabilities.inspect_separation(relation, parameter, variable, domain)["outputs"]
    capabilities.polynomial(separated["parameter_expression"], parameter)
    judgments.range_skill(separated["function"], variable, domain, reserved_symbols=(parameter,))
    return True


def _interval_cases(expression, variable, parameter, domain, quantifier, operator):
    policy = capabilities.select_quantifier_policy(quantifier, operator, domain)["outputs"]["policy"]
    judgments.interval_case_plan(expression, variable, parameter, domain, policy)
    return True


def _linear_parameter_range(expression, variable, parameter, domain, quantifier, operator):
    from .capabilities.variable_swap import validate_variable_swap

    policy = capabilities.select_quantifier_policy(quantifier, operator, domain)["outputs"]["policy"]
    validate_variable_swap(expression, variable, parameter, domain, policy)
    return True


def _function_domain(context):
    from .function_domain import admitted
    return admitted(context)


def _function_domain_parameter(context):
    from .function_domain import admitted_parameter
    return admitted_parameter(context)


def _function_equality(context):
    from .equality_runtime import admitted
    return admitted(context)


def _abstract_function_domain(context):
    from .abstract_function_domain import admitted
    if context["goal"]["kind"] == "find_abstract_domain_parameter":
        from .abstract_domain_parameter import admitted as admitted_parameter
        return admitted_parameter(context)
    return admitted(context)


def _function_evaluation(context):
    from .evaluation_runtime import admitted
    return admitted(context)


def _function_range(context, method=None):
    from .function_range import admitted
    return admitted(context, method)


CHECKS = {
    'function_range': _function_range,
    "function_evaluation": _function_evaluation,
    "function_equality": _function_equality,
    "abstract_function_domain": _abstract_function_domain,
    "function_domain": _function_domain,
    "function_domain_parameter": _function_domain_parameter,
    "quantifier": _quantifier,
    "polynomial_degree": _polynomial_degree,
    "quantified_reals": _quantified_reals,
    "rational_parameter_coefficients": _rational_parameter_coefficients,
    "separable_range": _separable_range,
    "interval_cases": _interval_cases,
    "linear_parameter_range": _linear_parameter_range,
}


def _references(value):
    if isinstance(value, str) and value.startswith("$"):
        yield value[1:]
    elif isinstance(value, dict):
        for item in value.values():
            yield from _references(item)
    elif isinstance(value, list):
        for item in value:
            yield from _references(item)


def validate_admission(contract):
    admission = contract.get("admission")
    if admission is None:
        raise ValueError("execution.missing_admission:" + contract["method"])
    if set(admission["bindings"]) != set(contract["inputs"]):
        raise ValueError("execution.admission_bindings:" + contract["method"])
    for specification in admission["bindings"].values():
        if "resolver" in specification and specification["resolver"] not in RESOLVERS:
            raise ValueError("execution.unknown_binding_resolver:" + specification["resolver"])
    for check in admission["checks"]:
        if check["function"] not in CHECKS:
            raise ValueError("execution.unknown_admission_check:" + check["function"])
        if not set(_references(check["inputs"])) <= set(admission["bindings"]):
            raise ValueError("execution.admission_dependency")
        try:
            signature(CHECKS[check["function"]]).bind(**check["inputs"])
        except TypeError as exc:
            raise ValueError("execution.admission_check_inputs:" + check["function"]) from exc
    return admission


def initial_bindings(contract, features, context):
    admission = validate_admission(contract)
    source = Inputs(features, context)
    return {
        name: source.resolve(specification["resolver"]) if "resolver" in specification
        else deepcopy(specification["constant"])
        for name, specification in admission["bindings"].items()
    }


def _resolve(value, bindings):
    if isinstance(value, str) and value.startswith("$"):
        return bindings[value[1:]]
    if isinstance(value, dict):
        return {key: _resolve(item, bindings) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve(item, bindings) for item in value]
    return value


def can_execute(contract, bindings):
    admission = validate_admission(contract)
    try:
        for check in admission["checks"]:
            result = CHECKS[check["function"]](**_resolve(check["inputs"], bindings))
            if result is False:
                return False
            if result is not True:
                raise ValueError("execution.invalid_admission_result:" + check["function"])
    except (CapabilityGap, UnknownPremise):
        return False
    return True
