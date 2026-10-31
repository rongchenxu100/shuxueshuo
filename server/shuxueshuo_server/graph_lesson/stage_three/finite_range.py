"""M14: a bounded input partition, real M9 calls, and an exact output set."""

from copy import deepcopy
from hashlib import sha256

import sympy as sp

from .. import function_evaluation as evaluation
from ..range_syntax import MAX_FINITE_INPUTS
from .capabilities import CapabilityGap, LocalCheckFailed, result


def finite_task(description, domain):
    # Preserve the existing single-point interval route. An explicit finite
    # set, including a singleton, uses enumeration; child range methods keep
    # their existing interval/endpoint contract.
    domains = [description['declared_domain_ast'], description['input_domain_ast'],
               *(row['domain_ast'] for row in description['restriction_facts'])]
    def contains_set(ast):
        return ast[0] == 'set' or (ast[0] in ('∩', '∪') and any(contains_set(v) for v in ast[1:]))
    return isinstance(domain, sp.FiniteSet) and (len(domain) > 1 or any(map(contains_set, domains)))


def input_rows(context):
    from .function_range import domain_ast, inputs

    desc = context['range_goal']
    _, _, domain = inputs(desc)
    if not isinstance(domain, sp.FiniteSet) or not 1 <= len(domain) <= MAX_FINITE_INPUTS:
        raise CapabilityGap('range.finite_input_budget')
    rows = []
    for point in sorted(domain):
        if point.is_Rational is not True:
            raise CapabilityGap('range.finite_rational_input_required')
        row_id = 'input-' + sha256(str(point).encode()).hexdigest()[:12]
        target = desc['target_ref'] + '/enumeration/' + row_id
        function = {key: deepcopy(desc[key]) for key in (
            'function_ref', 'function_name', 'variable', 'source_ref', 'expression_ast')}
        function.update(input_domain_ast=domain_ast(domain), explicit_domain=True,
                        input_domain_source_ref=desc['input_domain_source_ref'] or desc['source_ref'])
        goal = {'kind': 'find_value', 'target_ref': target, 'source_ref': desc['source_ref'],
                'expression_ast': ['function_call', ['ref', desc['function_ref'], 'function'],
                                   ['number', str(point)]],
                'functions': [function], 'terms': [], 'variable_ref': '', 'variable': '',
                'input_domain_ast': ['real']}
        goal.update(evaluation.structural_inspect(goal))
        if not goal['structure_supported']:
            raise CapabilityGap(goal['reason'])
        rows.append({'id': row_id, 'input': point, 'condition': sp.Eq(sp.Symbol(desc['variable'], real=True), point),
                     'domain': sp.FiniteSet(point), 'evaluation_goal': goal})
    return rows


def prepare_finite_range(context):
    from .function_range import inputs

    rows = input_rows(context)
    function, variable, domain = inputs(context['range_goal'])
    return result({'description': deepcopy(context['range_goal']), 'function': function,
                   'variable': variable, 'domain': domain, 'input_rows': rows},
                  ['finite_range_partition'],
                  [{'kind': 'complete_finite_input_partition', 'passed': True, 'domain': domain,
                    'row_ids': [row['id'] for row in rows]}])


def prepare_finite_input(row):
    return result({'child_context': {'goal': {'kind': 'find_value'},
                                    'evaluation_goal': deepcopy(row['evaluation_goal'])}},
                  ['finite_range_partition'],
                  [{'kind': 'source_bound_input', 'passed': True, 'input_id': row['id']}])


def collect_finite_range(context, evaluations):
    from .function_range import inputs

    rows = input_rows(context)
    if [item['case_id'] for item in evaluations] != [row['id'] for row in rows]:
        raise LocalCheckFailed('range.finite_input_coverage_mismatch')
    function, variable, domain = inputs(context['range_goal'])
    values = []
    for row, item in zip(rows, evaluations, strict=True):
        evaluated = item['outputs']['evaluation_result']
        expected = sp.simplify(function.subs(variable, row['input']))
        if (item['domain'] != row['domain'] or item['condition'] != row['condition']
                or not evaluation.verify(row['evaluation_goal'], evaluated)
                or evaluated['defined'] is not True or evaluated['kind'] != 'scalar_value'
                or evaluated['value'] != expected):
            raise LocalCheckFailed('range.finite_value_mismatch')
        values.append({'id': row['id'], 'input': row['input'], 'output': expected,
                       'substitution_latex': evaluated['calls'][0]['substitution_latex']})
    image = sp.FiniteSet(*(row['output'] for row in values))
    desc = deepcopy(context['range_goal'])
    desc['enumeration_rows'] = values
    return result({'description': desc, 'function': function, 'variable': variable, 'domain': domain,
                   'range': {'set': image}, 'feasible_set': image},
                  ['finite_range_collection'],
                  [{'kind': 'complete_verified_output_set', 'passed': True, 'domain': domain,
                    'image': image, 'rows': values}])


def phase_view(values):
    from .abstract_domain_presentation import _set_latex
    from .evaluation_presentation import _choice, _math
    from .math_values import latex
    from .range_presentation import _card, _image_choices, _source_definition

    desc = values['description']
    rows = desc['enumeration_rows']
    name, variable = desc['function_name'], latex(values['variable'])
    table = (r'\begin{array}{c|c}' + variable + '&' + name + '(' + variable + r')\\\hline '
             + r'\\'.join(latex(row['input']) + '&' + latex(row['output']) for row in rows) + r'\end{array}')
    if values['phase'] == 'finite_evaluate':
        outputs = [row['output'] for row in rows]
        def sequence(items):
            return r',\;'.join(latex(v) for v in items)
        wrong = [outputs[0]+1, *outputs[1:]]
        interaction, expected = _choice(f'${sequence(outputs)}$', [f'${sequence(wrong)}$'])
        return _card('逐一代入', '将左侧列出的输入依次代入，得到的函数值依次是什么？',
                     '函数与全部输入', _source_definition(desc, values['variable']) + r',\quad '
                     + variable + r'\in' + _set_latex(values['domain']),
                     '输入—输出表', table,
                     _math(*(rf'{name}({latex(row["input"])})={row["substitution_latex"]}={latex(row["output"])}'
                             for row in rows)), interaction, expected)
    image = values['range']['set']
    distractor = (sp.Interval(min(image), max(image)) if len(image) > 1 else values['domain'])
    interaction, expected = _choice(f'${_set_latex(image)}$', [f'${_set_latex(distractor)}$']) if distractor != image else _image_choices(image, values['domain'])
    return _card('收集输出，得到值域', '收集表中出现的全部函数值，相同的值只保留一次。值域是什么？',
                 '输入—输出表', table, '全部不同的输出', _set_latex(image),
                 _math(rf'{name}({variable})\in{_set_latex(image)}'), interaction, expected)
