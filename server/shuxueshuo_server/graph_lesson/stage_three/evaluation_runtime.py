"""M9 execution and typed completion shared by topic and photo learning."""

from copy import deepcopy

import sympy as sp

from .. import function_evaluation as math_kernel
from ..function_evaluation import evaluate, structural_inspect, verify
from .capabilities import CapabilityGap, LocalCheckFailed, result as capability_result
from .math_values import math_value
from .trajectory import decode_value, encode_value

GOAL_KINDS = frozenset({'find_value', 'check_constant', 'finite_sum'})
SUM_CERTIFICATE = 'finite-sum-occurrences/v1'


def _compact_sum(evaluated):
    """Persist each occurrence once; source ASTs are bound by their signature.

    Per-call substitution trees belong to the source recipe, not to every copy
    of an execution value. Retain all occurrence values and the complete pair
    partition, plus the few unpaired source terms used by the teaching cards.
    """
    if evaluated['kind'] != 'finite_sum' or evaluated.get('certificate_encoding') == SUM_CERTIFICATE:
        return evaluated
    compact = {key: value for key, value in evaluated.items() if key not in ('calls', 'constraints', 'terms')}
    compact['certificate_encoding'] = SUM_CERTIFICATE
    compact['occurrence_certificate'] = [[term[key] for key in (
        'occurrence_id', 'index', 'defined', 'value', 'input', 'function_ref')] for term in evaluated['terms']]
    leftovers = set(evaluated['leftovers'])
    compact['terms'] = [{key: value for key, value in term.items() if key != 'calls'}
                        for term in evaluated['terms'] if term['occurrence_id'] in leftovers]
    return compact


def _verify_evaluation(description, evaluated):
    if evaluated.get('certificate_encoding') != SUM_CERTIFICATE:
        return verify(description, evaluated)
    try:
        # Reconstruct omitted source metadata, then independently verify every
        # submitted value and the complete occurrence/pair partition. The
        # receipt never substitutes an expected result for a submitted value.
        complete = evaluate(description)
        certificate = evaluated['occurrence_certificate']
        if complete['kind'] != 'finite_sum' or len(certificate) != len(complete['terms']):
            return False
        for term, row in zip(complete['terms'], certificate, strict=True):
            if len(row) != 6:
                return False
            for key, value in zip(('occurrence_id', 'index', 'defined', 'value', 'input', 'function_ref'), row, strict=True):
                term[key] = value
        for key, value in evaluated.items():
            if key not in ('terms', 'certificate_encoding', 'occurrence_certificate'):
                complete[key] = value
        return _compact_sum(complete) == evaluated and verify(description, complete)
    except (KeyError, TypeError, ValueError, IndexError):
        return False


def admitted(context):
    description = context.get('evaluation_goal') or {}
    return (context.get('goal', {}).get('kind') in GOAL_KINDS
            and description.get('structure_supported') is True
            and structural_inspect(description).get('structure_supported') is True)


def solve_function_evaluation(context):
    if not admitted(context):
        raise CapabilityGap('function_evaluation.input_class_unavailable')
    description = deepcopy(context['evaluation_goal'])
    evaluated = evaluate(description)
    if not verify(description, evaluated):
        raise LocalCheckFailed('function_evaluation.local_verification_failed')
    from .evaluation_presentation import phase_flags

    return {'outputs': {'description': description, 'evaluation_result': _compact_sum(evaluated),
                        **phase_flags(description, evaluated)},
            'operations': ['function_evaluation'],
            'checks': [{'kind': 'function_evaluation', 'passed': True}]}


def _substitute_source(ast, functions, symbols, constraints, expressions, operations,
                       *, path='target', source_ref='', argument=None):
    """Bind the original AST and collect restrictions, without solving them.

    Keep a raw expression for the algebra capability and an arithmetic value
    for conditions. A constant function body must still visit its input first.
    """
    if ast == math_kernel.ARGUMENT:
        return argument
    kind = ast[0]
    if kind == 'number':
        value = sp.Rational(ast[1])
        return value, value
    if kind == 'ref':
        return symbols[ast[1]], symbols[ast[1]]
    if kind == 'function_call':
        function = functions[ast[1][1]]
        value = _substitute_source(ast[2], functions, symbols, constraints, expressions, operations,
                                   path=path + '/input', source_ref=source_ref)
        allowed = math_kernel._set(function.get('input_domain_ast', ['real']))
        if allowed != sp.S.Reals:
            constraints.append({'kind': 'membership', 'expression': value[1], 'allowed': allowed,
                                'path': path + '/declared-domain',
                                'source_ref': function.get('input_domain_source_ref') or function['source_ref']})
            operations.add('function_evaluation_input_domain')
        output = _substitute_source(function['expression_ast'], functions, symbols, constraints,
                                    expressions, operations, path=path + '/body',
                                    source_ref=function['source_ref'], argument=value)
        expressions[path] = output[0]
        return output
    values = [_substitute_source(child, functions, symbols, constraints, expressions, operations,
                                 path=path + '/' + str(index), source_ref=source_ref, argument=argument)
              for index, child in enumerate(ast[1:], 1)]
    if kind == '/' or (kind == '^' and values[1][1] == 0):
        constraints.append({'kind': 'nonzero', 'expression': values[1][1] if kind == '/' else values[0][1],
                            'path': path + ('/2' if kind == '/' else '/1'), 'source_ref': source_ref})
        operations.add('domain_denominator_conditions' if kind == '/' else 'domain_zero_power_conditions')
    raw = math_kernel._apply(kind, *(value[0] for value in values), raw=True)
    normalized = sp.cancel(math_kernel._apply(kind, *(value[1] for value in values)))
    return raw, normalized


