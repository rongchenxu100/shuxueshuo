"""Evidence-based range method cards; no artificial coordinate axes."""

import sympy as sp

from .abstract_domain_presentation import _set_latex
from .function_range import EQUATION_METHOD, FRACTION_METHOD, admitted, inputs
from .range_presentation import _source_definition, domain_prerequisite


def select_rational_range(context, contract, primary):
    desc = context['range_goal']
    function, x, domain = inputs(desc)
    numerator, denominator = sp.fraction(function)
    _, remainder = sp.div(numerator, denominator, x)
    constant = not remainder.has(x)
    can_fraction, can_equation = (admitted(context, method) for method in (FRACTION_METHOD, EQUATION_METHOD))
    preferred_branch = 'fraction' if can_fraction and (constant or not can_equation) else 'equation'
    branches, options, verdicts = [], [], {}
    for branch_id, method in [('fraction', FRACTION_METHOD), ('equation', EQUATION_METHOD)]:
        route = next(row for row in contract['routes'] if row['method'] == method)
        executable = admitted(context, method)
        preferred = executable and branch_id == preferred_branch
        if branch_id == 'fraction':
            message = ('本题可分离常数，求分母范围后取倒数并还原。' if constant else
                       '本题可分离常数，再通过对勾函数等中间函数求范围，并处理同除时排除的输入。') if executable else (
                       '本题分离后的中间函数超出当前支持范围，这条路线暂不能进入。')
        elif executable:
            message = '本题满足条件，反解方程的实根都是合法输入；求解时仍需检查次数退化。'
        elif domain != sp.S.Reals:
            message = '本题的定义域不是全体实数，当前路线尚不处理域内实根筛选。'
        else:
            message = '当前路线要求原分母恰为二次且全域非零、分子至多二次，本题未满足这些条件。'
        if preferred:
            message = '本题推荐。' + message
        branch = {'branch': branch_id, 'target': method, 'route_id': route['route_id'],
                  'trigger': 'triggered', 'applicability': 'applicable' if executable else 'unknown',
                  'recommendation': 'preferred' if preferred else 'optional' if executable else None,
                  'route_plan': 'capability_gap', 'missing_capabilities': [f'execution:{method}'],
                  'checks': [{'check_id': 'effective_input_domain', 'status': 'holds', 'domain': str(domain)},
                             {'check_id': route['admission'], 'status': 'holds' if executable else 'unknown'}]}
        branches.append(branch)
        options.append({'route_id': route['route_id'], 'branch': branch_id, 'method': method,
                        'recommendation': branch['recommendation'], 'route_plan': 'capability_gap', 'message': message})
        verdicts[branch_id] = {'value': 'fit' if executable else 'unknown', 'message': message}
    d3 = {'id': 'D3', 'title': '判断并选择求值域的方法',
          'question': '定义域已确定。结合下面的适用条件，选择本次求值域的方法。',
          'query': {'op': 'methods', 'from': primary},
          'interaction': {'type': 'method_cards',
                          'facts': [f'${_source_definition(desc,x)}$', f'$D={_set_latex(domain)}$'],
                          'checks': [],
                          'method_notes': {'fraction': '先分离常数；按余项求分母或对勾函数的范围，再取倒数、还原并合并。',
                                           'equation': r'适用条件：分子至多二次，原分母为二次式，定义域为 $\mathbb R$ 且分母全域非零。令 $y=f(x)$，分次数判断方程有实根。'}},
          'expected_answer': {'checks': {}},
          'verdicts': verdicts, 'submit_label': '确认方法，开始解题',
          'prerequisites': [domain_prerequisite(desc)]}
    return {'status': 'no_verified_route',
            'selection': {'kind': 'method_cards', 'rule': contract['rule'], 'branches': branches,
                          'recommendation_rule': 'constant_remainder_first',
                          'recommendation_checks': [{'check_id': 'constant_remainder', 'status': 'holds' if constant else 'fails'}]},
            'd3': d3, 'd4': {'id': 'D4', 'title': '解题路线', 'options': options}, 'diagnostics': []}
