"""Small, verified algebra chains for two-term rational identities.

This is a presentation projection, not an additional solver. The caller retains
the original domain and invokes it only for an already verified identity.
"""

import sympy as sp

from ..function_evaluation import MAX_DEGREE, _body_value, _check_source, _substitution_latex
from ..stage_one.function_domain import expression_latex
from ...problem_understanding.notation_parser import NotationError
from .math_values import latex


def _fraction(numerator, denominator):
    return rf'\frac{{{numerator}}}{{{denominator}}}'


def _term(numerator, denominator):
    if denominator != 1:
        return _fraction(latex(numerator), latex(denominator))
    rendered = latex(numerator)
    return rf'\left({rendered}\right)' if numerator.is_Add or numerator.could_extract_minus_sign() else rendered


def _rational_sum_steps(description, calls, value):
    ast = description['expression_ast']
    if len(ast) != 3 or ast[0] not in ('+', '-'):
        return None
    if any(child[0] != 'function_call' for child in ast[1:]):
        return None
    # Nested calls need their own dependency steps rather than a fraction chain.
    if len(calls) != 2 or {call['call_id'] for call in calls} != {'target/1', 'target/2'}:
        return None
    variable_ref = description.get('variable_ref')
    if not variable_ref:
        return None
    variable = sp.Symbol(description['variable'], real=True)
    symbols = {variable_ref: variable}
    functions = {item['function_ref']: item for item in description['functions']}
    expected, domain = _check_source(ast, functions, symbols, variable)
    if domain == sp.S.EmptySet or value is None or sp.cancel(expected - value) != 0:
        return None
    value = sp.sympify(value)
    if not value.is_Rational:
        return None

    by_path = {call['call_id']: call for call in calls}
    original, substituted, raw_terms, fractions = [], [], [], []
    names = {variable_ref: description['variable']}
    for index, child in enumerate(ast[1:], 1):
        call = by_path[f'target/{index}']
        function = functions[child[1][1]]
        if not call.get('defined') or call['function_ref'] != child[1][1]:
            return None
        argument, _ = _check_source(child[2], functions, symbols, variable)
        if sp.cancel(argument - call['input']) != 0:
            return None
        raw = _body_value(function['expression_ast'], argument, raw=True)
        if sp.cancel(raw - call['substitution']) != 0:
            return None
        num, den = sp.fraction(sp.cancel(raw))
        for polynomial in (num, den):
            poly = sp.Poly(polynomial, variable, domain=sp.QQ)
            if poly.degree() > MAX_DEGREE:
                return None
        name = function.get('function_name') or child[1][1].rsplit(':', 1)[-1]
        original.append(name + r'\left(' + expression_latex(child[2], description['variable'], names=names) + r'\right)')
        substituted.append(r'\left(' + _substitution_latex(function['expression_ast'], argument) + r'\right)')
        raw_terms.append(raw)
        fractions.append((num, den))

    if all(den == 1 for _, den in fractions):
        return None
    op, sign = ast[0], 1 if ast[0] == '+' else -1
    raw_sum = raw_terms[0] + sign * raw_terms[1]
    steps = [(op.join(original), expected), (op.join(substituted), raw_sum)]
    normalized = op.join(_term(num, den) for num, den in fractions)
    normalized_value = fractions[0][0] / fractions[0][1] + sign * fractions[1][0] / fractions[1][1]
    steps.append((normalized, normalized_value))

    (num1, den1), (num2, den2) = fractions
    common = sp.lcm(den1, den2)
    factors = [sp.cancel(common / den) for _, den in fractions]
    numerators = [sp.expand(num * factor) for (num, _), factor in zip(fractions, factors, strict=True)]
    if den1 != den2:
        # Show both fractions over the same denominator before adding numerators.
        aligned = op.join(_term(num, common) for num in numerators)
        steps.append((aligned, numerators[0] / common + sign * numerators[1] / common))
    combined = r'\left(' + latex(numerators[0]) + r'\right)' + op + r'\left(' + latex(numerators[1]) + r'\right)'
    steps.append((_fraction(combined, latex(common)), (numerators[0] + sign * numerators[1]) / common))
    expanded = sp.expand(numerators[0] + sign * numerators[1])
    steps.append((_fraction(latex(expanded), latex(common)), expanded / common))
    steps.append((latex(value), value))

    # Mathematical equality is checked before any row becomes student-visible.
    if any(sp.cancel(expression - expected) != 0 for _, expression in steps):
        return None
    return steps


def rational_sum_derivation(description, calls, value):
    """Return a LaTeX chain for a simple rational sum/difference, else ``None``.

    No domain is inferred from a simplified fraction: the outer card must keep
    its existing original-domain statement. Finite-domain checks and witnesses
    should use their own presentation instead of calling this helper.
    """
    try:
        steps = _rational_sum_steps(description, calls, value)
    except (KeyError, TypeError, ValueError, IndexError, ZeroDivisionError,
            NotationError, sp.PolynomialError):
        return None
    if not steps:
        return None
    rows = []
    for rendered, _ in steps:
        if not rows or rendered != rows[-1]:
            rows.append(rendered)
    return r'\begin{gathered}' + r'\\'.join([rows[0], *('=' + row for row in rows[1:])]) + r'\end{gathered}'