def extract_evaluation_conditions(description, evaluation_result):
    functions = math_kernel._prepare(description)
    variable = evaluation_result['variable']
    constraints, expressions, operations, terms = [], {}, set(), []
    if description['kind'] == 'finite_sum':
        sources = list(math_kernel._occurrences(description))
    else:
        sources = [{'occurrence_id': 'target', 'expression_ast': description['expression_ast'],
                    'symbols': {description['variable_ref']: variable} if description.get('variable_ref') else {},
                    'source_ref': description.get('target_ref', '')}]
    for source in sources:
        raw, _ = _substitute_source(source['expression_ast'], functions, source['symbols'],
                                    constraints, expressions, operations, path=source['occurrence_id'],
                                    source_ref=source['source_ref'])
        terms.append({'occurrence_id': source['occurrence_id'], 'expression': raw})
    compact_sum = evaluation_result.get('certificate_encoding') == SUM_CERTIFICATE
    if compact_sum and evaluation_result.get('source_signature') != math_kernel._signature(description):
        raise LocalCheckFailed('function_evaluation.source_signature_mismatch')
    if not compact_sum and not math_kernel._same_records(constraints, evaluation_result['constraints']):
        raise LocalCheckFailed('function_evaluation.original_conditions_mismatch')
    # An undefined input has no algebra value. Keep its source restrictions,
    # but do not checkpoint an unevaluated 1/0 that a later codec may collapse.
    for call in evaluation_result.get('calls', []):
        if not call['defined']:
            expressions[call['call_id']] = None
    if compact_sum:
        # The substitution capability consumes this exact bound source recipe;
        # avoid persisting 201 expanded copies of the same function definition.
        expressions = {'source_recipe': deepcopy(description), 'source_signature': evaluation_result['source_signature']}
        terms = []
    elif description['kind'] == 'finite_sum':
        for term, evaluated in zip(terms, evaluation_result['terms'], strict=True):
            if not evaluated['defined']:
                term['expression'] = None
    elif not evaluation_result['defined']:
        terms[0]['expression'] = None
    quadratic = []
    for row in constraints:
        if row['kind'] != 'nonzero':
            continue
        numerator = sp.fraction(sp.cancel(row['expression']))[0]
        if sp.Poly(numerator, variable).degree() == 2:
            quadratic.append({'expression': numerator, 'path': row['path'], 'source_ref': row['source_ref']})
    return capability_result({'conditions': constraints, 'substitutions': expressions, 'raw_terms': terms,
                              'quadratic_conditions': quadratic, 'has_quadratic_conditions': bool(quadratic)},
                             sorted(operations) or ['domain_unrestricted_expression'],
                             [{'kind': 'source_condition_extraction', 'passed': True, 'count': len(constraints)}])


def resolve_evaluation_domain(description, conditions, evaluation_result):
    """M9 consumes the extracted restrictions before any cancellation."""
    checked = deepcopy(evaluation_result)
    domain = math_kernel._guard_domain(conditions, checked['variable'])
    if description['kind'] != 'finite_sum':
        domain &= math_kernel._set(description.get('input_domain_ast', ['real']))
    if domain != checked['domain']:
        raise LocalCheckFailed('function_evaluation.condition_domain_mismatch')
    checked['domain'] = domain
    if checked.get('certificate_encoding') != SUM_CERTIFICATE:
        checked['constraints'] = deepcopy(conditions)
    return capability_result({'evaluation_result': checked},
                             ['domain_intersection'] if conditions else [],
                             [{'kind': 'original_condition_domain', 'passed': True}])


def check_evaluation_quadratic_conditions(quadratic_conditions, evaluation_result):
    from .capabilities import solve_quadratic

    if not quadratic_conditions:
        raise CapabilityGap('function_evaluation.quadratic_condition_required')
    checks, roots = [], []
    for row in quadratic_conditions:
        solved = solve_quadratic(row['expression'], evaluation_result['variable'])
        # The complete root certificate is consumed to check every forbidden
        # input, including irrational roots and roots hidden by cancellation.
        points = solved['outputs']['roots']
        if any(evaluation_result['domain'].contains(point) is not sp.S.false for point in points):
            raise LocalCheckFailed('function_evaluation.forbidden_root_retained')
        roots.append({**row, 'roots': points})
        checks.extend(solved['checks'])
    return capability_result({'root_checks': roots}, ['quadratic_roots'], checks)


def simplify_evaluation_expressions(substitutions, raw_terms, evaluation_result):
    from .capabilities import simplify_expression

    checked = deepcopy(evaluation_result)
    checks, operations = [], set()

    def simplify(raw):
        # Checkpoint decoding deliberately preserves Pow(..., evaluate=False).
        # Evaluate that arithmetic structure before the shared expand-based
        # identity checker (e.g. Pow(3, -1) otherwise stays structurally unequal
        # to Rational(1, 3)). The source expression is still checked below.
        expanded = simplify_expression(raw.doit())
        # Reuse the existing exact algebra capability, then normalize rational
        # expressions only after the separately retained original restrictions.
        value = sp.cancel(expanded['outputs']['expression'])
        if value.has(sp.zoo, sp.nan, sp.oo, -sp.oo) or sp.cancel(value - raw) != 0:
            raise LocalCheckFailed('function_evaluation.simplification_mismatch')
        checks.extend(expanded['checks'])
        operations.update(expanded['operations'])
        if sp.denom(raw) != 1:
            operations.add('bounded_rational_normal_form')
        return value

    for call in checked.get('calls', []):
        if call['defined']:
            call['output'] = simplify(substitutions[call['call_id']])
    if checked.get('certificate_encoding') == SUM_CERTIFICATE:
        description = substitutions['source_recipe']
        if (substitutions['source_signature'] != checked['source_signature']
                or math_kernel._signature(description) != checked['source_signature']):
            raise LocalCheckFailed('function_evaluation.source_signature_mismatch')
        functions = math_kernel._prepare(description)
        sources = list(math_kernel._occurrences(description))
        values = {}
        for source, row in zip(sources, checked['occurrence_certificate'], strict=True):
            if row[0] != source['occurrence_id'] or row[1] != source['index']:
                raise LocalCheckFailed('function_evaluation.occurrence_mismatch')
            if row[2]:
                raw, _ = _substitute_source(source['expression_ast'], functions, source['symbols'], [], {}, set(),
                                            path=source['occurrence_id'], source_ref=source['source_ref'])
                row[3] = simplify(raw)
            values[row[0]] = row[3]
        for term in checked['terms']:
            term['value'] = values[term['occurrence_id']]
        if checked['defined']:
            total = sum(values.values(), sp.S.Zero)
            checked.update(value=total, total=total, expression=total)
        checks = [{'kind': 'source_occurrence_algebra', 'passed': True, 'count': len(checks)}]
    elif checked['kind'] == 'finite_sum':
        for term, raw in zip(checked['terms'], raw_terms, strict=True):
            if term['occurrence_id'] != raw['occurrence_id']:
                raise LocalCheckFailed('function_evaluation.occurrence_mismatch')
            if term['defined']:
                term['value'] = simplify(raw['expression'])
        if checked['defined']:
            total = sum((term['value'] for term in checked['terms']), sp.S.Zero)
            checked.update(value=total, total=total, expression=total)
    elif checked['defined']:
        value = simplify(raw_terms[0]['expression'])
        checked['expression'] = value
        if checked['kind'] == 'scalar_value':
            checked['value'] = value
        elif checked['kind'] == 'constant_check' and checked['is_constant'] is True:
            if isinstance(checked['domain'], sp.FiniteSet):
                checked['value'] = sp.cancel(value.subs(checked['variable'], next(iter(checked['domain']))))
            else:
                checked['value'] = value
    return capability_result({'evaluation_result': checked}, sorted(operations),
                             checks or [{'kind': 'undefined_input_has_no_value_claim', 'passed': not checked['defined']}])


def verify_evaluation_identities(description, evaluation_result):
    # This source-based identity/domain check consumes the algebra capability's
    # outputs; the lesson cannot finish with an unverified replacement result.
    if not _verify_evaluation(description, evaluation_result):
        raise LocalCheckFailed('function_evaluation.substituted_identity_failed')
    return capability_result({'evaluation_result': evaluation_result}, ['identity'],
                             [{'kind': 'substitution_identity_on_original_domain', 'passed': True}])


def verify_frozen(candidate, target_ref, context, encoded_result):
    from .context import build_context

    current = build_context(candidate, target_ref)
    if current != context:
        raise LocalCheckFailed('function_evaluation.original_context_mismatch')
    result = decode_value(encoded_result)
    valid = admitted(current) and _verify_evaluation(current['evaluation_goal'], result)
    return {'status': 'verified' if valid else 'math_failed',
            'diagnostics': [] if valid else [{'code': 'function_evaluation.independent_verification_failed'}]}


def answer_for(description, result):
    def present(key):
        value = result.get(key)
        return None if value is None else math_value(value)

    return {'kind': description['kind'], 'status': 'complete',
            'result_type': result['kind'], 'defined': result.get('defined', True),
            'domain': present('domain'), 'value': present('value'),
            'expression': present('expression'), 'is_constant': result.get('is_constant')}


def finish(state, context, previous):
    result = decode_value(state['evaluation_result_exact'])
    answer = answer_for(context['evaluation_goal'], result)
    consistency = 'consistent'
    for route in previous:
        if route['status'] == 'verified' and route.get('answer') != answer:
            consistency = 'conflict'
    return {'state': deepcopy(state), 'answer': answer,
            'evaluation_result_exact': encode_value(result), 'consistency': consistency}
